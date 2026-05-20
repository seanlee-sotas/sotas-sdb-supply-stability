"""Compile a seed CAS list from existing in-repo sources + LLM-generated industrial list.

Seeds (deduplicated by normalised CAS):
- app/materials.yml (current pinned 17 — known scope)
- data/echa/svhc_*.parquet (~201 EU SVHC list — regulation-driven)
- data/regulations/pops_*.parquet (~37 Stockholm POPs)
- Anthropic API call: generate ~500 major industrial chemicals across categories

Output: data/chemicals/chemicals_seed.parquet
  Columns: cas, name_en (best-effort), category_seed, source_tags

This is the input to chemicals/pubchem_ingest.py which fetches structured metadata
for each CAS from PubChem.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import yaml
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "chemicals"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CAS_RE = re.compile(r"^\d{1,7}-\d{2}-\d$")


def normalise_cas(s) -> str | None:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).strip()
    if CAS_RE.match(s):
        return s
    return None


def from_materials_yml() -> list[dict]:
    p = ROOT / "app" / "materials.yml"
    rows = []
    if not p.exists():
        return rows
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    for m in data.get("materials", []):
        cas = normalise_cas(m.get("cas"))
        if not cas:
            continue
        rows.append({
            "cas": cas,
            "name_en": m.get("name_en") or m.get("name_ja") or "",
            "category_seed": m.get("category") or "scope",
            "source_tags": "materials_yml",
        })
    return rows


def from_svhc() -> list[dict]:
    p = sorted((ROOT / "data" / "echa").glob("svhc_*.parquet"))
    if not p:
        return []
    con = duckdb.connect()
    df = con.execute(f"SELECT cas_number, substance_name FROM '{p[-1]}'").df()
    rows = []
    for _, r in df.iterrows():
        cas = normalise_cas(r["cas_number"])
        if not cas:
            continue
        rows.append({
            "cas": cas,
            "name_en": str(r["substance_name"])[:200] if r["substance_name"] else "",
            "category_seed": "svhc",
            "source_tags": "echa_svhc",
        })
    return rows


def from_pops() -> list[dict]:
    p = sorted((ROOT / "data" / "regulations").glob("pops_*.parquet"))
    if not p:
        return []
    con = duckdb.connect()
    df = con.execute(f"SELECT cas, name_en FROM '{p[-1]}'").df()
    rows = []
    for _, r in df.iterrows():
        cas = normalise_cas(r["cas"])
        if not cas:
            continue
        rows.append({
            "cas": cas,
            "name_en": str(r["name_en"])[:200] if r["name_en"] else "",
            "category_seed": "pop",
            "source_tags": "stockholm_pops",
        })
    return rows


def from_curated_json() -> list[dict]:
    p = Path(__file__).parent / "seed_curated.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = []
    for c in data.get("chemicals", []):
        if c.get("category") == "_dup":
            continue  # duplicate markers
        cas = normalise_cas(c.get("cas"))
        if not cas:
            continue
        rows.append({
            "cas": cas,
            "name_en": (c.get("name_en") or "")[:200],
            "category_seed": c.get("category") or "other",
            "source_tags": "curated",
        })
    return rows


def main():
    print("Compiling seed CAS list...")
    all_rows: list[dict] = []
    all_rows.extend(from_materials_yml())
    print(f"  materials.yml: {len(all_rows)} CAS")
    n0 = len(all_rows)
    all_rows.extend(from_svhc())
    print(f"  + ECHA SVHC: {len(all_rows) - n0} CAS (total {len(all_rows)})")
    n0 = len(all_rows)
    all_rows.extend(from_pops())
    print(f"  + POPs: {len(all_rows) - n0} CAS (total {len(all_rows)})")
    n0 = len(all_rows)
    all_rows.extend(from_curated_json())
    print(f"  + curated JSON: {len(all_rows) - n0} CAS (total {len(all_rows)})")

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("No CAS collected, abort"); return
    # Dedupe by CAS, merging source_tags
    df = (
        df.groupby("cas", as_index=False)
        .agg({
            "name_en": "first",
            "category_seed": "first",
            "source_tags": lambda s: ";".join(sorted(set(s))),
        })
    )
    df["fetched_at"] = datetime.now(timezone.utc).isoformat()

    out = OUT_DIR / "chemicals_seed.parquet"
    df.to_parquet(out, index=False)
    print(f"\nWrote {out}: {len(df)} unique CAS")
    print("\nBy category_seed:")
    print(df["category_seed"].value_counts())


if __name__ == "__main__":
    main()
