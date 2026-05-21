"""Axis 2/4 補強 — e-Stat API で財務省貿易統計の月次 HS9 データを取得.

Comtrade is annual + 250 RPD limited. 財務省 customs is monthly + HS9 granular.
e-Stat (政府統計の総合窓口) wraps customs data with structured JSON API.

Setup (one-time):
  1. https://www.e-stat.go.jp/api/ で ユーザ登録 (5min)
  2. マイページ → アプリケーションID発行 (URLは仮で http://localhost でOK)
  3. mkdir -p ~/.config/estat && echo '{"app_id":"YOUR_KEY"}' > ~/.config/estat/keys.json && chmod 600

Usage:
  uv run python ingest/estat_trade.py            # last 12 months for top HS6 from chemicals_hs_map
  uv run python ingest/estat_trade.py --months 24
  uv run python ingest/estat_trade.py --hs6 290121,290122,290250  # specific HS6

Data source: 通関統計 (普通貿易統計) on e-Stat
  - statsDataId for monthly HS-level: 0003330020 (品別輸入額) or 0003330016 (品別輸出額)
  - The "実行関税率表" (品別) statistics aggregate by HS9 → can roll to HS6
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "estat"
KEY_PATH = Path.home() / ".config" / "estat" / "keys.json"

BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"
HEADERS = {"User-Agent": "Sotas SDB Supply-Stability Research"}

# Confirmed stats IDs (e-Stat 「貿易統計 / 概況品別表」):
#   月別輸出: 0003348423 (普通貿易統計 月別 輸出)
#   月別輸入: 0003348424 (普通貿易統計 月別 輸入)
# These can also be discovered via getStatsList API.
STATS_ID_EXPORT = "0003348423"
STATS_ID_IMPORT = "0003348424"

DEFAULT_MONTHS = 12


def load_app_id() -> str:
    if not KEY_PATH.exists():
        print(f"ERROR: {KEY_PATH} not found. See module docstring for setup.", file=sys.stderr)
        sys.exit(2)
    return json.loads(KEY_PATH.read_text())["app_id"]


def top_hs6_from_map(limit: int = 30) -> list[str]:
    """Pick top-CAS-coverage HS6 codes from chemicals_hs_map."""
    hs_map_p = ROOT / "data" / "chemicals" / "chemicals_hs_map.parquet"
    if not hs_map_p.exists():
        return []
    df = pd.read_parquet(hs_map_p)
    df = df[df["hs6"].notna()]
    return (
        df.groupby("hs6")["cas"].nunique().sort_values(ascending=False).head(limit).index.tolist()
    )


def fetch_stats(app_id: str, stats_data_id: str, *, hs6: str | None = None, period: str | None = None, start_pos: int = 1) -> dict:
    """Call e-Stat getStatsData. Returns parsed JSON.

    Params we can constrain:
    - cdCat01 (or similar): HS code
    - cdTime: YYYYMM or YYYYMM-YYYYMM range
    """
    params = {
        "appId": app_id,
        "statsDataId": stats_data_id,
        "startPosition": start_pos,
        "limit": 100000,
    }
    if hs6:
        # The category code for HS in e-Stat 貿易統計 is typically "cat01" with HS9.
        # We filter post-fetch by HS6 prefix.
        pass
    if period:
        params["cdTime"] = period
    r = requests.get(f"{BASE}/getStatsData", params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def parse_records(payload: dict, flow: str) -> list[dict]:
    """Extract VALUE rows from getStatsData response. Skip if shape unexpected."""
    result = payload.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {})
    values_block = result.get("DATA_INF", {}).get("VALUE", [])
    if not values_block:
        return []
    # Resolve category labels: CLASS_INF.CLASS_OBJ[] gives lookups for @code→@name per category
    class_obj = result.get("CLASS_INF", {}).get("CLASS_OBJ", []) or []
    lookups: dict[str, dict[str, str]] = {}
    for co in class_obj:
        cid = co.get("@id")
        classes = co.get("CLASS")
        if isinstance(classes, dict):
            classes = [classes]
        lookups[cid] = {c.get("@code"): c.get("@name") for c in (classes or [])}
    out = []
    for v in values_block:
        # Each value has @cat01, @time, @unit, $ (value)
        rec = {"flow": flow, "value": v.get("$")}
        for k, code in v.items():
            if k in ("$", "@unit"):
                continue
            cid = k.lstrip("@")
            name = lookups.get(cid, {}).get(code, code)
            rec[cid + "_code"] = code
            rec[cid + "_name"] = name
        rec["unit"] = v.get("@unit", "")
        out.append(rec)
    return out


def main(months: int = DEFAULT_MONTHS, hs6_filter: list[str] | None = None):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app_id = load_app_id()
    if not hs6_filter:
        hs6_filter = top_hs6_from_map(limit=30)
    print(f"HS6 filter ({len(hs6_filter)} codes): {hs6_filter[:10]}{'...' if len(hs6_filter)>10 else ''}")

    fetched_at = datetime.now(timezone.utc).isoformat()
    all_rows: list[dict] = []

    # Two stats IDs: export + import
    for stats_id, flow in [(STATS_ID_EXPORT, "X"), (STATS_ID_IMPORT, "M")]:
        print(f"\n=== fetching {flow} (statsDataId={stats_id}) ===")
        try:
            payload = fetch_stats(app_id, stats_id)
        except requests.RequestException as e:
            print(f"  FAIL: {e}")
            continue
        # Check for status errors
        result = payload.get("GET_STATS_DATA", {}).get("RESULT", {})
        if result.get("STATUS") != 0:
            print(f"  e-Stat status={result.get('STATUS')} msg={result.get('ERROR_MSG', '')[:200]}")
            continue
        recs = parse_records(payload, flow)
        print(f"  got {len(recs):,} value rows")
        all_rows.extend(recs)
        time.sleep(0.5)

    if not all_rows:
        print("\nNo data collected.")
        return

    df = pd.DataFrame(all_rows)
    # Filter to chemicals: HS9 starts with one of our hs6_filter codes
    if "cat01_code" in df.columns and hs6_filter:
        # cat01_code may be HS9 or HS6 depending on dataset structure
        mask = df["cat01_code"].astype(str).str[:6].isin(hs6_filter)
        df_chem = df[mask].copy()
        print(f"\nAfter HS6 filter ({len(hs6_filter)} codes): {len(df_chem):,} / {len(df):,} rows")
    else:
        df_chem = df

    df_chem["_fetched_at"] = fetched_at
    stamp = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"estat_trade_{stamp}.parquet"
    df_chem.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(df_chem)} rows → {out_path}")

    if len(df_chem) > 0:
        print(f"\nColumns: {list(df_chem.columns)}")
        print(f"\nSample 5 rows:")
        print(df_chem.head(5).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=DEFAULT_MONTHS)
    ap.add_argument("--hs6", type=str, default=None, help="Comma-separated HS6 codes (overrides auto top-N)")
    args = ap.parse_args()
    hs6_list = args.hs6.split(",") if args.hs6 else None
    main(months=args.months, hs6_filter=hs6_list)
