"""bw-worker — run background jobs. `--once` drains the queue and exits
(used by tests and cron-style setups); default is a polling loop."""

import argparse
import logging
import os

from bullwright_db import make_engine
from bullwright_news import EdgarClient, OllamaSentimentAnalyzer, SentimentAnalyzer
from bullwright_rag import Embedder, OllamaEmbedder
from sqlalchemy import Engine

from bullwright_worker.jobs import blog_export, make_embed_report
from bullwright_worker.quant_jobs import backtest_job, composite_calc, index_calc, price_ingest
from bullwright_worker.runner import JobRunner
from bullwright_worker.signal_jobs import (
    EdgarLike,
    alert_scan,
    make_sec_sync,
    make_sentiment_analyze,
    news_crawl,
)


def build_runner(
    engine: Engine | None = None,
    embedder: Embedder | None = None,
    edgar: EdgarLike | None = None,
    sentiment: SentimentAnalyzer | None = None,
) -> JobRunner:
    engine = engine or make_engine(os.environ.get("BW_DB_URL"))
    embedder = embedder or OllamaEmbedder()
    edgar = edgar or EdgarClient()
    sentiment = sentiment or OllamaSentimentAnalyzer()
    return JobRunner(
        engine,
        handlers={
            "embed_report": make_embed_report(embedder),
            "blog_export": blog_export,
            "price_ingest": price_ingest,
            "index_calc": index_calc,
            "composite_calc": composite_calc,
            "backtest": backtest_job,
            "news_crawl": news_crawl,
            "sec_sync": make_sec_sync(edgar),
            "sentiment_analyze": make_sentiment_analyze(sentiment),
            "alert_scan": alert_scan,
        },
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser("bw-worker")
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    parser.add_argument("--poll", type=float, default=2.0, help="poll interval seconds")
    args = parser.parse_args()

    runner = build_runner()
    if args.once:
        while runner.run_once():
            pass
    else:
        runner.run_forever(args.poll)


if __name__ == "__main__":
    main()
