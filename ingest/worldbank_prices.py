"""Axis 7 (価格変動性) ingest — World Bank Pink Sheet monthly commodity prices.

Free, monthly-updated, 60+ years history. Includes Rubber TSR20 / RSS3, Brent,
WTI, Dubai, Natural gas (Japan/EU/US), Coal, Cotton — directly relevant to
rubber/tire/petchem SDB scope.

The xlsx URL contains a versioned hash; we scrape the landing page to find the
current URL each run.

Source: https://www.worldbank.org/en/research/commodity-markets
"""
import io
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "worldbank"
LANDING_URL = "https://www.worldbank.org/en/research/commodity-markets"
HEADERS = {"User-Agent": "Mozilla/5.0 (sotas-sdb-supply-stability)"}

# Commodity short codes (row 6 of 'Monthly Prices') most relevant to SDB scope
SCOPE = [
    "CRUDE_BRENT",
    "CRUDE_DUBAI",
    "CRUDE_WTI",
    "NGAS_US",
    "NGAS_EUR",
    "NGAS_JP",
    "COAL_AUS",
    "RUBBER_TSR20",
    "RUBBER1_MYSG",
    "COTTON_A_INDX",
    "ALUMINUM",
    "COPPER",
    "NICKEL",
    "Zinc",
    "GOLD",
]


def find_monthly_xlsx_url() -> str:
    r = requests.get(LANDING_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    candidates = re.findall(r'href="([^"]*CMO-Historical-Data-Monthly\.xlsx[^"]*)"', r.text)
    if not candidates:
        raise RuntimeError("Couldn't find Monthly xlsx link on landing page")
    return candidates[0]


def fetch_monthly_prices() -> pd.DataFrame:
    url = find_monthly_xlsx_url()
    print(f"Downloading {url}")
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    raw = pd.read_excel(io.BytesIO(r.content), sheet_name="Monthly Prices", header=None)
    # Row 4: long names, Row 5: units, Row 6: short codes, Row 7+: data
    long_names = raw.iloc[4].tolist()
    units = raw.iloc[5].tolist()
    codes = raw.iloc[6].tolist()
    data = raw.iloc[7:].reset_index(drop=True)
    # Build a clean wide DF then melt
    cols = []
    for i, c in enumerate(codes):
        if i == 0:
            cols.append("period")
        else:
            cols.append(str(c) if pd.notna(c) else f"col{i}")
    data.columns = cols
    # Filter columns to our scope + period
    keep = ["period"] + [c for c in SCOPE if c in data.columns]
    data = data[keep].copy()
    # Drop rows where period is NaN / blank
    data = data[data["period"].notna()].copy()
    # Convert period (e.g. "1960M01") to datetime
    data["period"] = data["period"].astype(str)
    data["date"] = pd.to_datetime(data["period"].str.replace("M", "-") + "-01", errors="coerce")
    data = data[data["date"].notna()].copy()
    # Melt to long format
    long = data.melt(id_vars=["period", "date"], var_name="commodity", value_name="price")
    # Map unit and name
    code_to_unit = {str(c): str(units[i]) for i, c in enumerate(codes) if pd.notna(c)}
    code_to_name = {str(c): str(long_names[i]) for i, c in enumerate(codes) if pd.notna(c)}
    long["unit"] = long["commodity"].map(code_to_unit)
    long["name"] = long["commodity"].map(code_to_name)
    # Drop rows with missing prices (encoded as "…" or other non-numeric)
    long["price"] = pd.to_numeric(long["price"], errors="coerce")
    long = long.dropna(subset=["price"]).copy()
    long["_fetched_at"] = datetime.now(timezone.utc).isoformat()
    return long


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = fetch_monthly_prices()
    stamp = datetime.now().strftime("%Y%m%d")
    out = DATA_DIR / f"prices_monthly_{stamp}.parquet"
    df.to_parquet(out, index=False, compression="snappy")
    print(f"\nWrote {len(df)} rows ({df['commodity'].nunique()} commodities, "
          f"{df['date'].min().date()}–{df['date'].max().date()}) to {out}")
    print("\nLatest 5 commodity prices:")
    latest = df.sort_values(["commodity", "date"]).groupby("commodity").tail(1)[["name", "date", "price", "unit"]]
    print(latest.to_string(index=False))


if __name__ == "__main__":
    main()
