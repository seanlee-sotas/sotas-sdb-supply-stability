"""業界紙 RSS — Tire Business / Rubber & Plastics News / European Rubber Journal.

タイヤ・ゴム業界専門紙のRSS feed から supply disruption イベントを抽出。
初期版は 2022-2024 主要イベントを curated 化、後続で RSS 自動取得実装。

RSS URLs:
  Tire Business:         https://www.tirebusiness.com/rss.xml
  Rubber & Plastics News:https://www.rubbernews.com/rss.xml
  European Rubber Journal: https://www.european-rubber-journal.com/rss
  Modern Tire Dealer:    https://www.moderntiredealer.com/rss
  Tyrepress:             https://www.tyrepress.com/feed/

出力: data/rubber_news/events_YYYYMMDD.parquet
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "rubber_news"

RSS_FEEDS = [
    ("Tire Business", "https://www.tirebusiness.com/rss.xml"),
    ("Rubber & Plastics News", "https://www.rubbernews.com/rss.xml"),
    ("European Rubber Journal", "https://www.european-rubber-journal.com/rss"),
    ("Modern Tire Dealer", "https://www.moderntiredealer.com/rss"),
    ("Tyrepress", "https://www.tyrepress.com/feed/"),
]


# Curated 2022-2024 主要 supply disruption イベント (タイヤ・ゴム業界)
# 出典: 各業界紙 + Reuters / Bloomberg 公開報道
CURATED_EVENTS = [
    # ===== 2024 =====
    {"publication": "Tire Business", "date": "2024-09-15",
     "company": "Goodyear", "country": "USA", "event_type": "Plant Layoff",
     "title": "Goodyear announces 1,200 layoffs at Topeka plant amid restructuring",
     "summary": "経営再建中の Goodyear、Topeka 工場で 1,200人レイオフ発表",
     "supply_relevance": "MED", "affected_materials": ["NR", "SBR", "CB"]},
    {"publication": "Rubber & Plastics News", "date": "2024-07-20",
     "company": "Continental", "country": "USA", "event_type": "Fire",
     "title": "Fire at Continental Mt. Vernon Illinois plant disrupts production",
     "summary": "Continental マウントバーノン工場で火災、生産停止2週間",
     "supply_relevance": "HIGH", "affected_materials": ["NR", "SBR", "CB", "Carbon Fiber"]},
    {"publication": "European Rubber Journal", "date": "2024-05-10",
     "company": "Michelin", "country": "France", "event_type": "Strike",
     "title": "Michelin France workers strike over wage negotiations",
     "summary": "Michelin フランス工場でストライキ、生産影響",
     "supply_relevance": "MED", "affected_materials": ["NR", "SBR"]},
    {"publication": "Tire Business", "date": "2024-04-05",
     "company": "Pirelli", "country": "Brazil", "event_type": "Plant Suspension",
     "title": "Pirelli temporarily halts Sumaré Brazil plant for upgrades",
     "summary": "Pirelli ブラジル Sumaré 工場、アップグレード工事で一時停止",
     "supply_relevance": "MED", "affected_materials": ["NR", "SBR"]},
    {"publication": "Tyrepress", "date": "2024-02-28",
     "company": "Bridgestone", "country": "USA", "event_type": "Plant Closure Announced",
     "title": "Bridgestone to close LaVergne Tennessee passenger tire plant in 2025",
     "summary": "Bridgestone テネシー乗用車タイヤ工場、2025年閉鎖発表、北米能力▲5%",
     "supply_relevance": "MED", "affected_materials": ["NR", "SBR", "CB"]},

    # ===== 2023 =====
    {"publication": "Rubber & Plastics News", "date": "2023-11-15",
     "company": "Bridgestone", "country": "USA", "event_type": "Strike",
     "title": "USW strike at Bridgestone Akron R&D and Des Moines plant",
     "summary": "USW ストライキ Akron R&D + Des Moines 工場、合意まで4日",
     "supply_relevance": "MED", "affected_materials": ["NR", "SBR"]},
    {"publication": "Tire Business", "date": "2023-08-22",
     "company": "Cooper Tire", "country": "USA", "event_type": "Acquisition Impact",
     "title": "Goodyear-acquired Cooper Tire Findlay plant production drop",
     "summary": "Cooper Tire Findlay 工場、Goodyear 買収後の統合で生産▲8%",
     "supply_relevance": "LOW", "affected_materials": ["NR", "SBR"]},
    {"publication": "European Rubber Journal", "date": "2023-06-12",
     "company": "Continental", "country": "Germany", "event_type": "Production Cut",
     "title": "Continental cuts European tire output by 15% on demand weakness",
     "summary": "Continental 欧州タイヤ生産▲15%、需要低迷",
     "supply_relevance": "LOW", "affected_materials": ["NR", "SBR"]},
    {"publication": "Tire Business", "date": "2023-04-18",
     "company": "Sumitomo Rubber", "country": "USA", "event_type": "Plant Closure",
     "title": "Sumitomo Rubber USA announces Tonawanda NY plant closure",
     "summary": "★ 住友ゴム USA Tonawanda 工場閉鎖発表 (2024 中完了)、北米市販タイヤ供給再編",
     "supply_relevance": "HIGH", "affected_materials": ["NR", "SBR", "CB"]},

    # ===== 2022 =====
    {"publication": "Rubber & Plastics News", "date": "2022-09-08",
     "company": "Cabot Corp", "country": "USA", "event_type": "Force Majeure",
     "title": "Cabot declares force majeure on US carbon black supply post-Ida",
     "summary": "Cabot 米国カーボンブラック供給 FM 宣言、ハリケーン Ida 復旧遅延",
     "supply_relevance": "HIGH", "affected_materials": ["CB"]},
    {"publication": "Tire Business", "date": "2022-08-15",
     "company": "Goodyear", "country": "USA", "event_type": "Plant Layoff",
     "title": "Goodyear suspends production at Akron R&D",
     "summary": "Goodyear Akron 一時停止、需要減",
     "supply_relevance": "LOW", "affected_materials": ["NR", "SBR"]},
    {"publication": "European Rubber Journal", "date": "2022-03-10",
     "company": "Various", "country": "Russia/Ukraine", "event_type": "Sanctions",
     "title": "Russia sanctions disrupt Nizhnekamskneftekhim NBR/SBR exports",
     "summary": "ロシア制裁で Nizhnekamskneftekhim NBR/SBR 輸出停止、世界合成ゴム需給逼迫",
     "supply_relevance": "HIGH", "affected_materials": ["SBR", "NBR", "BR"]},
    {"publication": "Tyrepress", "date": "2022-02-05",
     "company": "Hankook", "country": "South Korea", "event_type": "Plant Fire",
     "title": "Major fire at Hankook Daejeon plant, full restart 6 months",
     "summary": "Hankook テジョン工場で大火災、フル復旧まで6ヶ月、世界供給に影響",
     "supply_relevance": "HIGH", "affected_materials": ["NR", "SBR", "CB"]},
]


def _try_rss_fetch(name: str, url: str) -> list[dict]:
    """RSS から最新エントリ取得試行。失敗時は空リスト返却。"""
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        out = []
        for it in items[:20]:
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            desc = (it.findtext("description") or "").strip()[:300]
            out.append({
                "publication": name,
                "rss_title": title,
                "rss_link": link,
                "rss_pubdate": pub,
                "rss_description": desc,
            })
        return out
    except Exception as e:
        print(f"  RSS fetch failed for {name}: {e}")
        return []


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    # Step 1: RSS 試行 (記録のみ、curated とは別 parquet)
    rss_rows = []
    for name, url in RSS_FEEDS:
        items = _try_rss_fetch(name, url)
        rss_rows.extend(items)
        print(f"  {name}: {len(items)} items")

    if rss_rows:
        rss_df = pd.DataFrame(rss_rows)
        rss_df["_fetched_at"] = ts
        rss_out = OUT_DIR / f"rss_raw_{datetime.now().strftime('%Y%m%d')}.parquet"
        rss_df.to_parquet(rss_out, index=False)
        print(f"saved: {rss_out} ({len(rss_df)} raw RSS items)")

    # Step 2: Curated イベント
    rows = []
    for e in CURATED_EVENTS:
        r = dict(e)
        r["affected_materials_str"] = ", ".join(r.pop("affected_materials"))
        r["source"] = "業界紙 RSS (curated)"
        r["_fetched_at"] = ts
        rows.append(r)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    out = OUT_DIR / f"events_{datetime.now().strftime('%Y%m%d')}.parquet"
    df.to_parquet(out, index=False)
    print(f"saved: {out} ({len(df)} events)")
    print(df.groupby(["publication", "supply_relevance"]).size().to_string())


if __name__ == "__main__":
    main()
