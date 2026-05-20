"""Fetch SEC 8-K filings (current reports) from major US chemical companies.

8-K filings are filed within 4 business days of significant events. For our axis 6
(供給途絶), we care about items that disclose plant shutdowns, fires, force majeure,
hurricanes, cyber incidents, and material impairments.

Filters (post-fetch, dashboard side) on item codes:
- Item 2.06: Material Impairments
- Item 8.01: Other Events (often where FM declarations land)
- Item 2.04: Triggering Events That Accelerate Financial Obligations
- Item 1.03: Bankruptcy

Source: SEC EDGAR data API (https://data.sec.gov/), no auth required, UA mandatory.
Rate limit: ~10 requests/sec.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "sec"

# Major US chemical companies + CIKs.
# CIK lookup: https://www.sec.gov/cgi-bin/browse-edgar?company=NAME&CIK=&type=&owner=include&count=10
COMPANIES = [
    {"ticker": "DOW", "cik": "0001751788", "name": "Dow Inc"},
    {"ticker": "DD",  "cik": "0001666700", "name": "DuPont de Nemours"},
    {"ticker": "LYB", "cik": "0001489393", "name": "LyondellBasell Industries"},
    {"ticker": "EMN", "cik": "0000915389", "name": "Eastman Chemical"},
    {"ticker": "WLK", "cik": "0001262823", "name": "Westlake Corp"},
    {"ticker": "CE",  "cik": "0001306830", "name": "Celanese"},
    {"ticker": "APD", "cik": "0000002969", "name": "Air Products & Chemicals"},
    {"ticker": "LIN", "cik": "0001707925", "name": "Linde plc"},
    {"ticker": "OLN", "cik": "0000074260", "name": "Olin Corp"},
    {"ticker": "HUN", "cik": "0001307954", "name": "Huntsman Corp"},
    {"ticker": "ASH", "cik": "0001674862", "name": "Ashland Inc"},
    {"ticker": "CC",  "cik": "0001545654", "name": "Chemours"},
    {"ticker": "ALB", "cik": "0000915913", "name": "Albemarle"},
    {"ticker": "PPG", "cik": "0000079879", "name": "PPG Industries"},
    {"ticker": "SHW", "cik": "0000089800", "name": "Sherwin-Williams"},
]

UA = "Sotas SDB Supply-Stability Research burnoutpapa@gmail.com"
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
SUB_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


def fetch_submissions(cik: str) -> dict:
    r = requests.get(SUB_URL.format(cik=cik), headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def extract_8k_recent(sub: dict, company: dict, since_year: int = 2023) -> list[dict]:
    """Extract 8-K rows from the 'recent' submissions block."""
    recent = sub.get("filings", {}).get("recent", {})
    if not recent:
        return []
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    items = recent.get("items", [])
    primary_docs = recent.get("primaryDocument", [])
    primary_docdescs = recent.get("primaryDocDescription", [])
    rows = []
    for i, form in enumerate(forms):
        if form not in ("8-K", "8-K/A"):
            continue
        date_str = dates[i] if i < len(dates) else ""
        if date_str and int(date_str[:4]) < since_year:
            continue
        rows.append({
            "ticker": company["ticker"],
            "cik": company["cik"],
            "company_name": company["name"],
            "form": form,
            "filing_date": date_str,
            "accession": accs[i] if i < len(accs) else "",
            "items": items[i] if i < len(items) else "",
            "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
            "primary_desc": primary_docdescs[i] if i < len(primary_docdescs) else "",
        })
    return rows


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()
    all_rows: list[dict] = []

    for i, company in enumerate(COMPANIES, 1):
        print(f"[{i}/{len(COMPANIES)}] {company['ticker']} ({company['name']})", flush=True)
        try:
            sub = fetch_submissions(company["cik"])
        except requests.RequestException as e:
            print(f"  FAIL: {e}", flush=True)
            continue
        rows = extract_8k_recent(sub, company, since_year=2023)
        for r in rows:
            r["_fetched_at"] = fetched_at
        all_rows.extend(rows)
        print(f"  -> {len(rows)} 8-K filings since 2023", flush=True)
        time.sleep(0.2)  # SEC limit is ~10 req/sec

    if not all_rows:
        print("No filings collected", flush=True)
        return

    df = pd.DataFrame(all_rows)
    df["accession_url"] = df.apply(
        lambda r: f"https://www.sec.gov/Archives/edgar/data/{int(r['cik'])}/{r['accession'].replace('-', '')}/{r['primary_doc']}",
        axis=1,
    )
    stamp = datetime.now().strftime("%Y%m%d")
    out_path = DATA_DIR / f"filings_8k_{stamp}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(df)} 8-K filings to {out_path}")
    print(f"\nFilings per company:")
    print(df.groupby("ticker").size().sort_values(ascending=False))
    print(f"\nTop item codes (supply-disruption-relevant: 2.06, 8.01, 2.04, 1.03):")
    items_split = df["items"].fillna("").str.split(",").explode().str.strip()
    print(items_split.value_counts().head(15))


if __name__ == "__main__":
    main()
