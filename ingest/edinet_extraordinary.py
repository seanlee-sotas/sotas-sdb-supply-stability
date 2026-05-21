"""Axis 6 (供給途絶) ingest — EDINET 臨時報告書 (docTypeCode=180).

臨時報告書は、上場会社が緊急性のある重要事象（火災・操業停止・親子会社変動・
訴訟・多額の損害・代表者異動など）を開示する法定書類。SEC 8-K の日本相当。

This script:
1. Loads JP化学+隣接7業種 443社 (edinet_code 付き) from /research-company-jp
2. Scans EDINET documents.json for the last N days
3. Filters docTypeCode=180/190 + edinetCode in 443社
4. Outputs metadata (docDescription contains the event title) to parquet

Uses the same EDINET API key as the existing /research-company-jp pipeline.
"""
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "edinet"
VAULT = Path("/Users/seanlee/My Drive (sean.lee@sotas.co.jp)/Vault")
COMPANIES_JSON = VAULT / "_scripts" / "research-company" / "jp" / "companies.json"
EDINET_KEY_PATH = VAULT / "_scripts" / "research-company" / "jp" / "edinet_api_key.txt"

API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
HEADERS = {"User-Agent": "Sotas SDB Supply-Stability Research"}
REQUEST_SLEEP = 0.3  # ~3 req/s, generous w.r.t. EDINET limit

DOC_TYPE_EXTRAORDINARY = "180"
DOC_TYPE_EXTRAORDINARY_AMEND = "190"

# Window: default to last 365 days (capture annual cycle); CLI override possible
DEFAULT_WINDOW_DAYS = 365


def load_api_key() -> str:
    if not EDINET_KEY_PATH.exists():
        print(f"ERROR: {EDINET_KEY_PATH} not found", file=sys.stderr)
        sys.exit(2)
    return EDINET_KEY_PATH.read_text(encoding="utf-8").strip()


def load_chemical_companies() -> dict[str, dict]:
    """Return dict keyed by edinet_code for fast lookup."""
    companies = json.loads(COMPANIES_JSON.read_text(encoding="utf-8"))
    return {c["edinet_code"]: c for c in companies if c.get("edinet_code")}


def fetch_listing(d: date, key: str) -> dict:
    r = requests.get(
        f"{API_BASE}/documents.json",
        params={"date": d.isoformat(), "type": 2, "Subscription-Key": key},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def main(window_days: int = DEFAULT_WINDOW_DAYS):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = load_api_key()
    targets = load_chemical_companies()
    print(f"Loaded {len(targets)} JP chemical+adjacent companies (edinet_code-indexed)")

    end = date.today()
    start = end - timedelta(days=window_days)
    print(f"Scanning EDINET {start} → {end} ({window_days} days) for docTypeCode 180/190…")

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    d = start
    days_scanned = 0
    total_docs = 0
    while d <= end:
        days_scanned += 1
        if days_scanned % 30 == 0 or days_scanned == 1:
            print(f"  [{days_scanned}/{window_days}] {d}  | hits so far: {len(rows)}", flush=True)
        try:
            data = fetch_listing(d, key)
        except requests.HTTPError as e:
            print(f"  HTTP error {d}: {e}; skip")
            d += timedelta(days=1)
            continue
        for row in data.get("results", []):
            total_docs += 1
            if row.get("docTypeCode") not in (DOC_TYPE_EXTRAORDINARY, DOC_TYPE_EXTRAORDINARY_AMEND):
                continue
            ed_code = row.get("edinetCode")
            if not ed_code or ed_code not in targets:
                continue
            company = targets[ed_code]
            rows.append({
                "doc_id": row.get("docID"),
                "edinet_code": ed_code,
                "ticker": company.get("ticker"),
                "company": company.get("name"),
                "company_full": company.get("name_full"),
                "industry": company.get("industry"),
                "submit_date": row.get("submitDateTime", "")[:10],
                "submit_datetime": row.get("submitDateTime"),
                "doc_type_code": row.get("docTypeCode"),
                "doc_description": row.get("docDescription") or "",
                "ordinance_code": row.get("ordinanceCode"),
                "form_code": row.get("formCode"),
                "withdrawal_status": row.get("withdrawalStatus"),
                "doc_info_edit_status": row.get("docInfoEditStatus"),
                "disclosure_status": row.get("disclosureStatus"),
                "xbrl_flag": row.get("xbrlFlag"),
                "pdf_flag": row.get("pdfFlag"),
                "_fetched_at": fetched_at,
            })
        time.sleep(REQUEST_SLEEP)
        d += timedelta(days=1)

    print(f"\nScanned {days_scanned} days, {total_docs:,} total documents, {len(rows)} extraordinary reports from chemical universe")

    if not rows:
        print("No extraordinary reports found in window. Output skipped.")
        return

    df = pd.DataFrame(rows)
    # Build viewing URL for each report
    df["pdf_url"] = df["doc_id"].map(lambda d: f"https://disclosure2.edinet-fsa.go.jp/api/v2/documents/{d}?type=2")
    df["viewer_url"] = df["doc_id"].map(lambda d: f"https://disclosure2.edinet-fsa.go.jp/PublicSearch/W1E63010/{d}")

    stamp = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"extraordinary_reports_{stamp}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(df)} rows → {out_path}")
    print(f"\n企業別 件数 Top 15:")
    print(df.groupby("company").size().sort_values(ascending=False).head(15).to_string())
    print(f"\n業種別 件数:")
    print(df.groupby("industry").size().sort_values(ascending=False).to_string())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS, help="Window in days (default 365)")
    args = ap.parse_args()
    main(window_days=args.days)
