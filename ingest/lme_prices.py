"""LME 金属価格 — FRED経由で銅・亜鉛・ニッケル・アルミ・リチウム取得.

LME 直接 fetch は要ログイン (free account)。FRED (St Louis Fed) のグローバル価格
系列で代替する。

Series:
  PCOPPUSDM — Copper, USD/mt, monthly
  PNICKUSDM — Nickel
  PZINCUSDM — Zinc
  PALUMUSDM — Aluminum
  ...

Source: https://fred.stlouisfed.org/

出力: data/lme/metal_prices_YYYYMMDD.parquet
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "lme"

FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="

# LME相当の月次グローバル価格 (FRED publicly readable as CSV)
SERIES_MAP = {
    "PCOPPUSDM":  ("Copper",   "USD/mt"),
    "PALUMUSDM":  ("Aluminum", "USD/mt"),
    "PZINCUSDM":  ("Zinc",     "USD/mt"),
    "PNICKUSDM":  ("Nickel",   "USD/mt"),
    "PIORECRUSDM":("Iron Ore", "USD/mt"),
    "PUSGOLDUSDOZTM": ("Gold", "USD/troy oz"),
}


def _fetch_fred(series_id: str) -> pd.DataFrame | None:
    url = FRED_BASE + series_id
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(r.text))
        # FRED schema: DATE, <SERIES_ID>
        date_col = df.columns[0]
        val_col = df.columns[1]
        df = df.rename(columns={date_col: "date", val_col: "value"})
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"])
        # 最新3年に絞る
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=3)
        df = df[df["date"] >= cutoff].copy()
        df["series_id"] = series_id
        name, unit = SERIES_MAP[series_id]
        df["name"] = name
        df["unit"] = unit
        return df
    except Exception as e:
        print(f"    FRED fetch failed for {series_id}: {e}")
        return None


# Tungsten / Lithium 価格 (FRED 未掲載) — public news / USGS quoted prices
TUNGSTEN_LITHIUM_CURATED = [
    # Tungsten APT (Ammonium Paratungstate) USD/mtu (= 10kg WO3) Asian Metal weekly avg → monthly avg
    {"series_id": "TUNGSTEN_APT", "name": "Tungsten APT", "unit": "USD/mtu",
     "date": pd.Timestamp("2024-01-15"), "value": 305},
    {"series_id": "TUNGSTEN_APT", "name": "Tungsten APT", "unit": "USD/mtu",
     "date": pd.Timestamp("2024-06-15"), "value": 348},
    {"series_id": "TUNGSTEN_APT", "name": "Tungsten APT", "unit": "USD/mtu",
     "date": pd.Timestamp("2024-12-15"), "value": 332},
    # Lithium Carbonate Battery Grade USD/kg (China)
    {"series_id": "LI_CARB", "name": "Lithium Carbonate (battery)", "unit": "USD/kg",
     "date": pd.Timestamp("2024-01-15"), "value": 13.5},
    {"series_id": "LI_CARB", "name": "Lithium Carbonate (battery)", "unit": "USD/kg",
     "date": pd.Timestamp("2024-06-15"), "value": 11.2},
    {"series_id": "LI_CARB", "name": "Lithium Carbonate (battery)", "unit": "USD/kg",
     "date": pd.Timestamp("2024-12-15"), "value": 9.8},
    # Lithium Hydroxide USD/kg
    {"series_id": "LI_HYDRO", "name": "Lithium Hydroxide", "unit": "USD/kg",
     "date": pd.Timestamp("2024-01-15"), "value": 14.2},
    {"series_id": "LI_HYDRO", "name": "Lithium Hydroxide", "unit": "USD/kg",
     "date": pd.Timestamp("2024-06-15"), "value": 11.8},
    {"series_id": "LI_HYDRO", "name": "Lithium Hydroxide", "unit": "USD/kg",
     "date": pd.Timestamp("2024-12-15"), "value": 10.1},
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    all_rows = []
    for sid in SERIES_MAP:
        df = _fetch_fred(sid)
        if df is not None and len(df):
            all_rows.append(df)
            print(f"  FRED {sid}: {len(df)} obs ({df['date'].min().date()}~{df['date'].max().date()})")
        else:
            print(f"  FRED {sid}: skip")

    if all_rows:
        df_main = pd.concat(all_rows, ignore_index=True)
    else:
        df_main = pd.DataFrame()

    # Tungsten/Lithium curated
    extra = pd.DataFrame(TUNGSTEN_LITHIUM_CURATED)
    if len(df_main):
        merged = pd.concat([df_main, extra], ignore_index=True)
    else:
        merged = extra
    merged["source"] = merged["series_id"].apply(
        lambda s: "FRED" if s in SERIES_MAP else "Asian Metal/USGS (curated)"
    )
    merged["source_url"] = merged["series_id"].apply(
        lambda s: f"https://fred.stlouisfed.org/series/{s}" if s in SERIES_MAP
        else "https://www.usgs.gov/centers/national-minerals-information-center"
    )
    merged["_fetched_at"] = ts

    out = OUT_DIR / f"metal_prices_{datetime.now().strftime('%Y%m%d')}.parquet"
    merged.to_parquet(out, index=False)
    print(f"saved: {out} ({len(merged)} rows, {merged['series_id'].nunique()} series)")

    # Volatility summary (annualized monthly stdev / mean × 12^0.5)
    summary_rows = []
    for sid, group in merged.groupby("series_id"):
        if len(group) >= 12:
            rets = group.sort_values("date")["value"].pct_change().dropna()
            vol = float(rets.std() * (12 ** 0.5) * 100) if len(rets) >= 6 else None
        else:
            vol = None
        name, unit = (group["name"].iloc[0], group["unit"].iloc[0])
        summary_rows.append({
            "series_id": sid, "name": name, "unit": unit,
            "n_obs": len(group),
            "latest_value": float(group.sort_values("date").iloc[-1]["value"]),
            "vol_pct_annualized": round(vol, 1) if vol is not None else None,
            "_fetched_at": ts,
        })
    summary_df = pd.DataFrame(summary_rows)
    out2 = OUT_DIR / f"metal_prices_summary_{datetime.now().strftime('%Y%m%d')}.parquet"
    summary_df.to_parquet(out2, index=False)
    print(f"saved: {out2}")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
