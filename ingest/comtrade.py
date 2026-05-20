"""Fetch UN Comtrade trade data per HS code/flow/period and write Parquet.

Reads API key from ~/.config/comtrade/keys.json, scope from ingest/hs_codes.yml.
Use --quick to fetch only the latest period (first in `periods:` list).
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
KEYS_PATH = Path.home() / ".config" / "comtrade" / "keys.json"
CONFIG_PATH = ROOT / "ingest" / "hs_codes.yml"
DATA_DIR = ROOT / "data" / "comtrade"
BASE_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
REF_REPORTERS_URL = "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json"
REF_H6_URL = "https://comtradeapi.un.org/files/v1/app/reference/H6.json"

REQUEST_SLEEP_SEC = 1.0
REQUEST_TIMEOUT_SEC = 120
MAX_RETRIES = 3


def load_key() -> str:
    return json.loads(KEYS_PATH.read_text())["primary_key"]


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def fetch_trade(key: str, cmd_code: str, flow_code: str, period: str) -> list[dict]:
    params = {
        "cmdCode": cmd_code,
        "flowCode": flow_code,
        "partnerCode": 0,
        "period": period,
    }
    headers = {"Ocp-Apim-Subscription-Key": key}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(BASE_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SEC)
            if r.status_code == 429:
                wait = 30 * attempt
                print(f"  429 rate limited, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json().get("data", [])
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            print(f"  attempt {attempt} failed: {e}; retrying in 10s", flush=True)
            time.sleep(10)
    return []


def fetch_reporters() -> list[dict]:
    r = requests.get(REF_REPORTERS_URL, timeout=60)
    r.raise_for_status()
    return r.json()["results"]


def fetch_hs_codes() -> list[dict]:
    r = requests.get(REF_H6_URL, timeout=60)
    r.raise_for_status()
    return r.json()["results"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Fetch only the first period")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, don't call API")
    args = parser.parse_args()

    key = load_key()
    config = load_config()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    hs_codes = config["hs_codes"]
    flows = config["flows"]
    periods = config["periods"][:1] if args.quick else config["periods"]

    plan = [(c, f, p) for c in hs_codes for f in flows for p in periods]
    print(f"Plan: {len(hs_codes)} HS x {len(flows)} flows x {len(periods)} periods = {len(plan)} calls")
    print(f"Estimated time: ~{len(plan) * 20 / 60:.1f} min at 20s/call")

    if args.dry_run:
        for c, f, p in plan[:5]:
            print(f"  would fetch HS={c} flow={f} period={p}")
        if len(plan) > 5:
            print(f"  ... and {len(plan) - 5} more")
        return

    fetched_at = datetime.now(timezone.utc).isoformat()
    all_rows: list[dict] = []
    failures: list[tuple] = []

    for i, (cmd, flow, period) in enumerate(plan, 1):
        print(f"[{i}/{len(plan)}] HS={cmd} flow={flow} period={period}", flush=True)
        try:
            rows = fetch_trade(key, cmd, flow, period)
        except requests.RequestException as e:
            print(f"  FAIL: {e}", flush=True)
            failures.append((cmd, flow, period, str(e)))
            continue
        for row in rows:
            row["_fetched_at"] = fetched_at
        all_rows.extend(rows)
        print(f"  -> {len(rows)} rows", flush=True)
        time.sleep(REQUEST_SLEEP_SEC)

    if not all_rows:
        print("No data collected", file=sys.stderr)
        sys.exit(1)

    df = pd.DataFrame(all_rows)
    stamp = datetime.now().strftime("%Y%m%d")
    suffix = "_quick" if args.quick else ""
    out_path = DATA_DIR / f"trade_{stamp}{suffix}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(df)} rows to {out_path}")

    print("Fetching M49 reporter reference...")
    reporters = fetch_reporters()
    ref_path = DATA_DIR / "ref_reporters.json"
    ref_path.write_text(json.dumps(reporters, ensure_ascii=False, indent=2))
    print(f"Wrote {len(reporters)} reporters to {ref_path}")

    print("Fetching H6 HS code reference...")
    hs_ref = fetch_hs_codes()
    hs_path = DATA_DIR / "ref_hs.json"
    hs_path.write_text(json.dumps(hs_ref, ensure_ascii=False, indent=2))
    print(f"Wrote {len(hs_ref)} HS entries to {hs_path}")

    if failures:
        print(f"\n{len(failures)} failures:")
        for f in failures:
            print(f"  {f}")


if __name__ == "__main__":
    main()
