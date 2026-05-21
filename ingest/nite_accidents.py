"""Axis 6 — NITE 化学物質事故DB ingest.

NITE (製品評価技術基盤機構) publishes chemical-accident registry data covering
fires, leaks, explosions at JP chemical facilities since 1979. The public-facing
search is at https://www.nite.go.jp/chem/jiken/jiken_kensaku.html but does not
expose a direct JSON API. Historical compiled data files are released annually
as Excel (XLSX) workbooks under the 化学物質安全管理 portal.

Strategy:
1. Try the official NITE chemical accident open-data XLSX
   (https://www.nite.go.jp/chem/jiken/...)
2. Fall back to scraping the search HTML.

Output: NITE_accidents_<stamp>.parquet keyed on (date, facility, substance).
"""
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "nite"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja"}

# NITE no longer exposes a search API or open-data XLSX for accident incidents.
# What is available: 注意喚起 press release index — each entry is a documented
# chemical-accident notification (factory fire, leak, explosion, recall trigger).
PRESS_INDEX = "https://www.nite.go.jp/jiko/chuikanki/press/index.html"
SAIGAI_PAGE = "https://www.nite.go.jp/jiko/chuikanki/saigai.html"


def fetch_html(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 200 and len(r.text) > 500:
            r.encoding = "utf-8"
            return r.text
    except requests.RequestException:
        pass
    return None


def discover_press_releases(html: str) -> list[dict]:
    """Find press-release links.

    NITE year-folder pages list each release as:
      <a href="/jiko/chuikanki/press/YYYYfy/prsYYMMDD.html">タイトル</a>
    Date is encoded in the filename (prsYYMMDD).
    """
    out = []
    pat = re.compile(
        r'href="(/jiko/chuikanki/press/\d{4}fy/prs(\d{6})\.html)"[^>]*>([^<]+)</a>',
        re.IGNORECASE,
    )
    for m in pat.finditer(html):
        path, yymmdd, title = m.group(1), m.group(2), unescape(m.group(3)).strip()
        # Convert YYMMDD → 20YY-MM-DD
        try:
            iso = f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"
        except IndexError:
            iso = ""
        out.append({
            "date": iso,
            "title": title,
            "url": "https://www.nite.go.jp" + path,
        })

    # Also catch direct PDF references on /data/
    pdf_pat = re.compile(r'href="(/data/\d+\.pdf)"[^>]*>([^<]+)</a>', re.IGNORECASE)
    for m in pdf_pat.finditer(html):
        out.append({
            "date": "",
            "title": unescape(m.group(2)).strip(),
            "url": "https://www.nite.go.jp" + m.group(1),
        })

    return out


def discover_xlsx_links(html: str) -> list[str]:
    """Find XLSX/CSV links to compiled accident summary data."""
    pat = re.compile(r'href="([^"]+\.(?:xlsx|csv))"', re.IGNORECASE)
    out = []
    for m in pat.finditer(html):
        href = m.group(1)
        if not href.startswith("http"):
            href = "https://www.nite.go.jp" + (href if href.startswith("/") else "/chem/jiken/" + href)
        out.append(href)
    return list(dict.fromkeys(out))  # dedupe preserving order


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()

    pages_html = {}
    for url in (PRESS_INDEX, SAIGAI_PAGE):
        html = fetch_html(url)
        if html:
            pages_html[url] = html
            print(f"OK {url} ({len(html):,} bytes)")
        else:
            print(f"FAIL {url}")

    # Drill into year-folder pages linked from PRESS_INDEX
    year_pat = re.compile(r'href="(/jiko/chuikanki/press/20\d{2}fy/index\.html)"')
    seen_year_pages: set[str] = set()
    if PRESS_INDEX in pages_html:
        for m in year_pat.finditer(pages_html[PRESS_INDEX]):
            yurl = "https://www.nite.go.jp" + m.group(1)
            if yurl in seen_year_pages:
                continue
            seen_year_pages.add(yurl)
            yhtml = fetch_html(yurl)
            if yhtml:
                pages_html[yurl] = yhtml
                print(f"  + {yurl}")
            time.sleep(0.3)

    if not pages_html:
        print("ERROR: all NITE pages unreachable. Output skipped.")
        return

    rows: list[dict] = []
    for url, html in pages_html.items():
        for entry in discover_press_releases(html):
            rows.append({
                **entry,
                "source_page": url,
                "_fetched_at": fetched_at,
            })
    # Dedupe by URL
    seen_urls = set()
    deduped = []
    for r in rows:
        if r["url"] in seen_urls:
            continue
        seen_urls.add(r["url"])
        deduped.append(r)
    rows = deduped
    print(f"\nDiscovered {len(rows)} unique press-release / accident notification links")

    df = pd.DataFrame(rows)
    stamp = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"nite_accidents_{stamp}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"Wrote {len(df)} rows → {out_path}")
    if len(df):
        print("\nSample 10:")
        for _, r in df.head(10).iterrows():
            print(f"  [{r['date']}] {r['title'][:100]}")


if __name__ == "__main__":
    main()
