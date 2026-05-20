"""Fetch ECHA SVHC (Substances of Very High Concern) Candidate List → Parquet.

Source: https://echa.europa.eu/candidate-list-table
Output: data/echa/svhc_YYYYMMDD.parquet

Feeds Axis 5 (政策・規制リスク) of the SDB supply-stability dashboard.
"""
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "echa"
URL = "https://echa.europa.eu/candidate-list-table"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
PARAMS = {
    "p_p_id": "disslists_WAR_disslistsportlet",
    "p_p_lifecycle": "0",
    "_disslists_WAR_disslistsportlet_delta": "1000",
    "_disslists_WAR_disslistsportlet_keywords": "",
    "_disslists_WAR_disslistsportlet_advancedSearch": "false",
    "_disslists_WAR_disslistsportlet_andOperator": "true",
}


def fetch_svhc() -> pd.DataFrame:
    r = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=60)
    r.raise_for_status()
    tables = pd.read_html(StringIO(r.text))
    target = max(tables, key=lambda t: t.shape[0])
    target = target.rename(
        columns={
            "Substance name": "substance_name",
            "EC No.": "ec_number",
            "CAS No.": "cas_number",
            "Date of inclusion": "date_of_inclusion",
            "Reason for inclusion": "reason",
            "Decision": "decision_id",
        }
    )
    keep = ["substance_name", "ec_number", "cas_number", "date_of_inclusion", "reason", "decision_id"]
    target = target[[c for c in keep if c in target.columns]].copy()
    target["date_of_inclusion"] = pd.to_datetime(target["date_of_inclusion"], format="%d-%b-%Y", errors="coerce")
    target["_fetched_at"] = datetime.now(timezone.utc).isoformat()
    target["_source"] = "ECHA SVHC Candidate List"
    return target


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fetching ECHA SVHC list from {URL}")
    df = fetch_svhc()
    print(f"Got {len(df)} SVHC entries")

    stamp = datetime.now().strftime("%Y%m%d")
    out_path = DATA_DIR / f"svhc_{stamp}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"Wrote {out_path}")

    with_cas = df[df["cas_number"].notna() & (df["cas_number"] != "-")]
    print(f"  with CAS: {len(with_cas)}")
    print(f"  unique reasons: {df['reason'].nunique()}")
    print("\nTop reasons:")
    print(df["reason"].value_counts().head(5).to_string())


if __name__ == "__main__":
    main()
