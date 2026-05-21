"""Axis 2 真の需給データ強化 — JPCA 月次 エチレンクラッカー稼働率.

JPCA publishes a monthly "実績概要メモ" PDF containing the actual ethylene cracker
utilization rate (稼働プラントの実質稼働率試算). This is THE supply-demand signal
that the chemical industry watches.

Source: https://www.jpca.or.jp/files/statistics/monthly/memo/YYYYMM_memo.pdf

Format inside PDF (page 2):
  稼働プラントの実質稼働率試算：前月68.8％* → 当月67.3％ ← 前年同月78.6％
  定修プラント：前月 4社4プラント → 当月 4社4プラント ← 前年同月 なし
  生産増減に係る諸要因 (table): 日数増減, 定修要因等, 能力増減, 稼働率変動
"""
import io
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import fitz
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "jpca"
MEMO_INDEX_URL = "https://www.jpca.or.jp/statistics/monthly/memo.html"
MEMO_PDF_BASE = "https://www.jpca.or.jp/files/statistics/monthly/memo/{stamp}_memo.pdf"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
HEADERS = {"User-Agent": UA}
REQUEST_SLEEP = 0.4

# Regex patterns — JPCA memo format
RE_UTIL_TRIPLE = re.compile(
    r"稼働プラント.*?実質稼働率試算[：:]\s*"
    r"前月\s*([\d.]+)\s*[％%][^→]*→\s*"
    r"当月\s*([\d.]+)\s*[％%][^←]*←\s*"
    r"前年同月\s*([\d.]+)\s*[％%]",
    re.DOTALL,
)
RE_TEISHU = re.compile(
    r"定修プラント[：:]\s*前月\s*([^→]+?)→\s*当月\s*([^←]+?)←\s*前年同月\s*([^\n]+)",
)
RE_ETHYLENE_VOL = re.compile(
    r"エチレン\s+([0-9,]+)\s*トン.*?前\s*月\s*比\s*([▲＋\+\-]?\s*[\d.]+)\s*[％%].*?前年同月比\s*([▲＋\+\-]?\s*[\d.]+)\s*[％%]",
    re.DOTALL,
)


def fetch_memo_index() -> list[str]:
    """Return list of YYYYMM strings for available memo PDFs."""
    r = requests.get(MEMO_INDEX_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    html = r.text
    stamps = re.findall(r'/memo/(\d{6})_memo\.pdf', html)
    return sorted(set(stamps))


def fetch_pdf_text(stamp: str) -> str | None:
    url = MEMO_PDF_BASE.format(stamp=stamp)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return None
    except requests.RequestException:
        return None
    try:
        doc = fitz.open(stream=r.content, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        # NFKC normalize: 全角数字/記号 → 半角 (６８．８% → 68.8%)
        text = unicodedata.normalize("NFKC", text)
        return text
    except Exception as e:
        print(f"  PDF parse failed for {stamp}: {e}")
        return None


def parse_metric(text: str) -> dict:
    out = {
        "util_prev_month": None,
        "util_current": None,
        "util_prev_year_same_month": None,
        "teishu_prev_month": None,
        "teishu_current": None,
        "teishu_prev_year_same_month": None,
        "ethylene_kton": None,
        "ethylene_mom_pct": None,
        "ethylene_yoy_pct": None,
    }
    m = RE_UTIL_TRIPLE.search(text)
    if m:
        out["util_prev_month"] = float(m.group(1))
        out["util_current"] = float(m.group(2))
        out["util_prev_year_same_month"] = float(m.group(3))
    m2 = RE_TEISHU.search(text)
    if m2:
        out["teishu_prev_month"] = m2.group(1).strip()
        out["teishu_current"] = m2.group(2).strip()
        out["teishu_prev_year_same_month"] = m2.group(3).strip()
    m3 = RE_ETHYLENE_VOL.search(text)
    if m3:
        try:
            out["ethylene_kton"] = float(m3.group(1).replace(",", "")) / 1000.0
            mom = m3.group(2).replace("▲", "-").replace("＋", "+").replace(" ", "")
            yoy = m3.group(3).replace("▲", "-").replace("＋", "+").replace(" ", "")
            out["ethylene_mom_pct"] = float(mom)
            out["ethylene_yoy_pct"] = float(yoy)
        except (ValueError, AttributeError):
            pass
    return out


def main(limit: int | None = None):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()

    stamps = fetch_memo_index()
    if limit:
        stamps = stamps[-limit:]
    print(f"Found {len(stamps)} memo PDFs ({stamps[0]} → {stamps[-1]})")

    rows = []
    for i, stamp in enumerate(stamps, 1):
        if i % 10 == 0 or i == 1:
            print(f"  [{i}/{len(stamps)}] {stamp}", flush=True)
        text = fetch_pdf_text(stamp)
        if not text:
            continue
        metrics = parse_metric(text)
        if metrics["util_current"] is None:
            # Some early memos may not have utilization stat
            continue
        rows.append({
            "year": int(stamp[:4]),
            "month": int(stamp[4:6]),
            "period": f"{stamp[:4]}-{stamp[4:6]}",
            **metrics,
            "memo_url": MEMO_PDF_BASE.format(stamp=stamp),
            "_fetched_at": fetched_at,
        })
        time.sleep(REQUEST_SLEEP)

    if not rows:
        print("No utilization data parsed.")
        return

    df = pd.DataFrame(rows).sort_values("period")
    print(f"\nParsed {len(df)} months with utilization data")
    print(f"\nLatest 6 rows:")
    print(df.tail(6)[["period", "util_current", "util_prev_month", "util_prev_year_same_month", "ethylene_kton"]].to_string(index=False))

    stamp_today = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"jpca_utilization_{stamp_today}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(df)} rows → {out_path}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Limit to most recent N months")
    args = ap.parse_args()
    main(limit=args.limit)
