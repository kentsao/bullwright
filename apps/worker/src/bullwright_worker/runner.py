"""Job runner over the `jobs` table (docs/ARCHITECTURE.md §4).

Deliberately boring: poll, lock one job, run its handler, record the
outcome. The table doubles as the audit trail the ops dashboard reads.
Retries with attempt caps; a handler exception marks the attempt failed
and requeues until max_attempts.
"""

import logging
import socket
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from bullwright_db import make_session_factory
from bullwright_db.models import Job
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

log = logging.getLogger("bw.worker")

Handler = Callable[[Session, dict[str, Any]], str | None]


class JobRunner:
    def __init__(self, engine: Engine, handlers: dict[str, Handler]) -> None:
        self.factory = make_session_factory(engine)
        self.handlers = handlers
        self.worker_id = f"{socket.gethostname()}:{id(self):x}"

    def _claim(self, session: Session) -> Job | None:
        now = datetime.now(UTC)
        job = session.scalars(
            select(Job)
            .where(Job.status == "queued")
            .where((Job.run_after.is_(None)) | (Job.run_after <= now))
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if job is None:
            return None
        job.status = "running"
        job.locked_by = self.worker_id
        job.locked_at = now
        job.attempts += 1
        session.flush()
        return job

    def run_once(self) -> bool:
        """Process at most one job. Returns True if a job was processed."""
        session = self.factory()
        try:
            job = self._claim(session)
            if job is None:
                session.rollback()
                return False
            session.commit()  # release the claim lock before long work

            handler = self.handlers.get(job.kind)
            try:
                if handler is None:
                    raise RuntimeError(f"no handler for job kind {job.kind!r}")
                note = handler(session, dict(job.payload))
                job = session.get(Job, job.job_id)
                assert job is not None  # noqa: S101 — just claimed it
                job.status = "done"
                job.error = note
                session.commit()
                log.info("job %s (%s) done", job.job_id, job.kind)
            except Exception as e:
                session.rollback()
                assert job is not None  # noqa: S101 — claimed above
                job = session.get(Job, job.job_id)
                assert job is not None  # noqa: S101
                exhausted = job.attempts >= job.max_attempts
                job.status = "failed" if exhausted else "queued"
                job.error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"[:2000]
                session.commit()
                log.warning(
                    "job %s (%s) attempt %d failed: %s", job.job_id, job.kind, job.attempts, e
                )
            return True
        finally:
            session.close()

    def run_forever(self, poll_interval: float = 2.0) -> None:
        log.info("worker %s polling", self.worker_id)
        while True:
            if not self.run_once():
                time.sleep(poll_interval)
