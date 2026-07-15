"""SEC EDGAR client — official JSON APIs only (ADR-0002 §2).

SEC requires a descriptive User-Agent with contact info; set
BW_EDGAR_UA. Endpoints used:
- ticker->CIK map: https://www.sec.gov/files/company_tickers.json
- submissions:     https://data.sec.gov/submissions/CIK##########.json
"""

import os
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx2 as httpx

IMPORTANT_FORMS = {"10-K", "10-Q", "8-K", "S-1", "4", "SC 13D", "SC 13G", "DEF 14A"}
MAX_FILINGS = 40


@dataclass(frozen=True)
class FilingRecord:
    accession_no: str
    ticker: str
    form_type: str
    filed_at: date
    title: str | None
    url: str | None

    @property
    def is_important(self) -> bool:
        return self.form_type in IMPORTANT_FORMS


class EdgarClient:
    def __init__(self, user_agent: str | None = None, timeout: float = 20.0) -> None:
        self.user_agent = user_agent or os.environ.get(
            "BW_EDGAR_UA", "Bullwright research framework (set BW_EDGAR_UA with contact)"
        )
        self.timeout = timeout
        self._cik_cache: dict[str, str] | None = None

    def _get(self, url: str) -> Any:
        resp = httpx.get(
            url,
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return resp.json()

    def cik_for(self, symbol: str) -> str | None:
        if self._cik_cache is None:
            raw = self._get("https://www.sec.gov/files/company_tickers.json")
            self._cik_cache = {
                str(row["ticker"]).upper(): f"{int(row['cik_str']):010d}" for row in raw.values()
            }
        return self._cik_cache.get(symbol.upper())

    def recent_filings(self, symbol: str) -> list[FilingRecord]:
        cik = self.cik_for(symbol)
        if cik is None:
            return []
        data = self._get(f"https://data.sec.gov/submissions/CIK{cik}.json")
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        docs = recent.get("primaryDocument", [])
        descs = recent.get("primaryDocDescription", [])
        out: list[FilingRecord] = []
        for i in range(min(len(forms), MAX_FILINGS)):
            accession = str(accessions[i])
            plain = accession.replace("-", "")
            doc = docs[i] if i < len(docs) else ""
            out.append(
                FilingRecord(
                    accession_no=accession,
                    ticker=symbol.upper(),
                    form_type=str(forms[i]),
                    filed_at=date.fromisoformat(str(dates[i])),
                    title=(descs[i] or None) if i < len(descs) else None,
                    url=(
                        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{plain}/{doc}"
                        if doc
                        else None
                    ),
                )
            )
        return out


class FixtureEdgarClient:
    """Offline stand-in: canned filings for tests/CI."""

    def __init__(self, filings: dict[str, list[FilingRecord]] | None = None) -> None:
        self._filings = filings or {}

    def cik_for(self, symbol: str) -> str | None:
        return "0000000000" if symbol in self._filings else None

    def recent_filings(self, symbol: str) -> list[FilingRecord]:
        return list(self._filings.get(symbol, []))
