"""Collect results from a completed Anthropic Batch and write structured Parquet.

Reads the most recent batch metadata from data/edinet/batches/, polls until ended,
then downloads results and joins back with the original snippet data.

Output: data/edinet/capacity_structured_YYYYMMDD.parquet
  Columns: company, doctype, period, file_path, product, facility,
           capacity_value, capacity_unit, direction, target_year, confidence
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
EDINET_DIR = ROOT / "data" / "edinet"
BATCH_DIR = EDINET_DIR / "batches"


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set"); return
    client = Anthropic()

    metas = sorted(BATCH_DIR.glob("batch_*.json"))
    if not metas:
        print(f"No batch metadata in {BATCH_DIR}"); return
    meta = json.loads(metas[-1].read_text())
    batch_id = meta["batch_id"]
    print(f"Checking batch {batch_id}")

    batch = client.messages.batches.retrieve(batch_id)
    print(f"Status: {batch.processing_status}")
    print(f"  Counts: {batch.request_counts}")

    if batch.processing_status != "ended":
        print("Not ended yet. Try again later.")
        sys.exit(1)

    # Stream results
    print("\nDownloading results...")
    results_by_id: dict[str, dict] = {}
    for result in client.messages.batches.results(batch_id):
        results_by_id[result.custom_id] = result

    print(f"Got {len(results_by_id)} results")

    # Load original snippets
    snippets_p = ROOT / meta["source_parquet"]
    con = duckdb.connect()
    con.execute(f"CREATE VIEW snip AS SELECT row_number() OVER () AS rn, * FROM '{snippets_p}'")
    snip_df = con.execute("SELECT * FROM snip").df()

    rows = []
    parse_failures = 0
    for _, row in snip_df.iterrows():
        cid = f"snippet_{int(row['rn'])}"
        res = results_by_id.get(cid)
        if not res or res.result.type != "succeeded":
            continue
        text = res.result.message.content[0].text
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            parse_failures += 1
            continue
        try:
            payload = json.loads(m.group(0))
        except json.JSONDecodeError:
            parse_failures += 1
            continue
        for item in payload.get("extracted", []):
            rows.append({
                "company": row["company"],
                "doctype": row["doctype"],
                "period": row["period"],
                "file_path": row["file_path"],
                "snippet_id": cid,
                **item,
            })

    print(f"Parsed {len(rows)} structured capacity items ({parse_failures} parse failures)")
    if not rows:
        print("No structured rows extracted."); return

    df = pd.DataFrame(rows)
    df["_processed_at"] = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now().strftime("%Y%m%d")
    out = EDINET_DIR / f"capacity_structured_{stamp}.parquet"
    df.to_parquet(out, index=False)
    print(f"\nWrote {out}")
    print("\nDirection distribution:")
    print(df["direction"].value_counts())
    print("\nTop 10 products mentioned:")
    print(df["product"].value_counts().head(10))


if __name__ == "__main__":
    main()
