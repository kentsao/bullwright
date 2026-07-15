"""Market data behind a protocol (docs/ARCHITECTURE.md §9).

FixtureProvider is the framework default: deterministic synthetic data,
zero network, works in CI and for template users without any API. Real
providers (yfinance today, EDGAR/paid feeds later) are adapters."""

import hashlib
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol


@dataclass(frozen=True)
class Bar:
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


class MarketDataProvider(Protocol):
    name: str

    def fetch_daily(self, symbols: list[str], start: date, end: date) -> dict[str, list[Bar]]: ...

    def fetch_fundamentals(self, symbols: list[str]) -> dict[str, dict[str, Any]]: ...


class FixtureProvider:
    """Seeded per-symbol random walk — same symbol, same dates, same data,
    forever. Weekdays only."""

    name = "fixture"

    def _seed(self, symbol: str) -> int:
        return int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:4], "big")

    def fetch_daily(self, symbols: list[str], start: date, end: date) -> dict[str, list[Bar]]:
        out: dict[str, list[Bar]] = {}
        for symbol in symbols:
            seed = self._seed(symbol)
            price = 50.0 + (seed % 200)
            drift = ((seed % 7) - 3) * 2e-4  # between -6e-4 and +6e-4 daily
            bars: list[Bar] = []
            day = start
            i = 0
            while day <= end:
                if day.weekday() < 5:
                    wave = 0.01 * math.sin(i / 9.0 + seed % 10)
                    price = max(1.0, price * (1.0 + drift + wave * 0.3))
                    bars.append(
                        Bar(
                            bar_date=day,
                            open=round(price * 0.999, 4),
                            high=round(price * 1.006, 4),
                            low=round(price * 0.994, 4),
                            close=round(price, 4),
                            adj_close=round(price, 4),
                            volume=1_000_000 + (seed + i * 977) % 500_000,
                        )
                    )
                    i += 1
                day += timedelta(days=1)
            out[symbol] = bars
        return out

    def fetch_fundamentals(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        out = {}
        for symbol in symbols:
            seed = self._seed(symbol)
            out[symbol] = {
                "pe": 10.0 + seed % 30,
                "ps": 1.0 + seed % 12,
                "ev_ebitda": 8.0 + seed % 20,
                "roe": 0.05 + (seed % 25) / 100.0,
                "gross_margin": 0.25 + (seed % 50) / 100.0,
                "debt_to_equity": (seed % 180) / 100.0,
            }
        return out


class YFinanceProvider:
    """Free-data adapter. Known limitations, accepted for local use:
    fields go missing, history of fundamentals does not exist (snapshot
    accretes from first ingest), and terms prohibit redistribution —
    which is why data/ is gitignored."""

    name = "yfinance"

    def fetch_daily(self, symbols: list[str], start: date, end: date) -> dict[str, list[Bar]]:
        import yfinance as yf  # type: ignore[import-not-found]  # optional extra

        out: dict[str, list[Bar]] = {}
        frame = yf.download(
            symbols,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            progress=False,
            group_by="ticker",
        )
        for symbol in symbols:
            sub = frame[symbol] if len(symbols) > 1 else frame
            bars: list[Bar] = []
            for ts, row in sub.dropna(subset=["Close"]).iterrows():
                bars.append(
                    Bar(
                        bar_date=ts.date(),
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        adj_close=float(row.get("Adj Close", row["Close"])),
                        volume=int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                    )
                )
            out[symbol] = bars
        return out

    def fetch_fundamentals(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        import yfinance as yf

        out: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            info = yf.Ticker(symbol).info or {}
            gm = info.get("grossMargins")
            de = info.get("debtToEquity")
            out[symbol] = {
                "pe": info.get("trailingPE"),
                "ps": info.get("priceToSalesTrailing12Months"),
                "ev_ebitda": info.get("enterpriseToEbitda"),
                "roe": info.get("returnOnEquity"),
                "gross_margin": gm,
                # yfinance reports D/E as a percentage
                "debt_to_equity": (de / 100.0) if isinstance(de, int | float) else None,
            }
        return out


def get_provider(name: str) -> MarketDataProvider:
    if name == "fixture":
        return FixtureProvider()
    if name == "yfinance":
        return YFinanceProvider()
    raise KeyError(f"unknown market data provider {name!r} (have: fixture, yfinance)")
