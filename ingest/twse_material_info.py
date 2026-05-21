"""Axis 6 — TWSE/TPEX 重大訊息 (Material Information) ingest via mopsov.twse.com.tw.

Uses the new MOPS UI domain (mopsov) which serves the daily list of material info
across all listed companies (上市 sii / 上櫃 otc). The old mops.twse.com.tw domain
has aggressive anti-bot, but mopsov works with a simple POST.

Endpoint: POST https://mopsov.twse.com.tw/mops/web/ajax_t05st01
Returns HTML table: 公司代號 | 公司名稱 | 發言日期 | 發言時間 | 主旨
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
OUT_DIR = ROOT / "data" / "twse"

BASE = "https://mopsov.twse.com.tw/mops/web/ajax_t05st01"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://mopsov.twse.com.tw/mops/web/t05st01",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded",
}
REQUEST_SLEEP = 0.8

DEFAULT_WINDOW_DAYS = 90

# Taiwan chemical+adjacent industries (TWSE 產業類別 codes):
# 13 化學工業 | 14 生技醫療 | 15 玻璃陶瓷 | 16 造紙 | 22 橡膠 | 17 鋼鐵 | 27 半導體 | 11 塑膠工業
# Simpler approach: include ALL filings, filter downstream by company industry list.
# For now we include both SII (上市) and OTC (上櫃).

ROW_RE = re.compile(
    r"<tr[^>]*>\s*"
    r"<td[^>]*>(?P<code>\d{4})</td>\s*"
    r"<td[^>]*>(?P<name>[^<]+)</td>\s*"
    r"<td[^>]*>(?P<date>\d{3}/\d{2}/\d{2})</td>\s*"
    r"<td[^>]*>(?P<time>[^<]+)</td>\s*"
    r"<td[^>]*>(?P<subject>.*?)</td>",
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


def fetch_month_window(year_roc: int, month: int, b_date: int, e_date: int, market: str) -> str | None:
    """Date-range query within a single ROC month."""
    payload = {
        "encodeURIComponent": "1",
        "step": "1",
        "firstin": "1",
        "off": "1",
        "year": str(year_roc),
        "month": f"{month:02d}",
        "b_date": str(b_date),
        "e_date": str(e_date),
        "TYPEK": market,
    }
    try:
        r = requests.post(BASE, headers=HEADERS, data=payload, timeout=60)
        if r.status_code != 200:
            return None
        r.encoding = "utf-8"
        return r.text
    except requests.RequestException:
        return None


def parse_rows(html: str) -> list[dict]:
    out: list[dict] = []
    for m in ROW_RE.finditer(html):
        subject = TAG_RE.sub("", m.group("subject"))
        subject = unescape(re.sub(r"\s+", " ", subject)).strip()
        out.append({
            "ticker": m.group("code").strip(),
            "company_name": unescape(m.group("name")).strip(),
            "filing_date_roc": m.group("date").strip(),
            "filing_time": m.group("time").strip(),
            "subject": subject,
        })
    return out


def roc_to_iso(roc: str) -> str:
    """'115/05/20' → '2026-05-20'"""
    try:
        y, mo, d = roc.split("/")
        return f"{int(y) + 1911:04d}-{mo}-{d}"
    except ValueError:
        return ""


def main(window_days: int = DEFAULT_WINDOW_DAYS):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    end = date.today()
    bgn = end - timedelta(days=window_days)
    print(f"TWSE/TPEX 重大訊息 window: {bgn} → {end} ({window_days} days)")

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    # Iterate month-by-month windows (TWSE accepts ranges within one month).
    # For each (year_roc, month) overlapping the window, query 1-15 and 16-end.
    current = bgn.replace(day=1)
    months_done = 0
    while current <= end:
        roc_year = current.year - 1911
        month = current.month
        # Determine last day of this month
        if month == 12:
            next_month = current.replace(year=current.year + 1, month=1)
        else:
            next_month = current.replace(month=month + 1)
        last_day = (next_month - timedelta(days=1)).day
        slots = [(1, 15), (16, last_day)]
        months_done += 1
        print(f"  [{months_done}] 民國{roc_year}/{month:02d} (slots 2)", flush=True)
        for b, e in slots:
            for market in ("sii", "otc"):
                html = fetch_month_window(roc_year, month, b, e, market)
                if not html:
                    continue
                for r in parse_rows(html):
                    r["market"] = market
                    r["filing_date"] = roc_to_iso(r["filing_date_roc"])
                    r["_fetched_at"] = fetched_at
                    rows.append(r)
                time.sleep(REQUEST_SLEEP)
        current = next_month
    n_days = (end - bgn).days
    # Filter to the actual window (we over-fetched month edges)
    rows = [r for r in rows if r.get("filing_date") and bgn.isoformat() <= r["filing_date"] <= end.isoformat()]
    # Dedupe on (ticker, filing_date, filing_time, subject)
    seen = set()
    deduped = []
    for r in rows:
        key = (r["ticker"], r["filing_date"], r["filing_time"], r["subject"][:60])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    rows = deduped

    print(f"\n合計 {len(rows)} 重大訊息 / {n_days} days")

    if not rows:
        print("No data collected.")
        return

    df = pd.DataFrame(rows)
    # Filter to chemical-relevant TWSE industries by company code range / known company list
    # For now, keep all and filter at scoring time. Later: add companies.json for TW.
    stamp = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"twse_material_info_{stamp}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(df)} rows → {out_path}")

    print(f"\n企業別 件数 Top 15:")
    print(df.groupby("company_name").size().sort_values(ascending=False).head(15).to_string())
    print(f"\n市場別:")
    print(df["market"].value_counts().to_string())
    print(f"\nサンプル subject 10件:")
    for s in df["subject"].sample(min(10, len(df)), random_state=42).tolist():
        print(f"  - {s[:120]}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
    args = ap.parse_args()
    main(window_days=args.days)
