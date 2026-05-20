"""Axis 6 LLM classification — classify SEC 8-K Item 8.01 filings with Claude.

Item 8.01 ("Other Events") is the catch-all bucket where Force Majeure, plant
fires, regulatory updates, cyber incidents, M&A announcements often land.
Without reading the actual document body, item code alone can't tell them apart.

This script:
1. Fetches the 30 most recent Item 8.01 filings from our SEC 8-K dataset
2. Downloads each filing's primary document (HTML)
3. Sends body text to Claude for structured classification
4. Outputs Parquet with event_type, summary_ja, supply_relevance flag

Cost: ~$0.30-0.50 for 30 filings using Sonnet 4.6.
"""
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
SEC_DIR = ROOT / "data" / "sec"
OUT_DIR = ROOT / "data" / "sec"
SEC_HEADERS = {"User-Agent": "Sotas SDB Supply-Stability Research burnoutpapa@gmail.com"}

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are classifying SEC 8-K Item 8.01 ("Other Events") filings from US chemical companies for a supply-stability dashboard.

Output STRICT JSON only, no preamble. Schema:
{
  "event_type": "FORCE_MAJEURE" | "PLANT_INCIDENT" | "PRODUCTION_SUSPENSION" | "STRATEGIC_REVIEW" | "M_AND_A" | "DIVESTITURE" | "REGULATORY_UPDATE" | "LITIGATION" | "FINANCING" | "GUIDANCE_UPDATE" | "DIVIDEND_BUYBACK" | "EXECUTIVE_CHANGE" | "PARTNERSHIP" | "OTHER",
  "summary_ja": "<1文の日本語要約、80字以内>",
  "supply_relevance": "HIGH" | "MED" | "LOW",  // 供給安定性への影響度
  "key_facility": "<施設名 or null>",
  "key_product": "<製品名 or null>"
}

supply_relevance basis:
- HIGH: production halt, FM declaration, plant accident, capacity reduction
- MED: divestiture, strategic review, regulatory delay
- LOW: dividend, executive change, financing, normal M&A"""

USER_TEMPLATE = """Filing date: {date}
Company: {company} ({ticker})

Filing body (truncated):
{body}

Classify this filing per the schema."""


def fetch_filing_text(url: str) -> str:
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=30)
        if r.status_code != 200:
            return ""
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text)
        return text[:8000]
    except Exception:
        return ""


def classify(client: Anthropic, row: dict) -> dict:
    body = fetch_filing_text(row["accession_url"])
    if not body:
        return {"event_type": "FETCH_FAILED", "summary_ja": "", "supply_relevance": "LOW", "key_facility": None, "key_product": None}
    msg = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": USER_TEMPLATE.format(
            date=row["filing_date"], company=row["company_name"], ticker=row["ticker"], body=body,
        )}],
    )
    txt = msg.content[0].text.strip()
    # Try to extract JSON (sometimes wrapped in fences)
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if not m:
        return {"event_type": "PARSE_FAILED", "summary_ja": txt[:80], "supply_relevance": "LOW", "key_facility": None, "key_product": None}
    import json
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"event_type": "PARSE_FAILED", "summary_ja": txt[:80], "supply_relevance": "LOW", "key_facility": None, "key_product": None}


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set"); return
    client = Anthropic()

    sec_files = sorted(SEC_DIR.glob("filings_8k_*.parquet"))
    sec_p = max(sec_files)
    con = duckdb.connect()
    con.execute(f"CREATE VIEW sec AS SELECT * FROM '{sec_p}'")
    df = con.execute(
        """SELECT filing_date, ticker, company_name, items, primary_desc, accession_url, accession
           FROM sec
           WHERE list_has(string_split(items, ','), '8.01')
           ORDER BY filing_date DESC LIMIT 30"""
    ).df()
    print(f"Classifying {len(df)} Item 8.01 filings")

    results = []
    for i, row in df.iterrows():
        print(f"[{i+1}/{len(df)}] {row['filing_date']} {row['ticker']}", flush=True)
        cls = classify(client, row)
        out_row = {**row.to_dict(), **cls, "_classified_at": datetime.now(timezone.utc).isoformat()}
        results.append(out_row)
        time.sleep(0.5)  # gentle on both SEC and Anthropic

    df_out = pd.DataFrame(results)
    stamp = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"item801_classified_{stamp}.parquet"
    df_out.to_parquet(out_path, index=False)
    print(f"\nWrote {len(df_out)} classified rows to {out_path}")
    print("\nEvent type distribution:")
    print(df_out["event_type"].value_counts())
    print("\nSupply relevance distribution:")
    print(df_out["supply_relevance"].value_counts())


if __name__ == "__main__":
    main()
