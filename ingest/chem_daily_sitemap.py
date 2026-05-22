"""Axis 1 短期要因 — 化学工業日報 sitemap ingest.

Google News RSS では取りこぼす日本国内の化学業界専門紙ヘッドラインを
sitemap 経由で取得する (RSS は WP 上で disabled)。

戦略:
  1. /sitemap_index.xml → post-sitemap{,2,3...}.xml を巡回
  2. lastmod が直近 N 日のエントリのみ集める
  3. 既存 parquet に無い URL のみ HTML fetch して og:title / og:description /
     article:published_time を抽出
  4. parquet を差分上書き (URL key)

site は subscription だが <head> の meta tag は誰でも見られる (見出し +
冒頭 70字)。軸1 短期要因スコアの「業界ニュース密度」シグナルに使う。

robots.txt: Mozilla UA は Disallow なし。0.5秒 sleep でマナー守る。
"""
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "chem_daily"
SITEMAP_INDEX = "https://chemicaldaily.com/sitemap_index.xml"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"}

REQUEST_SLEEP = 0.5
WINDOW_DAYS = 90  # 軸1 短期要因と合わせる
MAX_NEW_FETCH = 600  # 初回でも 600 件まで (1リクエスト=~0.5s なら 5分)

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

RE_OG_TITLE = re.compile(r'property=["\']og:title["\']\s+content=["\']([^"\']+)["\']')
RE_OG_DESC = re.compile(r'property=["\']og:description["\']\s+content=["\']([^"\']+)["\']')
RE_ARTICLE_PUB = re.compile(r'article:published_time["\']\s+content=["\']([^"\']+)["\']')
RE_ARCHIVE_ID = re.compile(r'/archives/(\d+)')


def fetch_sitemap_index() -> list[str]:
    """Return list of post-sitemap*.xml URLs ordered newest-first by lastmod."""
    r = requests.get(SITEMAP_INDEX, headers=HEADERS, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    sitemaps = []
    for sm in root.findall("sm:sitemap", NS):
        loc = sm.findtext("sm:loc", default="", namespaces=NS).strip()
        lastmod = sm.findtext("sm:lastmod", default="", namespaces=NS).strip()
        if "post-sitemap" in loc:
            sitemaps.append((loc, lastmod))
    # sort by lastmod desc
    sitemaps.sort(key=lambda x: x[1], reverse=True)
    return [loc for loc, _ in sitemaps]


def parse_sitemap(url: str) -> list[dict]:
    """Return [{url, lastmod}] entries from a post-sitemap*.xml."""
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for u in root.findall("sm:url", NS):
        loc = u.findtext("sm:loc", default="", namespaces=NS).strip()
        lastmod = u.findtext("sm:lastmod", default="", namespaces=NS).strip()
        if loc and "/archives/" in loc:
            out.append({"url": loc, "lastmod": lastmod})
    return out


def fetch_article_meta(url: str) -> dict | None:
    """Fetch article HTML and extract og:title / og:description / pub time."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return None
    except requests.RequestException as e:
        print(f"    HTTP error on {url}: {e}")
        return None
    html = r.text
    title_m = RE_OG_TITLE.search(html)
    desc_m = RE_OG_DESC.search(html)
    pub_m = RE_ARTICLE_PUB.search(html)
    id_m = RE_ARCHIVE_ID.search(url)
    return {
        "url": url,
        "article_id": id_m.group(1) if id_m else "",
        "title": title_m.group(1) if title_m else "",
        "summary": desc_m.group(1) if desc_m else "",
        "pub_date_iso": pub_m.group(1) if pub_m else "",
    }


def latest_existing_parquet() -> Path | None:
    files = sorted(OUT_DIR.glob("chem_daily_*.parquet"))
    return files[-1] if files else None


def main(window_days: int = WINDOW_DAYS, max_new: int = MAX_NEW_FETCH):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    fetched_at = datetime.now(timezone.utc).isoformat()

    # 1. sitemap index → individual post-sitemap*.xml
    print(f"Fetching sitemap index → {SITEMAP_INDEX}")
    sitemap_urls = fetch_sitemap_index()
    print(f"  found {len(sitemap_urls)} post-sitemaps")

    # 2. collect URLs within window
    candidates: list[dict] = []
    for sm_url in sitemap_urls:
        print(f"  parsing {sm_url}")
        entries = parse_sitemap(sm_url)
        in_window = [e for e in entries if e["lastmod"] >= cutoff]
        candidates.extend(in_window)
        # 古いsitemapに到達したら break
        if entries and entries[-1]["lastmod"] < cutoff and not in_window:
            print(f"    out of window → stop")
            break
        time.sleep(REQUEST_SLEEP)
    print(f"\n  {len(candidates)} URLs within last {window_days}d window")

    # 3. dedupe vs existing parquet
    existing_urls: set[str] = set()
    existing_df = pd.DataFrame()
    prev = latest_existing_parquet()
    if prev is not None:
        existing_df = pd.read_parquet(prev)
        existing_urls = set(existing_df["url"].astype(str).tolist())
        print(f"  prev parquet: {prev.name} ({len(existing_df)} rows)")

    new_urls = [c for c in candidates if c["url"] not in existing_urls]
    print(f"  {len(new_urls)} new URLs to fetch (cap {max_new})")
    new_urls = new_urls[:max_new]

    # 4. fetch metadata for each new URL
    new_rows = []
    for i, c in enumerate(new_urls, 1):
        if i % 20 == 0 or i == 1:
            print(f"    [{i}/{len(new_urls)}] {c['url']}", flush=True)
        meta = fetch_article_meta(c["url"])
        if meta:
            meta["sitemap_lastmod"] = c["lastmod"]
            meta["_fetched_at"] = fetched_at
            new_rows.append(meta)
        time.sleep(REQUEST_SLEEP)

    if not new_rows and existing_df.empty:
        print("\nNo articles parsed.")
        return

    # 5. merge with existing, drop rows older than window
    df_new = pd.DataFrame(new_rows)
    if not existing_df.empty:
        merged = pd.concat([existing_df, df_new], ignore_index=True)
    else:
        merged = df_new
    merged = merged.drop_duplicates(subset=["url"], keep="last")
    # drop rows whose pub_date_iso (or sitemap_lastmod fallback) is older than cutoff
    def _is_recent(row) -> bool:
        d = str(row.get("pub_date_iso") or row.get("sitemap_lastmod") or "")
        return d >= cutoff
    merged = merged[merged.apply(_is_recent, axis=1)]
    merged = merged.sort_values("pub_date_iso", ascending=False, na_position="last")

    stamp = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"chem_daily_{stamp}.parquet"
    merged.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(merged)} articles → {out_path}")
    print(f"  (+{len(new_rows)} new this run)")
    print(f"\nLatest 10:")
    for _, r in merged.head(10).iterrows():
        d = (r.get("pub_date_iso") or r.get("sitemap_lastmod") or "?")[:10]
        print(f"  [{d}] {(r.get('title') or '?')[:80]}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--max-new", type=int, default=MAX_NEW_FETCH)
    args = ap.parse_args()
    main(window_days=args.days, max_new=args.max_new)
