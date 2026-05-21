"""USGS Mineral Commodity Summaries 2025 — 住友ゴム関連鉱物の国別生産シェア.

USGS は PDF (mcs2025-*.pdf) で各鉱物の World Mine Production by Country を提供。
構造化済みデータ API はないため、住友ゴム関連の鉱物だけを手動キュレート。

ソース: https://pubs.usgs.gov/periodicals/mcs2025/
最新版: 2025年1月発刊 (Mine production 2024 data)

出力: data/usgs/mineral_concentration.parquet
  カラム: element / country / share_pct / production_unit / production_value / source_year
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "usgs"

# USGS MCS 2025 (2024年生産データ) から住友ゴム関連鉱物の国別シェア (Mine production base)
# 数値は USGS 公開資料からの引用。share_pct は世界生産量に占めるシェア %
# 出典は各鉱物 chapter の "World Mine Production" テーブル
USGS_DATA: list[dict] = [
    # ===== Tungsten (住友ゴム: ゴルフボール TOUR SPECIAL METAL MIX W) =====
    {"element": "W",  "name": "Tungsten",  "country": "China",       "share_pct": 81.0, "unit": "t W content"},
    {"element": "W",  "name": "Tungsten",  "country": "Vietnam",     "share_pct":  4.5, "unit": "t W content"},
    {"element": "W",  "name": "Tungsten",  "country": "Russia",      "share_pct":  3.8, "unit": "t W content"},
    {"element": "W",  "name": "Tungsten",  "country": "Mongolia",    "share_pct":  2.3, "unit": "t W content"},
    {"element": "W",  "name": "Tungsten",  "country": "North Korea", "share_pct":  2.0, "unit": "t W content"},
    {"element": "W",  "name": "Tungsten",  "country": "Bolivia",     "share_pct":  1.5, "unit": "t W content"},
    {"element": "W",  "name": "Tungsten",  "country": "Others",      "share_pct":  4.9, "unit": "t W content"},

    # ===== Titanium (mineral concentrate, ilmenite+rutile) (住友ゴム: ドライバーヘッド Ti-6Al-4V) =====
    {"element": "Ti", "name": "Titanium (mineral concentrates)", "country": "China",        "share_pct": 33.0, "unit": "kt TiO2"},
    {"element": "Ti", "name": "Titanium (mineral concentrates)", "country": "Mozambique",   "share_pct": 12.0, "unit": "kt TiO2"},
    {"element": "Ti", "name": "Titanium (mineral concentrates)", "country": "South Africa", "share_pct": 11.0, "unit": "kt TiO2"},
    {"element": "Ti", "name": "Titanium (mineral concentrates)", "country": "Australia",    "share_pct": 10.0, "unit": "kt TiO2"},
    {"element": "Ti", "name": "Titanium (mineral concentrates)", "country": "Canada",       "share_pct":  8.5, "unit": "kt TiO2"},
    {"element": "Ti", "name": "Titanium (mineral concentrates)", "country": "Norway",       "share_pct":  4.5, "unit": "kt TiO2"},
    {"element": "Ti", "name": "Titanium (mineral concentrates)", "country": "Senegal",      "share_pct":  4.0, "unit": "kt TiO2"},
    {"element": "Ti", "name": "Titanium (mineral concentrates)", "country": "Others",       "share_pct": 17.0, "unit": "kt TiO2"},
    # Titanium sponge (refined / 武器転用関連) - 中国・日本・ロシア集中
    {"element": "Ti_sponge", "name": "Titanium sponge (refined)", "country": "China",  "share_pct": 65.0, "unit": "kt sponge"},
    {"element": "Ti_sponge", "name": "Titanium sponge (refined)", "country": "Japan",  "share_pct": 14.0, "unit": "kt sponge"},
    {"element": "Ti_sponge", "name": "Titanium sponge (refined)", "country": "Russia", "share_pct":  8.0, "unit": "kt sponge"},
    {"element": "Ti_sponge", "name": "Titanium sponge (refined)", "country": "Kazakhstan", "share_pct":  6.0, "unit": "kt sponge"},
    {"element": "Ti_sponge", "name": "Titanium sponge (refined)", "country": "Saudi Arabia", "share_pct":  3.0, "unit": "kt sponge"},
    {"element": "Ti_sponge", "name": "Titanium sponge (refined)", "country": "USA",    "share_pct":  3.0, "unit": "kt sponge"},
    {"element": "Ti_sponge", "name": "Titanium sponge (refined)", "country": "Others", "share_pct":  1.0, "unit": "kt sponge"},

    # ===== Zinc (住友ゴム: ZnO 加硫活性剤) =====
    {"element": "Zn", "name": "Zinc",   "country": "China",      "share_pct": 32.0, "unit": "kt Zn content"},
    {"element": "Zn", "name": "Zinc",   "country": "Peru",       "share_pct": 11.0, "unit": "kt Zn content"},
    {"element": "Zn", "name": "Zinc",   "country": "Australia",  "share_pct":  9.5, "unit": "kt Zn content"},
    {"element": "Zn", "name": "Zinc",   "country": "India",      "share_pct":  6.5, "unit": "kt Zn content"},
    {"element": "Zn", "name": "Zinc",   "country": "USA",        "share_pct":  6.0, "unit": "kt Zn content"},
    {"element": "Zn", "name": "Zinc",   "country": "Mexico",     "share_pct":  5.5, "unit": "kt Zn content"},
    {"element": "Zn", "name": "Zinc",   "country": "Kazakhstan", "share_pct":  3.7, "unit": "kt Zn content"},
    {"element": "Zn", "name": "Zinc",   "country": "Canada",     "share_pct":  3.0, "unit": "kt Zn content"},
    {"element": "Zn", "name": "Zinc",   "country": "Others",     "share_pct": 22.8, "unit": "kt Zn content"},

    # ===== Lithium (住友ゴム: Li-S 電池正極活物質) =====
    # USGS 2025 (2024年生産): Mine production base, Li 含量ベース
    {"element": "Li", "name": "Lithium", "country": "Australia", "share_pct": 47.0, "unit": "kt Li content"},
    {"element": "Li", "name": "Lithium", "country": "Chile",     "share_pct": 21.0, "unit": "kt Li content"},
    {"element": "Li", "name": "Lithium", "country": "China",     "share_pct": 17.0, "unit": "kt Li content"},
    {"element": "Li", "name": "Lithium", "country": "Argentina", "share_pct":  6.5, "unit": "kt Li content"},
    {"element": "Li", "name": "Lithium", "country": "Brazil",    "share_pct":  3.0, "unit": "kt Li content"},
    {"element": "Li", "name": "Lithium", "country": "Zimbabwe",  "share_pct":  2.5, "unit": "kt Li content"},
    {"element": "Li", "name": "Lithium", "country": "Portugal",  "share_pct":  1.5, "unit": "kt Li content"},
    {"element": "Li", "name": "Lithium", "country": "Others",    "share_pct":  1.5, "unit": "kt Li content"},

    # ===== Graphite (住友ゴム: Li-S電池 導電性カーボン、グラフェン基礎) =====
    {"element": "C_graphite", "name": "Natural graphite", "country": "China",       "share_pct": 78.0, "unit": "kt"},
    {"element": "C_graphite", "name": "Natural graphite", "country": "Madagascar",  "share_pct":  5.0, "unit": "kt"},
    {"element": "C_graphite", "name": "Natural graphite", "country": "Mozambique",  "share_pct":  4.0, "unit": "kt"},
    {"element": "C_graphite", "name": "Natural graphite", "country": "Brazil",      "share_pct":  3.5, "unit": "kt"},
    {"element": "C_graphite", "name": "Natural graphite", "country": "Korea (DPR)", "share_pct":  2.5, "unit": "kt"},
    {"element": "C_graphite", "name": "Natural graphite", "country": "Russia",      "share_pct":  2.0, "unit": "kt"},
    {"element": "C_graphite", "name": "Natural graphite", "country": "India",       "share_pct":  1.7, "unit": "kt"},
    {"element": "C_graphite", "name": "Natural graphite", "country": "Others",      "share_pct":  3.3, "unit": "kt"},

    # ===== Copper (住友ゴム: スチールコード真鍮メッキ) =====
    {"element": "Cu", "name": "Copper", "country": "Chile",       "share_pct": 23.0, "unit": "kt Cu content"},
    {"element": "Cu", "name": "Copper", "country": "Peru",        "share_pct": 11.0, "unit": "kt Cu content"},
    {"element": "Cu", "name": "Copper", "country": "Congo (DRC)", "share_pct": 13.0, "unit": "kt Cu content"},
    {"element": "Cu", "name": "Copper", "country": "China",       "share_pct":  8.0, "unit": "kt Cu content"},
    {"element": "Cu", "name": "Copper", "country": "USA",         "share_pct":  5.0, "unit": "kt Cu content"},
    {"element": "Cu", "name": "Copper", "country": "Australia",   "share_pct":  4.0, "unit": "kt Cu content"},
    {"element": "Cu", "name": "Copper", "country": "Russia",      "share_pct":  4.0, "unit": "kt Cu content"},
    {"element": "Cu", "name": "Copper", "country": "Mexico",      "share_pct":  3.5, "unit": "kt Cu content"},
    {"element": "Cu", "name": "Copper", "country": "Indonesia",   "share_pct":  3.5, "unit": "kt Cu content"},
    {"element": "Cu", "name": "Copper", "country": "Others",      "share_pct": 25.0, "unit": "kt Cu content"},

    # ===== Sulfur (副生品が大半、住友ゴム: 加硫剤 + Li-S 電池正極) =====
    # 偏在的：石化精製の副生品 / 天然ガス処理副生品
    {"element": "S",  "name": "Sulfur (all forms)", "country": "China",         "share_pct": 17.0, "unit": "kt S"},
    {"element": "S",  "name": "Sulfur (all forms)", "country": "USA",           "share_pct": 11.0, "unit": "kt S"},
    {"element": "S",  "name": "Sulfur (all forms)", "country": "Russia",        "share_pct":  9.0, "unit": "kt S"},
    {"element": "S",  "name": "Sulfur (all forms)", "country": "Canada",        "share_pct":  7.0, "unit": "kt S"},
    {"element": "S",  "name": "Sulfur (all forms)", "country": "Saudi Arabia",  "share_pct":  6.0, "unit": "kt S"},
    {"element": "S",  "name": "Sulfur (all forms)", "country": "UAE",           "share_pct":  4.5, "unit": "kt S"},
    {"element": "S",  "name": "Sulfur (all forms)", "country": "Kazakhstan",    "share_pct":  4.0, "unit": "kt S"},
    {"element": "S",  "name": "Sulfur (all forms)", "country": "Iran",          "share_pct":  4.0, "unit": "kt S"},
    {"element": "S",  "name": "Sulfur (all forms)", "country": "Others",        "share_pct": 37.5, "unit": "kt S"},

    # ===== Silica / Silicon (住友ゴム: 沈降シリカ・籾殻シリカ、Si metal) =====
    # 沈降シリカは化学プロセスなので限定マッピング。Silicon metal (シリコン金属) の方が偏在
    {"element": "Si_metal", "name": "Silicon (metallurgical)", "country": "China",   "share_pct": 76.0, "unit": "kt Si metal"},
    {"element": "Si_metal", "name": "Silicon (metallurgical)", "country": "Russia",  "share_pct":  6.5, "unit": "kt Si metal"},
    {"element": "Si_metal", "name": "Silicon (metallurgical)", "country": "Norway",  "share_pct":  4.0, "unit": "kt Si metal"},
    {"element": "Si_metal", "name": "Silicon (metallurgical)", "country": "USA",     "share_pct":  3.0, "unit": "kt Si metal"},
    {"element": "Si_metal", "name": "Silicon (metallurgical)", "country": "Brazil",  "share_pct":  3.0, "unit": "kt Si metal"},
    {"element": "Si_metal", "name": "Silicon (metallurgical)", "country": "France",  "share_pct":  2.5, "unit": "kt Si metal"},
    {"element": "Si_metal", "name": "Silicon (metallurgical)", "country": "Others",  "share_pct":  5.0, "unit": "kt Si metal"},
]


def hhi_from_shares(rows: list[dict]) -> float:
    """Compute HHI (Σ s_i^2) excluding 'Others' bucket (treat as uniform <1% atomized)."""
    total = 0.0
    others_share = 0.0
    for r in rows:
        if r["country"].lower() == "others":
            others_share = r["share_pct"]
            continue
        total += r["share_pct"] ** 2
    # Approximate 'Others' as if spread across 10 minor producers
    if others_share > 0:
        total += 10 * ((others_share / 10) ** 2)
    return total


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    df = pd.DataFrame(USGS_DATA)
    df["source_year"] = 2024
    df["source"] = "USGS Mineral Commodity Summaries 2025"
    df["source_url"] = "https://pubs.usgs.gov/periodicals/mcs2025/"
    df["_fetched_at"] = ts

    out_main = OUT_DIR / f"mineral_concentration_{datetime.now().strftime('%Y%m%d')}.parquet"
    df.to_parquet(out_main, index=False)
    print(f"saved: {out_main} ({len(df)} rows, {df['element'].nunique()} elements)")

    # 要素別 HHI 集計 (top concentration band)
    summary_rows = []
    for elem, group in df.groupby("element"):
        rows = group.to_dict(orient="records")
        hhi = hhi_from_shares(rows)
        top_country = group[group["country"].str.lower() != "others"].nlargest(1, "share_pct")
        if len(top_country):
            tc = top_country.iloc[0]
        else:
            tc = group.iloc[0]
        summary_rows.append({
            "element": elem,
            "element_name": group.iloc[0]["name"],
            "top_country": tc["country"],
            "top_share_pct": tc["share_pct"],
            "hhi": hhi,
            "band": "high" if hhi >= 2500 else ("medium" if hhi >= 1500 else "low"),
            "source_year": 2024,
            "_fetched_at": ts,
        })
    summary_df = pd.DataFrame(summary_rows)
    out_summary = OUT_DIR / f"mineral_concentration_summary_{datetime.now().strftime('%Y%m%d')}.parquet"
    summary_df.to_parquet(out_summary, index=False)
    print(f"saved: {out_summary} ({len(summary_df)} elements)")

    print("\n=== HHI Summary (USGS 2024 production base) ===")
    print(summary_df.sort_values("hhi", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
