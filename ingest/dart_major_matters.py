"""Axis 6 (供給途絶) ingest — DART 주요사항보고서 (pblntf_ty=B).

주요사항보고서 is the Korean equivalent of SEC 8-K. Categories include:
- 화재발생 (fire)
- 생산중단/공장가동중지 (production halt)
- 사업의 양도/양수 (M&A)
- 손해배상청구의 소제기 (lawsuit)
- 회생절차 개시 (rehabilitation procedure start)
- 재해/사고 (disaster/accident)
- etc.

This script:
1. Loads KR companies (299 chemical-adjacent) from /research-company-kr
2. Queries DART list.json with pblntf_ty=B for each corp_code (last N days)
3. Outputs metadata to parquet for LLM classification downstream

Free tier limit: 10,000 req/day. 299 companies × ~1 page each = ~300 req/run.
"""
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "dart"
VAULT = Path("/Users/seanlee/My Drive (sean.lee@sotas.co.jp)/Vault")
COMPANIES_JSON = VAULT / "_scripts" / "research-company" / "kr" / "companies.json"
KEY_PATH = VAULT / "_scripts" / "research-company" / "kr" / "opendart_api_key.txt"

DART_BASE = "https://opendart.fss.or.kr/api"
HEADERS = {"User-Agent": "Sotas SDB Supply-Stability Research"}
RATE_SEC = 0.4

DEFAULT_WINDOW_DAYS = 365


def load_api_key() -> str:
    if not KEY_PATH.exists():
        print(f"ERROR: {KEY_PATH} not found", file=sys.stderr)
        sys.exit(2)
    return KEY_PATH.read_text(encoding="utf-8").strip()


def load_companies() -> list[dict]:
    return json.loads(COMPANIES_JSON.read_text(encoding="utf-8"))


def fetch_list_for_company(corp_code: str, key: str, *, bgn: date, end: date) -> list[dict]:
    """Returns all 주요사항 filings for a company in the window."""
    out: list[dict] = []
    page = 1
    while True:
        params = {
            "crtfc_key": key,
            "corp_code": corp_code,
            "bgn_de": bgn.strftime("%Y%m%d"),
            "end_de": end.strftime("%Y%m%d"),
            "pblntf_ty": "B",
            "page_no": page,
            "page_count": 100,
        }
        r = requests.get(f"{DART_BASE}/list.json", params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        status = data.get("status")
        if status == "013":  # no data
            break
        if status != "000":
            print(f"    WARN status={status} msg={data.get('message')}")
            break
        out.extend(data.get("list", []))
        time.sleep(RATE_SEC)
        if page >= data.get("total_page", 1):
            break
        page += 1
    return out


def main(window_days: int = DEFAULT_WINDOW_DAYS):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = load_api_key()
    companies = load_companies()
    companies = [c for c in companies if c.get("corp_code")]
    print(f"Loaded {len(companies)} KR chemical+adjacent companies with corp_code")

    end = date.today()
    bgn = end - timedelta(days=window_days)
    print(f"Window: {bgn} → {end} ({window_days} days)")

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for i, c in enumerate(companies, 1):
        if i % 30 == 0 or i == 1:
            print(f"  [{i}/{len(companies)}] {c['name']}  | hits so far: {len(rows)}", flush=True)
        try:
            items = fetch_list_for_company(c["corp_code"], key, bgn=bgn, end=end)
        except requests.HTTPError as e:
            print(f"    HTTP error for {c['name']}: {e}; skip")
            continue
        for item in items:
            rows.append({
                "rcept_no": item.get("rcept_no"),
                "corp_code": item.get("corp_code") or c["corp_code"],
                "corp_name": item.get("corp_name") or c["name"],
                "stock_code": c.get("stock_code"),
                "industry": c.get("industry"),
                "main_product": c.get("main_product"),
                "market_tier": c.get("market_tier"),
                "rcept_dt": item.get("rcept_dt"),
                "report_nm": item.get("report_nm"),
                "flr_nm": item.get("flr_nm"),
                "rm": item.get("rm"),
                "_fetched_at": fetched_at,
            })

    print(f"\n合計 {len(rows)} 주요사항 reports across {len(companies)} companies")

    if not rows:
        print("No reports found in window. Output skipped.")
        return

    df = pd.DataFrame(rows)
    df["viewer_url"] = df["rcept_no"].map(
        lambda r: f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r}"
    )
    stamp = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"dart_major_matters_{stamp}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(df)} rows → {out_path}")

    print(f"\n企業別 件数 Top 15:")
    print(df.groupby("corp_name").size().sort_values(ascending=False).head(15).to_string())
    print(f"\n業種別 件数:")
    print(df.groupby("industry").size().sort_values(ascending=False).head(10).to_string())
    print(f"\nreport_nm 上位パターン:")
    print(df["report_nm"].value_counts().head(15).to_string())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
    args = ap.parse_args()
    main(window_days=args.days)
