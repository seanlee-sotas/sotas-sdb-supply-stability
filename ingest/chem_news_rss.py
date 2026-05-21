"""Axis 6 — 化学業界ニュース ingest via Google News RSS.

化学工業日報はサブスク主体で headlines まで届かない。代替で Google News RSS が
日次更新で「火災/操業停止/供給停止/FM/リコール」等の供給途絶ニュースを集約する。

複数クエリ:
- 火災 / 爆発 系 (plant accidents)
- 操業停止 / 生産停止 系 (production halt)
- 供給停止 / FM / Force Majeure 系
- リコール 系

Each query becomes a separate RSS feed. We dedupe by URL across queries.
"""
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "chem_news"
GNEWS_BASE = "https://news.google.com/rss/search"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
HEADERS = {"User-Agent": UA}

# Query list — Japanese chemical supply disruption keywords
QUERIES = [
    {"name": "plant_accident", "q": '("操業停止" OR "火災" OR "爆発" OR "事故") 化学', "lang": "ja"},
    {"name": "supply_halt", "q": '("供給停止" OR "出荷停止" OR "Force Majeure" OR "フォースマジュール") 化学', "lang": "ja"},
    {"name": "recall", "q": '"リコール" 化学 OR 樹脂 OR ゴム', "lang": "ja"},
    {"name": "naphtha", "q": '"ナフサ" (停止 OR 不足 OR 供給) ', "lang": "ja"},
    {"name": "ethylene_cracker", "q": '"エチレンクラッカー" OR "ナフサクラッカー"', "lang": "ja"},
    # English / global
    {"name": "global_chem_disruption", "q": '("force majeure" OR "plant shutdown" OR "explosion") chemical', "lang": "en"},
]

REQUEST_SLEEP = 1.0


def fetch_rss(query: dict) -> list[dict]:
    """Run a Google News RSS search, return parsed items."""
    if query["lang"] == "ja":
        url = f"{GNEWS_BASE}?q={quote_plus(query['q'])}&hl=ja&gl=JP&ceid=JP:ja"
    else:
        url = f"{GNEWS_BASE}?q={quote_plus(query['q'])}&hl=en-US&gl=US&ceid=US:en"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return []
    except requests.RequestException as e:
        print(f"  HTTP error: {e}")
        return []
    items = []
    try:
        root = ET.fromstring(r.content)
        channel = root.find("channel")
        if channel is None:
            return []
        for item in channel.findall("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub = item.findtext("pubDate", "").strip()
            source_el = item.find("source")
            source = source_el.text.strip() if source_el is not None and source_el.text else ""
            source_url = source_el.get("url", "") if source_el is not None else ""
            desc = item.findtext("description", "").strip()
            items.append({
                "title": title,
                "link": link,
                "pub_date": pub,
                "source_name": source,
                "source_url": source_url,
                "description_html": desc[:500],
            })
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
        return []
    return items


def normalize_pubdate(s: str) -> str:
    """RFC2822 → ISO 8601, fallback to original."""
    if not s:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return s


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()

    all_items: list[dict] = []
    seen_links: set[str] = set()

    for query in QUERIES:
        print(f"=== {query['name']}: {query['q'][:50]}... ===")
        items = fetch_rss(query)
        print(f"  fetched {len(items)} items")
        new_count = 0
        for it in items:
            link = it["link"]
            if link in seen_links:
                continue
            seen_links.add(link)
            it["query_name"] = query["name"]
            it["query_q"] = query["q"]
            it["query_lang"] = query["lang"]
            it["pub_date_iso"] = normalize_pubdate(it["pub_date"])
            it["_fetched_at"] = fetched_at
            all_items.append(it)
            new_count += 1
        print(f"  +{new_count} new (after dedup)")
        time.sleep(REQUEST_SLEEP)

    if not all_items:
        print("\nNo news collected.")
        return

    df = pd.DataFrame(all_items)
    # Sort by publish date desc
    df = df.sort_values("pub_date_iso", ascending=False, na_position="last")

    stamp = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"chem_news_{stamp}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(df)} news items → {out_path}")
    print(f"\nクエリ別 件数:")
    print(df.groupby("query_name").size().to_string())
    print(f"\nソース別 Top 10:")
    print(df.groupby("source_name").size().sort_values(ascending=False).head(10).to_string())
    print(f"\nサンプル直近10件:")
    for _, r in df.head(10).iterrows():
        print(f"  [{(r['pub_date_iso'] or '?')[:10]}] {r['title'][:90]}")


if __name__ == "__main__":
    main()
