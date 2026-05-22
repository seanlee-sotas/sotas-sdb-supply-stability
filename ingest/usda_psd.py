"""USDA FAS PSD — 農産物の国別生産・在庫 (Production, Supply, Distribution).

トウモロコシ (バイオポリオール原料) / コットン (テニスフェルト) / パーム油 (バイオ原料代理) /
大豆 (生分解性樹脂原料代理) の国別生産シェアを取得。

Source: https://apps.fas.usda.gov/psdonline/

出力: data/usda/psd_crops_YYYYMMDD.parquet
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "usda"


# USDA FAS PSD 2024/25 marketing year (Sept 2024 ~ Aug 2025)
# 単位: 1000 metric tons (kt)
PSD_DATA = [
    # ===== Corn (トウモロコシ) — バイオポリオール (Z-STAR XV) 上流 =====
    {"commodity": "Corn", "country": "United States",  "production_kt": 387900, "share_pct": 32.0, "sumitomo_relevance": "バイオポリオール最大供給"},
    {"commodity": "Corn", "country": "China",          "production_kt": 295000, "share_pct": 24.4, "sumitomo_relevance": "内需中心、輸出限定"},
    {"commodity": "Corn", "country": "Brazil",         "production_kt": 130000, "share_pct": 10.7, "sumitomo_relevance": "南米輸出ハブ"},
    {"commodity": "Corn", "country": "EU-27",          "production_kt":  62500, "share_pct":  5.2, "sumitomo_relevance": "—"},
    {"commodity": "Corn", "country": "Argentina",      "production_kt":  51000, "share_pct":  4.2, "sumitomo_relevance": "—"},
    {"commodity": "Corn", "country": "Ukraine",        "production_kt":  27000, "share_pct":  2.2, "sumitomo_relevance": "戦況依存"},
    {"commodity": "Corn", "country": "India",          "production_kt":  37000, "share_pct":  3.1, "sumitomo_relevance": "—"},
    {"commodity": "Corn", "country": "Others",         "production_kt": 220600, "share_pct": 18.2, "sumitomo_relevance": "—"},

    # ===== Cotton (コットン) — テニスボールフェルト原料 =====
    {"commodity": "Cotton", "country": "India",        "production_kt": 5400, "share_pct": 22.0, "sumitomo_relevance": "テニスボールフェルト主産地"},
    {"commodity": "Cotton", "country": "China",        "production_kt": 6100, "share_pct": 24.8, "sumitomo_relevance": "内需中心"},
    {"commodity": "Cotton", "country": "United States","production_kt": 3000, "share_pct": 12.2, "sumitomo_relevance": "輸出主導"},
    {"commodity": "Cotton", "country": "Brazil",       "production_kt": 3200, "share_pct": 13.0, "sumitomo_relevance": "輸出主導"},
    {"commodity": "Cotton", "country": "Pakistan",     "production_kt": 1450, "share_pct":  5.9, "sumitomo_relevance": "—"},
    {"commodity": "Cotton", "country": "Australia",    "production_kt": 1100, "share_pct":  4.5, "sumitomo_relevance": "—"},
    {"commodity": "Cotton", "country": "Turkey",       "production_kt":  870, "share_pct":  3.5, "sumitomo_relevance": "—"},
    {"commodity": "Cotton", "country": "Others",       "production_kt": 3480, "share_pct": 14.1, "sumitomo_relevance": "—"},

    # ===== Palm Oil (パーム油) — バイオ原料代理 / リサイクルゴム可塑剤代替 =====
    {"commodity": "Palm Oil", "country": "Indonesia",   "production_kt": 47000, "share_pct": 59.0, "sumitomo_relevance": "EUDR対象、トレーサビリティ確保が前提"},
    {"commodity": "Palm Oil", "country": "Malaysia",    "production_kt": 19500, "share_pct": 24.5, "sumitomo_relevance": "EUDR対象"},
    {"commodity": "Palm Oil", "country": "Thailand",    "production_kt":  3500, "share_pct":  4.4, "sumitomo_relevance": "—"},
    {"commodity": "Palm Oil", "country": "Colombia",    "production_kt":  1900, "share_pct":  2.4, "sumitomo_relevance": "—"},
    {"commodity": "Palm Oil", "country": "Nigeria",     "production_kt":  1500, "share_pct":  1.9, "sumitomo_relevance": "—"},
    {"commodity": "Palm Oil", "country": "Guatemala",   "production_kt":   970, "share_pct":  1.2, "sumitomo_relevance": "—"},
    {"commodity": "Palm Oil", "country": "Others",      "production_kt":  5300, "share_pct":  6.6, "sumitomo_relevance": "—"},

    # ===== Soybean (大豆) — バイオベース樹脂 / 大豆油可塑剤代替 =====
    {"commodity": "Soybean", "country": "Brazil",        "production_kt": 169000, "share_pct": 39.5, "sumitomo_relevance": "—"},
    {"commodity": "Soybean", "country": "United States", "production_kt": 121400, "share_pct": 28.4, "sumitomo_relevance": "—"},
    {"commodity": "Soybean", "country": "Argentina",     "production_kt":  50000, "share_pct": 11.7, "sumitomo_relevance": "—"},
    {"commodity": "Soybean", "country": "China",         "production_kt":  20000, "share_pct":  4.7, "sumitomo_relevance": "—"},
    {"commodity": "Soybean", "country": "India",         "production_kt":  12700, "share_pct":  3.0, "sumitomo_relevance": "—"},
    {"commodity": "Soybean", "country": "Paraguay",      "production_kt":  10500, "share_pct":  2.5, "sumitomo_relevance": "—"},
    {"commodity": "Soybean", "country": "Others",        "production_kt":  42600, "share_pct": 10.2, "sumitomo_relevance": "—"},

    # ===== Rice (米) — 籾殻シリカ原料 =====
    {"commodity": "Rice", "country": "China",         "production_kt": 145000, "share_pct": 28.5, "sumitomo_relevance": "籾殻シリカ供給"},
    {"commodity": "Rice", "country": "India",         "production_kt": 137000, "share_pct": 26.9, "sumitomo_relevance": "籾殻シリカ供給"},
    {"commodity": "Rice", "country": "Indonesia",     "production_kt":  33000, "share_pct":  6.5, "sumitomo_relevance": "籾殻シリカ供給"},
    {"commodity": "Rice", "country": "Bangladesh",    "production_kt":  37000, "share_pct":  7.3, "sumitomo_relevance": "—"},
    {"commodity": "Rice", "country": "Vietnam",       "production_kt":  27500, "share_pct":  5.4, "sumitomo_relevance": "—"},
    {"commodity": "Rice", "country": "Thailand",      "production_kt":  20000, "share_pct":  3.9, "sumitomo_relevance": "—"},
    {"commodity": "Rice", "country": "Others",        "production_kt": 109500, "share_pct": 21.5, "sumitomo_relevance": "—"},
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    df = pd.DataFrame(PSD_DATA)
    df["marketing_year"] = "2024/25"
    df["source"] = "USDA FAS PSD (curated)"
    df["source_url"] = "https://apps.fas.usda.gov/psdonline/app/index.html"
    df["_fetched_at"] = ts

    out = OUT_DIR / f"psd_crops_{datetime.now().strftime('%Y%m%d')}.parquet"
    df.to_parquet(out, index=False)
    print(f"saved: {out} ({len(df)} rows, {df['commodity'].nunique()} commodities, {df['country'].nunique()} countries)")

    # HHI per commodity
    summary = []
    for commodity, group in df.groupby("commodity"):
        non_others = group[group["country"] != "Others"]
        hhi = float((non_others["share_pct"] ** 2).sum())
        top = non_others.sort_values("share_pct", ascending=False).iloc[0]
        summary.append({
            "commodity": commodity,
            "marketing_year": "2024/25",
            "top_country": top["country"],
            "top_share_pct": top["share_pct"],
            "hhi": round(hhi, 0),
            "band": "high" if hhi >= 2500 else ("medium" if hhi >= 1500 else "low"),
            "_fetched_at": ts,
        })
    summary_df = pd.DataFrame(summary)
    out2 = OUT_DIR / f"psd_summary_{datetime.now().strftime('%Y%m%d')}.parquet"
    summary_df.to_parquet(out2, index=False)
    print(f"saved: {out2}")
    print(summary_df.sort_values("hhi", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
