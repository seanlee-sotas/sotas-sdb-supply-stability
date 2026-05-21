"""Axis 6 (供給途絶) ingest — TDnet 適時開示 (Timely Disclosure).

TDnet is JPX's real-time corporate disclosure service. Filings include:
- 業績修正
- 火災・事故・操業停止
- リコール
- M&A
- ストックオプション付与

Coverage: 東証/名証/福証/札証全上場社、~31日履歴のみ (older data not retained).
URL pattern: https://www.release.tdnet.info/inbs/I_list_NNN_YYYYMMDD.html
where NNN = page (001, 002, ...) and the page returns 404 when exhausted.

No auth, but requires UA header.
"""
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "tdnet"
VAULT = Path("/Users/seanlee/My Drive (sean.lee@sotas.co.jp)/Vault")
JP_COMPANIES = VAULT / "_scripts" / "research-company" / "jp" / "companies.json"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.7"}
BASE = "https://www.release.tdnet.info/inbs"
REQUEST_SLEEP = 0.3

DEFAULT_WINDOW_DAYS = 31  # TDnet retention limit

ROW_RE = re.compile(
    r'kjTime[^>]*>(?P<time>[^<]+)<'
    r'.{0,2000}?kjCode[^>]*>(?P<code>[^<]+)<'
    r'.{0,2000}?kjName[^>]*>(?P<name>[^<]+)<'
    r'.{0,2000}?kjPlace[^>]*>(?P<place>[^<]+)<'
    r'.{0,2000}?kjTitle[^>]*>(?P<title>.*?)</td>',
    re.DOTALL,
)
LINK_RE = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>')


def load_chemical_tickers() -> dict[str, dict]:
    """Return dict {ticker_4digit: company_meta}."""
    import json
    companies = json.loads(JP_COMPANIES.read_text(encoding="utf-8"))
    return {c["ticker"]: c for c in companies if c.get("ticker")}


def fetch_page(d: date, page: int) -> str | None:
    url = f"{BASE}/I_list_{page:03d}_{d.strftime('%Y%m%d')}.html"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        print(f"  HTTP {r.status_code} for {url}")
        return None
    r.encoding = "utf-8"  # TDnet pages are UTF-8 but Content-Type lacks charset
    return r.text


def parse_rows(html: str) -> list[dict]:
    out: list[dict] = []
    for m in ROW_RE.finditer(html):
        title_html = m.group("title")
        # Extract title text + PDF link
        link_m = LINK_RE.search(title_html)
        if link_m:
            pdf_path = link_m.group(1)
            title = unescape(link_m.group(2)).strip()
        else:
            pdf_path = ""
            # Strip any HTML tags
            title = unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        code = m.group("code").strip()
        # TDnet uses 5-digit codes with trailing 0 → strip to 4-digit ticker
        ticker_4 = code[:4] if len(code) == 5 else code
        out.append({
            "time": m.group("time").strip(),
            "code_5": code,
            "ticker": ticker_4,
            "company_name_tdnet": unescape(m.group("name")).strip(),
            "place": unescape(m.group("place")).strip(),
            "title": title,
            "pdf_relpath": pdf_path,
        })
    return out


def main(window_days: int = DEFAULT_WINDOW_DAYS):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tickers = load_chemical_tickers()
    print(f"Loaded {len(tickers)} JP chemical+adjacent companies (ticker-indexed)")

    end = date.today()
    bgn = end - timedelta(days=window_days)
    print(f"TDnet window: {bgn} → {end} ({window_days} days, 31日制限)")

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    d = bgn
    days_scanned = 0
    total_filings = 0
    while d <= end:
        days_scanned += 1
        if days_scanned % 7 == 0 or days_scanned == 1:
            print(f"  [{days_scanned}/{window_days}] {d}  | hits so far: {len(rows)}", flush=True)
        page = 1
        while True:
            html = fetch_page(d, page)
            if html is None:
                break
            page_rows = parse_rows(html)
            if not page_rows:
                break
            total_filings += len(page_rows)
            for r in page_rows:
                if r["ticker"] not in tickers:
                    continue
                co_meta = tickers[r["ticker"]]
                rows.append({
                    "date": d.isoformat(),
                    "time": r["time"],
                    "ticker": r["ticker"],
                    "company": co_meta["name"],
                    "company_full": co_meta.get("name_full"),
                    "industry": co_meta.get("industry"),
                    "market_tier": co_meta.get("market_tier"),
                    "company_name_tdnet": r["company_name_tdnet"],
                    "place": r["place"],
                    "title": r["title"],
                    "pdf_url": f"{BASE}/{r['pdf_relpath']}" if r["pdf_relpath"] else "",
                    "_fetched_at": fetched_at,
                })
            page += 1
            time.sleep(REQUEST_SLEEP)
        d += timedelta(days=1)

    print(f"\nScanned {days_scanned} days, {total_filings:,} total filings (all companies), {len(rows)} from chemical universe")

    if not rows:
        print("No filings collected.")
        return

    df = pd.DataFrame(rows)
    stamp = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"tdnet_disclosure_{stamp}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(df)} rows → {out_path}")

    print(f"\n企業別 件数 Top 15:")
    print(df.groupby("company").size().sort_values(ascending=False).head(15).to_string())
    print(f"\n業種別 件数:")
    print(df.groupby("industry").size().sort_values(ascending=False).to_string())
    print(f"\nタイトル サンプル (供給途絶関連を含むかLLM分類対象):")
    for t in df["title"].sample(min(10, len(df)), random_state=42).tolist():
        print(f"  - {t[:120]}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
    args = ap.parse_args()
    main(window_days=args.days)
