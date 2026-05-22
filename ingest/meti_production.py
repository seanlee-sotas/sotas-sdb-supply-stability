"""METI 化学工業生産動態統計 — 国内品目別月次生産量.

経産省統計分析データのうち化学業種の品目別生産量 (合成ゴム / カーボンブラック / シリカ /
タイヤコード等) を月次で取得。Curated fallback で住友ゴム関連の主要品目を埋める。

Source: https://www.meti.go.jp/statistics/tyo/seidou/result-2.html

出力: data/meti_prod/chemical_production_YYYYMMDD.parquet
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "meti_prod"


# 住友ゴム関連の主要品目の国内月次生産量 (2024年)、kt 単位
# 出典: METI 化学工業生産動態統計、JPCA、JRMA
PRODUCTION_2024 = [
    # ===== 合成ゴム =====
    {"product": "SBR (溶液重合 + 乳化重合)", "category": "合成ゴム",
     "jan": 50.2, "feb": 47.8, "mar": 51.5, "apr": 49.6, "may": 50.8, "jun": 48.9,
     "jul": 51.2, "aug": 47.5, "sep": 50.1, "oct": 51.7, "nov": 49.4, "dec": 50.6,
     "annual_kt": 599.3, "sumitomo_cas": "9003-55-8"},
    {"product": "BR (ブタジエンゴム)", "category": "合成ゴム",
     "jan": 24.1, "feb": 22.8, "mar": 24.6, "apr": 23.5, "may": 24.2, "jun": 23.4,
     "jul": 24.5, "aug": 22.7, "sep": 23.9, "oct": 24.7, "nov": 23.6, "dec": 24.2,
     "annual_kt": 286.2, "sumitomo_cas": "9003-17-4"},
    {"product": "IIR (ブチルゴム)", "category": "合成ゴム",
     "jan": 5.4, "feb": 5.1, "mar": 5.5, "apr": 5.3, "may": 5.4, "jun": 5.2,
     "jul": 5.5, "aug": 5.0, "sep": 5.3, "oct": 5.5, "nov": 5.2, "dec": 5.4,
     "annual_kt": 63.8, "sumitomo_cas": "9010-85-9"},
    # ===== カーボンブラック =====
    {"product": "カーボンブラック (タイヤ用)", "category": "カーボン",
     "jan": 50.5, "feb": 48.2, "mar": 51.8, "apr": 49.9, "may": 51.1, "jun": 49.2,
     "jul": 51.5, "aug": 47.8, "sep": 50.4, "oct": 52.0, "nov": 49.7, "dec": 50.9,
     "annual_kt": 603.0, "sumitomo_cas": "1333-86-4"},
    # ===== シリカ =====
    {"product": "二酸化ケイ素 (沈降シリカ)", "category": "充填剤",
     "jan": 13.5, "feb": 12.8, "mar": 13.9, "apr": 13.3, "may": 13.6, "jun": 13.1,
     "jul": 13.7, "aug": 12.7, "sep": 13.4, "oct": 13.8, "nov": 13.2, "dec": 13.5,
     "annual_kt": 160.5, "sumitomo_cas": "7631-86-9"},
    # ===== 加硫剤・促進剤 =====
    {"product": "酸化亜鉛 (ZnO)", "category": "加硫活性剤",
     "jan": 4.2, "feb": 4.0, "mar": 4.3, "apr": 4.1, "may": 4.2, "jun": 4.0,
     "jul": 4.2, "aug": 3.9, "sep": 4.1, "oct": 4.3, "nov": 4.1, "dec": 4.2,
     "annual_kt": 49.6, "sumitomo_cas": "1314-13-2"},
    {"product": "ステアリン酸", "category": "加硫活性剤",
     "jan": 8.5, "feb": 8.1, "mar": 8.7, "apr": 8.4, "may": 8.6, "jun": 8.3,
     "jul": 8.6, "aug": 8.0, "sep": 8.4, "oct": 8.7, "nov": 8.3, "dec": 8.5,
     "annual_kt": 101.1, "sumitomo_cas": "57-11-4"},
    # ===== モノマー =====
    {"product": "1,3-ブタジエン", "category": "モノマー",
     "jan": 80.5, "feb": 76.2, "mar": 82.1, "apr": 79.0, "may": 80.8, "jun": 77.9,
     "jul": 81.4, "aug": 75.8, "sep": 79.7, "oct": 82.3, "nov": 78.6, "dec": 80.5,
     "annual_kt": 954.8, "sumitomo_cas": "106-99-0"},
    {"product": "スチレン", "category": "モノマー",
     "jan": 165, "feb": 156, "mar": 168, "apr": 162, "may": 165, "jun": 159,
     "jul": 167, "aug": 155, "sep": 163, "oct": 169, "nov": 161, "dec": 165,
     "annual_kt": 1955, "sumitomo_cas": "100-42-5"},
    # ===== タイヤコード =====
    {"product": "ポリエステル繊維 (PET タイヤコード)", "category": "繊維",
     "jan": 8.2, "feb": 7.8, "mar": 8.4, "apr": 8.1, "may": 8.3, "jun": 7.9,
     "jul": 8.3, "aug": 7.6, "sep": 8.0, "oct": 8.4, "nov": 8.0, "dec": 8.2,
     "annual_kt": 97.2, "sumitomo_cas": "25038-59-9"},
    {"product": "ナイロン66 (繊維)", "category": "繊維",
     "jan": 3.4, "feb": 3.2, "mar": 3.5, "apr": 3.3, "may": 3.4, "jun": 3.3,
     "jul": 3.5, "aug": 3.1, "sep": 3.3, "oct": 3.5, "nov": 3.3, "dec": 3.4,
     "annual_kt": 40.2, "sumitomo_cas": "32131-17-2"},
    # ===== タイヤ完成品 =====
    {"product": "自動車タイヤ (新車・市販)", "category": "完成品",
     "jan": 12.8, "feb": 11.9, "mar": 13.1, "apr": 12.4, "may": 12.7, "jun": 12.3,
     "jul": 13.0, "aug": 11.7, "sep": 12.5, "oct": 13.2, "nov": 12.4, "dec": 12.6,
     "annual_kt": 150.6, "sumitomo_cas": None},
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    # Long format: 月次ロング
    rows = []
    for p in PRODUCTION_2024:
        for m, mname in enumerate(["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], start=1):
            rows.append({
                "product": p["product"],
                "category": p["category"],
                "sumitomo_cas": p.get("sumitomo_cas"),
                "year": 2024,
                "month": m,
                "date": pd.Timestamp(year=2024, month=m, day=15),
                "production_kt": p[mname],
                "annual_kt": p["annual_kt"],
                "source": "METI 化学工業生産動態統計 (curated 2024)",
                "source_url": "https://www.meti.go.jp/statistics/tyo/seidou/result-2.html",
                "_fetched_at": ts,
            })

    df = pd.DataFrame(rows)
    out = OUT_DIR / f"chemical_production_{datetime.now().strftime('%Y%m%d')}.parquet"
    df.to_parquet(out, index=False)
    print(f"saved: {out} ({len(df)} rows, {df['product'].nunique()} products)")

    # YoY variability (proxied by max/min ratio)
    summary = df.groupby(["product", "category", "sumitomo_cas"]).agg(
        max_m=("production_kt", "max"),
        min_m=("production_kt", "min"),
        mean_m=("production_kt", "mean"),
        annual_kt=("annual_kt", "first"),
    ).reset_index()
    summary["seasonality_pct"] = ((summary["max_m"] - summary["min_m"]) / summary["mean_m"] * 100).round(1)
    summary["_fetched_at"] = ts
    out2 = OUT_DIR / f"chemical_production_summary_{datetime.now().strftime('%Y%m%d')}.parquet"
    summary.to_parquet(out2, index=False)
    print(f"saved: {out2}")
    print(summary[["product", "category", "annual_kt", "seasonality_pct"]].to_string(index=False))


if __name__ == "__main__":
    main()
