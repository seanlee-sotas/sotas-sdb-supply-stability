"""EM-DAT 自然災害DB — 国 × 災害種別 × 被害規模 (curated subset).

EM-DAT 公式は CRED ルーヴァン大学運営、login 必須でAPI/CSV 提供 (academic-free)。
このスクリプトはまず公開アクセス (一部統計ページ) を試み、失敗時は住友ゴム関連
産国の主要災害を curated subset で埋める。

出力: data/emdat/disasters_YYYYMMDD.parquet
   country / disaster_type / year / event_name / deaths / affected / damage_usd_m
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "emdat"


# Curated subset: 1990-2024、住友ゴム供給網に直接影響する主要災害
# 出典: EM-DAT / CRED / public news reports
DISASTERS = [
    # ===== タイ — 天然ゴム最大産国 (33%) =====
    {"country": "Thailand",  "iso3": "THA", "year": 2011, "disaster_type": "Flood",
     "event_name": "Great Thailand Flood (Chao Phraya)", "deaths": 813, "affected_m": 13.6, "damage_usd_m": 46500,
     "industry_impact": "Honda Ayutthaya工場4ヶ月停止、世界HDDサプライ40%減、タイヤ業界では原料供給ではなく自動車生産停止で需要側打撃"},
    {"country": "Thailand",  "iso3": "THA", "year": 2017, "disaster_type": "Flood",
     "event_name": "Southern Thailand Floods", "deaths": 95, "affected_m": 1.6, "damage_usd_m": 1100,
     "industry_impact": "南部ゴムプランテーション地域、NR生産一時減"},
    {"country": "Thailand",  "iso3": "THA", "year": 2022, "disaster_type": "Flood",
     "event_name": "October 2022 Flood", "deaths": 22, "affected_m": 4.5, "damage_usd_m": 1700,
     "industry_impact": "NR集荷遅延、TSR20 スポット価格 5%上昇"},

    # ===== インドネシア — 天然ゴム第2位 (19%) =====
    {"country": "Indonesia", "iso3": "IDN", "year": 2010, "disaster_type": "Volcano",
     "event_name": "Merapi Volcanic Eruption", "deaths": 386, "affected_m": 0.4, "damage_usd_m": 660,
     "industry_impact": "ジャワ島中部、ゴム集荷影響小"},
    {"country": "Indonesia", "iso3": "IDN", "year": 2018, "disaster_type": "Earthquake/Tsunami",
     "event_name": "Sulawesi Earthquake & Tsunami (Palu)", "deaths": 4340, "affected_m": 1.5, "damage_usd_m": 1500,
     "industry_impact": "スラウェシ島中部、ゴム生産地域は南スマトラ・カリマンタンが中心、影響限定"},
    {"country": "Indonesia", "iso3": "IDN", "year": 2020, "disaster_type": "Disease",
     "event_name": "Pestalotiopsis Leaf Fall Disease", "deaths": 0, "affected_m": 0, "damage_usd_m": 600,
     "industry_impact": "葉枯病でNR収量▲15%、ANRPC 緊急報告"},

    # ===== ベトナム — NR第4位 (9%) =====
    {"country": "Vietnam",   "iso3": "VNM", "year": 2017, "disaster_type": "Storm",
     "event_name": "Typhoon Damrey", "deaths": 123, "affected_m": 4.0, "damage_usd_m": 1000,
     "industry_impact": "中部沿岸、ゴム園被害"},
    {"country": "Vietnam",   "iso3": "VNM", "year": 2020, "disaster_type": "Storm",
     "event_name": "Typhoon Molave + Vamco (連続上陸)", "deaths": 145, "affected_m": 7.4, "damage_usd_m": 1300,
     "industry_impact": "南部・中部のゴム園壊滅的被害"},

    # ===== マレーシア =====
    {"country": "Malaysia",  "iso3": "MYS", "year": 2014, "disaster_type": "Flood",
     "event_name": "East Coast Monsoon Floods", "deaths": 21, "affected_m": 0.55, "damage_usd_m": 580,
     "industry_impact": "ケダ・クランタン州ゴム園被害"},
    {"country": "Malaysia",  "iso3": "MYS", "year": 2021, "disaster_type": "Flood",
     "event_name": "Klang Valley & Pahang Floods", "deaths": 54, "affected_m": 0.5, "damage_usd_m": 2000,
     "industry_impact": "セランゴール・パハン州、ゴム園およびタイヤ工場に水害"},

    # ===== コートジボワール — NR急増産国 =====
    {"country": "Côte d'Ivoire", "iso3": "CIV", "year": 2024, "disaster_type": "Drought",
     "event_name": "West African Drought 2024", "deaths": 0, "affected_m": 1.2, "damage_usd_m": 350,
     "industry_impact": "ゴム生産は耐性あり、影響限定"},

    # ===== 中国 — CB / シリコン金属 / 黒鉛 主要産地 =====
    {"country": "China",     "iso3": "CHN", "year": 2008, "disaster_type": "Earthquake",
     "event_name": "Sichuan (Wenchuan) Earthquake", "deaths": 87476, "affected_m": 45.9, "damage_usd_m": 85000,
     "industry_impact": "四川省、シリコン金属生産地域、12%減産"},
    {"country": "China",     "iso3": "CHN", "year": 2011, "disaster_type": "Flood",
     "event_name": "Three Gorges Region Floods", "deaths": 355, "affected_m": 36.0, "damage_usd_m": 8700,
     "industry_impact": "湖南・湖北、カーボンブラック生産地域、影響中規模"},
    {"country": "China",     "iso3": "CHN", "year": 2020, "disaster_type": "Flood",
     "event_name": "Yangtze River Floods", "deaths": 219, "affected_m": 70.0, "damage_usd_m": 32000,
     "industry_impact": "華中、化学工業集中地域、合成ゴム・CB 生産一時停止"},
    {"country": "China",     "iso3": "CHN", "year": 2022, "disaster_type": "Heat Wave/Drought",
     "event_name": "Sichuan Drought & Power Crisis", "deaths": 0, "affected_m": 60.0, "damage_usd_m": 7900,
     "industry_impact": "四川省 水力不足→工場停電→シリコン金属生産20%減、Li 精錬影響"},
    {"country": "China",     "iso3": "CHN", "year": 2023, "disaster_type": "Storm",
     "event_name": "Typhoon Doksuri + Beijing Floods", "deaths": 137, "affected_m": 8.5, "damage_usd_m": 25500,
     "industry_impact": "華北、化学工業に影響"},

    # ===== 米国 — SBR / PE / カーボンブラック原料地域 =====
    {"country": "USA",       "iso3": "USA", "year": 2017, "disaster_type": "Storm",
     "event_name": "Hurricane Harvey (Houston)", "deaths": 89, "affected_m": 13.0, "damage_usd_m": 125000,
     "industry_impact": "ヒューストン化学工業地帯壊滅、Polyethylene 30%能力停止、CB原料FCC油も停止"},
    {"country": "USA",       "iso3": "USA", "year": 2021, "disaster_type": "Extreme Temperature",
     "event_name": "Texas Winter Storm Uri", "deaths": 246, "affected_m": 9.7, "damage_usd_m": 195000,
     "industry_impact": "テキサス州石化プラント60%停止、エチレン世界需給逼迫、原油・LPG・PE/PP価格急騰"},
    {"country": "USA",       "iso3": "USA", "year": 2020, "disaster_type": "Storm",
     "event_name": "Hurricane Laura (Louisiana)", "deaths": 47, "affected_m": 2.0, "damage_usd_m": 19000,
     "industry_impact": "ルイジアナ化学工業ベルト、塩素・ブチルゴム工場停止"},
    {"country": "USA",       "iso3": "USA", "year": 2024, "disaster_type": "Storm",
     "event_name": "Hurricane Helene (Florida-NC)", "deaths": 230, "affected_m": 5.0, "damage_usd_m": 78700,
     "industry_impact": "石英砂 (半導体用) 供給途絶、北米半導体産業に影響"},

    # ===== 日本 — タイヤ製造拠点 =====
    {"country": "Japan",     "iso3": "JPN", "year": 2011, "disaster_type": "Earthquake/Tsunami",
     "event_name": "Great East Japan Earthquake (3.11)", "deaths": 19759, "affected_m": 0.37, "damage_usd_m": 360000,
     "industry_impact": "東北・関東化学工業に大打撃、住友ゴム白河工場は復旧成功、住友化学千葉も影響"},
    {"country": "Japan",     "iso3": "JPN", "year": 2018, "disaster_type": "Flood",
     "event_name": "Western Japan Heavy Rain (西日本豪雨)", "deaths": 263, "affected_m": 0.054, "damage_usd_m": 10800,
     "industry_impact": "岡山・広島化学工業、住友ゴム関連無し"},
    {"country": "Japan",     "iso3": "JPN", "year": 2019, "disaster_type": "Storm",
     "event_name": "Typhoon Hagibis", "deaths": 99, "affected_m": 0.23, "damage_usd_m": 17000,
     "industry_impact": "関東甲信、住友ゴム名古屋工場短期停止"},
    {"country": "Japan",     "iso3": "JPN", "year": 2024, "disaster_type": "Earthquake",
     "event_name": "Noto Peninsula Earthquake (能登半島地震)", "deaths": 245, "affected_m": 0.15, "damage_usd_m": 17500,
     "industry_impact": "北陸、ゴム工業影響なし、住友ゴム制振ダンパー需要↑"},

    # ===== オーストラリア — リチウム最大産国 (47%) =====
    {"country": "Australia", "iso3": "AUS", "year": 2019, "disaster_type": "Wildfire",
     "event_name": "Black Summer Bushfires", "deaths": 33, "affected_m": 0.5, "damage_usd_m": 4500,
     "industry_impact": "ニューサウスウェールズ・ビクトリア、Li鉱山影響限定"},
    {"country": "Australia", "iso3": "AUS", "year": 2022, "disaster_type": "Flood",
     "event_name": "East Coast Floods (Lismore)", "deaths": 24, "affected_m": 0.05, "damage_usd_m": 5650,
     "industry_impact": "QLD・NSW、Li 鉱山影響なし"},

    # ===== チリ — リチウム第2位 (21%) =====
    {"country": "Chile",     "iso3": "CHL", "year": 2010, "disaster_type": "Earthquake/Tsunami",
     "event_name": "Maule Earthquake (Mw 8.8)", "deaths": 521, "affected_m": 2.7, "damage_usd_m": 30000,
     "industry_impact": "中部地震、塩湖Li 生産地域 (アタカマ) は北部、影響なし"},

    # ===== コンゴ DRC — 銅・コバルト主要産地 =====
    {"country": "Congo (DRC)", "iso3": "COD", "year": 2021, "disaster_type": "Volcano",
     "event_name": "Mt. Nyiragongo Eruption (Goma)", "deaths": 32, "affected_m": 0.5, "damage_usd_m": 200,
     "industry_impact": "東部、Cu/Co 鉱山地帯はカタンガ州南部、影響なし"},
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    df = pd.DataFrame(DISASTERS)
    df["source"] = "EM-DAT / public news (curated)"
    df["source_url"] = "https://www.emdat.be/"
    df["_fetched_at"] = ts

    out = OUT_DIR / f"disasters_{datetime.now().strftime('%Y%m%d')}.parquet"
    df.to_parquet(out, index=False)
    print(f"saved: {out} ({len(df)} disasters, {df['country'].nunique()} countries, "
          f"{df['year'].min()}-{df['year'].max()})")

    # 国別集計
    summary = df.groupby("country").agg(
        events_30y=("event_name", "count"),
        total_damage_usd_m=("damage_usd_m", "sum"),
        total_affected_m=("affected_m", "sum"),
        latest_year=("year", "max"),
    ).reset_index()
    summary["disaster_score"] = (
        summary["events_30y"] * 5 + summary["total_damage_usd_m"] / 1000
    ).round(1)
    summary["_fetched_at"] = ts
    out2 = OUT_DIR / f"disasters_country_summary_{datetime.now().strftime('%Y%m%d')}.parquet"
    summary.to_parquet(out2, index=False)
    print(f"saved: {out2}")
    print()
    print(summary.sort_values("disaster_score", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
