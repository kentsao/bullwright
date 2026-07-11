"""API key lifecycle (docs/API.md §3).

Format: bw_<env>_<40 urlsafe chars>. Only the argon2id hash is stored;
key_prefix (first 12 chars of the full string) narrows the lookup. The
plaintext is shown exactly once, at mint time.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from bullwright_core.ids import new_id
from bullwright_db.models import Agent, ApiKey
from sqlalchemy import select
from sqlalchemy.orm import Session

_hasher = PasswordHasher(time_cost=2, memory_cost=32 * 1024, parallelism=2)

VALID_SCOPES = frozenset(
    {
        "reports:write",
        "reports:read",
        "search:read",
        "market:read",
        "backtest:run",
        "admin",
    }
)

PREFIX_LEN = 12


@dataclass(frozen=True)
class Principal:
    key_id: str
    agent_id: str
    agent_name: str
    agent_kind: str
    scopes: frozenset[str]

    def has_scope(self, scope: str) -> bool:
        return "admin" in self.scopes or scope in self.scopes

    @property
    def is_admin(self) -> bool:
        return "admin" in self.scopes


def mint_key(
    session: Session,
    agent: Agent,
    scopes: list[str],
    env: str = "live",
    expires_at: datetime | None = None,
) -> tuple[str, ApiKey]:
    bad = set(scopes) - VALID_SCOPES
    if bad:
        raise ValueError(f"unknown scopes: {sorted(bad)}")
    # A1: agent-kind principals can never hold admin.
    if "admin" in scopes and agent.kind != "human":
        raise ValueError("admin scope is operator-only; agents never get admin (rule A1)")
    plaintext = f"bw_{env}_{secrets.token_urlsafe(30)[:40]}"
    row = ApiKey(
        key_id=new_id("key"),
        agent_id=agent.agent_id,
        key_prefix=plaintext[:PREFIX_LEN],
        key_hash=_hasher.hash(plaintext),
        scopes=sorted(scopes),
        expires_at=expires_at,
    )
    session.add(row)
    return plaintext, row


def authenticate(session: Session, token: str) -> Principal | None:
    """Verify a presented key. Hits the DB every call — key revocation must
    be effective within seconds (rule S7), so no caching."""
    if not token.startswith("bw_") or len(token) < PREFIX_LEN + 8:
        return None
    now = datetime.now(UTC)
    candidates = session.scalars(
        select(ApiKey).where(ApiKey.key_prefix == token[:PREFIX_LEN])
    ).all()
    for row in candidates:
        if row.revoked_at is not None:
            continue
        if row.expires_at is not None and _as_utc(row.expires_at) < now:
            continue
        try:
            _hasher.verify(row.key_hash, token)
        except VerifyMismatchError:
            continue
        agent = session.get(Agent, row.agent_id)
        if agent is None or not agent.is_active:
            return None
        return Principal(
            key_id=row.key_id,
            agent_id=agent.agent_id,
            agent_name=agent.name,
            agent_kind=agent.kind,
            scopes=frozenset(str(s) for s in row.scopes),
        )
    return None


def _as_utc(dt: datetime) -> datetime:
    # SQLite returns naive datetimes; they were stored as UTC.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
