"""FAOSTAT Natural Rubber Production — 国別×年次 (API + ANRPC/IRSG curated fallback).

FAOSTAT JSON API:
  domain QCL (Crops and livestock products)
  item   1042 = Natural rubber, dry
  element 5510 = Production
  area = 主要産国 (TH, ID, VN, MY, CI, IN, CN, etc.)

Fallback: API が unreachable な時は ANRPC/IRSG 公開数値の curated 2023 データで埋める。
FAOSTAT 復活したら自動で本データに置き換わる。

Output: data/faostat/natural_rubber_production_YYYYMMDD.parquet
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "faostat"

FAO_BASE = "https://fenixservices.fao.org/faostat/api/v1/en/data/QCL"

# 主要天然ゴム生産国 (FAOSTAT M49 codes / FAO area codes)
# https://www.fao.org/faostat/en/#definitions
TARGET_COUNTRIES = [
    "TH",   # Thailand
    "ID",   # Indonesia
    "VN",   # Vietnam
    "CI",   # Côte d'Ivoire (近年急増)
    "IN",   # India
    "MY",   # Malaysia
    "CN",   # China
    "GT",   # Guatemala
    "MX",   # Mexico
    "MM",   # Myanmar
    "LK",   # Sri Lanka
    "PH",   # Philippines
    "LR",   # Liberia
    "KH",   # Cambodia
    "BR",   # Brazil
    "NG",   # Nigeria
    "CM",   # Cameroon
    "GH",   # Ghana
    "LA",   # Laos
    "BD",   # Bangladesh
]


def _safe_int(v):
    try:
        return int(float(v))
    except Exception:
        return None


def _try_faostat_api(ts: str) -> list[dict] | None:
    """Try FAOSTAT API. Returns rows or None on failure."""
    current_year = datetime.now().year
    years = list(range(current_year - 10, current_year))

    params = [
        ("area", c) for c in TARGET_COUNTRIES
    ] + [
        ("item", "1042"),
        ("element", "5510"),
        ("output_type", "objects"),
    ] + [
        ("year", str(y)) for y in years
    ]

    try:
        r = requests.get(
            FAO_BASE, params=params, timeout=20,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        print(f"FAOSTAT API failed: {e}")
        return None

    data = d.get("data") or []
    if not data:
        return None

    rows = []
    for rec in data:
        rows.append({
            "area_code": rec.get("Area Code (M49)") or rec.get("Area Code"),
            "area": rec.get("Area"),
            "year": _safe_int(rec.get("Year")),
            "item": rec.get("Item"),
            "element": rec.get("Element"),
            "unit": rec.get("Unit"),
            "value": _safe_int(rec.get("Value")),
            "flag": rec.get("Flag"),
            "flag_description": rec.get("Flag Description"),
            "source": "FAOSTAT_API",
            "_fetched_at": ts,
        })
    return rows


# ANRPC / IRSG 2023 公開数値（thousand tonnes / kt）
# Sources: ANRPC Natural Rubber Trends & Statistics, IRSG Rubber Statistical Bulletin
CURATED_2023 = [
    ("Thailand",     "TH", 4830),
    ("Indonesia",    "ID", 2720),
    ("Côte d'Ivoire","CI", 1500),
    ("Vietnam",      "VN", 1295),
    ("India",        "IN",  860),
    ("China",        "CN",  856),
    ("Malaysia",     "MY",  460),
    ("Cambodia",     "KH",  442),
    ("Philippines",  "PH",  430),
    ("Myanmar",      "MM",  280),
    ("Brazil",       "BR",  210),
    ("Laos",         "LA",  170),
    ("Nigeria",      "NG",  145),
    ("Guatemala",    "GT",  115),
    ("Liberia",      "LR",  100),
    ("Sri Lanka",    "LK",   70),
    ("Cameroon",     "CM",   50),
    ("Mexico",       "MX",   50),
    ("Ghana",        "GH",   40),
    ("Bangladesh",   "BD",   10),
]


def _curated_fallback(ts: str) -> list[dict]:
    """Manually curated ANRPC/IRSG 2023 figures (used when FAOSTAT API is down)."""
    return [
        {
            "area_code": code,
            "area": name,
            "year": 2023,
            "item": "Natural rubber, dry",
            "element": "Production",
            "unit": "kt",
            "value": value,
            "flag": "X",
            "flag_description": "Figure from international organizations (ANRPC/IRSG curated)",
            "source": "ANRPC_IRSG_CURATED",
            "_fetched_at": ts,
        }
        for (name, code, value) in CURATED_2023
    ]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    rows = _try_faostat_api(ts)
    if rows:
        print(f"  Source: FAOSTAT API ({len(rows)} rows)")
    else:
        rows = _curated_fallback(ts)
        print(f"  Source: ANRPC/IRSG curated 2023 fallback ({len(rows)} rows)")
    data = rows

    df = pd.DataFrame(data)
    print(f"Fetched: {len(df)} rows, {df['area'].nunique()} countries, years {df['year'].min()}-{df['year'].max()}")

    out = OUT_DIR / f"natural_rubber_production_{datetime.now().strftime('%Y%m%d')}.parquet"
    df.to_parquet(out, index=False)
    print(f"saved: {out}")

    # Summary: 最新年のトップ国とシェア
    latest_year = df["year"].max()
    latest = df[df["year"] == latest_year].copy()
    total = latest["value"].sum()
    latest["share_pct"] = latest["value"] / total * 100
    latest = latest.sort_values("share_pct", ascending=False)
    print(f"\n=== Latest Year ({latest_year}) Natural Rubber Production Shares ===")
    print(latest[["area", "value", "unit", "share_pct"]].head(15).to_string(index=False))

    # HHI 計算 (主要産国のシェアから)
    hhi = float((latest["share_pct"] ** 2).sum())
    print(f"\nHHI (主要産国): {hhi:.0f}")
    print(f"Top country: {latest.iloc[0]['area']} ({latest.iloc[0]['share_pct']:.1f}%)")

    summary_rows = [{
        "item": "Natural rubber, dry",
        "fao_item_code": 1042,
        "year": int(latest_year),
        "top_country": latest.iloc[0]["area"],
        "top_share_pct": round(float(latest.iloc[0]["share_pct"]), 1),
        "hhi": round(hhi, 0),
        "total_production": int(total),
        "unit": latest.iloc[0]["unit"],
        "_fetched_at": ts,
    }]
    summary_out = OUT_DIR / f"natural_rubber_summary_{datetime.now().strftime('%Y%m%d')}.parquet"
    pd.DataFrame(summary_rows).to_parquet(summary_out, index=False)
    print(f"saved: {summary_out}")


if __name__ == "__main__":
    main()
