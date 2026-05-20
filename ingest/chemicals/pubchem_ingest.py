"""For each CAS in chemicals_seed.parquet, fetch PubChem CID and structured properties.

PubChem REST API (no auth, ~5 req/sec per IP):
- /compound/name/{CAS}/cids/JSON     → CID lookup by CAS
- /compound/cid/{CID}/property/...    → structural properties
- /compound/cid/{CID}/synonyms/JSON   → English synonyms (Japanese rare)

Output: data/chemicals/chemicals.parquet
  Columns: cas, pubchem_cid, name_en, iupac_name, molecular_formula,
           molecular_weight, inchikey, smiles, synonyms_count, top_synonym,
           category_seed, source_tags, pubchem_fetch_status, fetched_at

Re-run is idempotent: existing rows are kept; only new/failed CAS are re-fetched.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
CHEM_DIR = ROOT / "data" / "chemicals"
SEED_P = CHEM_DIR / "chemicals_seed.parquet"
OUT_P = CHEM_DIR / "chemicals.parquet"

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
UA = "sotas-sdb-supply-stability/1.0 (research; sean@sotas.co.jp)"
SESS = requests.Session()
SESS.headers["User-Agent"] = UA

PROPS = "IUPACName,InChIKey,ConnectivitySMILES,MolecularFormula,MolecularWeight"
RATE_LIMIT_PER_SEC = 4.5  # under 5/s ceiling


def throttle(last_ts: float) -> float:
    elapsed = time.time() - last_ts
    min_gap = 1.0 / RATE_LIMIT_PER_SEC
    if elapsed < min_gap:
        time.sleep(min_gap - elapsed)
    return time.time()


def lookup_cid(cas: str, last_ts: float) -> tuple[int | None, float, str]:
    last_ts = throttle(last_ts)
    try:
        r = SESS.get(f"{BASE}/compound/name/{cas}/cids/JSON", timeout=15)
    except requests.exceptions.RequestException as e:
        return None, last_ts, f"network_error:{e.__class__.__name__}"
    if r.status_code == 404:
        return None, last_ts, "cid_not_found"
    if r.status_code == 503:
        return None, last_ts, "service_unavailable"
    if r.status_code != 200:
        return None, last_ts, f"http_{r.status_code}"
    try:
        data = r.json()
        cids = data.get("IdentifierList", {}).get("CID", [])
        if not cids:
            return None, last_ts, "no_cid_in_response"
        return cids[0], last_ts, "ok"
    except Exception as e:
        return None, last_ts, f"parse_error:{e.__class__.__name__}"


def fetch_props(cid: int, last_ts: float) -> tuple[dict | None, float, str]:
    last_ts = throttle(last_ts)
    try:
        r = SESS.get(f"{BASE}/compound/cid/{cid}/property/{PROPS}/JSON", timeout=15)
    except requests.exceptions.RequestException as e:
        return None, last_ts, f"network_error:{e.__class__.__name__}"
    if r.status_code != 200:
        return None, last_ts, f"http_{r.status_code}"
    try:
        props = r.json()["PropertyTable"]["Properties"][0]
        return props, last_ts, "ok"
    except Exception as e:
        return None, last_ts, f"parse_error:{e.__class__.__name__}"


def fetch_synonyms(cid: int, last_ts: float) -> tuple[list[str], float, str]:
    last_ts = throttle(last_ts)
    try:
        r = SESS.get(f"{BASE}/compound/cid/{cid}/synonyms/JSON", timeout=15)
    except requests.exceptions.RequestException as e:
        return [], last_ts, f"network_error:{e.__class__.__name__}"
    if r.status_code != 200:
        return [], last_ts, f"http_{r.status_code}"
    try:
        syns = r.json()["InformationList"]["Information"][0].get("Synonym", [])
        return syns, last_ts, "ok"
    except Exception:
        return [], last_ts, "no_synonyms"


def fetch_one(cas: str, last_ts: float) -> tuple[dict, float]:
    """Fetch full record for one CAS. Returns (row_dict, last_ts)."""
    row = {
        "cas": cas, "pubchem_cid": None, "iupac_name": None,
        "molecular_formula": None, "molecular_weight": None,
        "inchikey": None, "smiles": None, "synonyms_count": 0,
        "top_synonym": None, "pubchem_fetch_status": "pending",
    }
    cid, last_ts, st = lookup_cid(cas, last_ts)
    if cid is None:
        row["pubchem_fetch_status"] = f"cid_lookup:{st}"
        return row, last_ts
    row["pubchem_cid"] = int(cid)
    props, last_ts, st = fetch_props(cid, last_ts)
    if props is None:
        row["pubchem_fetch_status"] = f"props:{st}"
        return row, last_ts
    row["iupac_name"] = props.get("IUPACName")
    row["molecular_formula"] = props.get("MolecularFormula")
    mw = props.get("MolecularWeight")
    try:
        row["molecular_weight"] = float(mw) if mw is not None else None
    except (ValueError, TypeError):
        row["molecular_weight"] = None
    row["inchikey"] = props.get("InChIKey")
    row["smiles"] = props.get("ConnectivitySMILES") or props.get("CanonicalSMILES")
    syns, last_ts, _ = fetch_synonyms(cid, last_ts)
    row["synonyms_count"] = len(syns)
    # Pick a shorter, more common synonym as top (CAS-format strings filtered out)
    short_syns = [s for s in syns if len(s) <= 40 and not s.replace("-", "").isdigit()]
    row["top_synonym"] = short_syns[0] if short_syns else (syns[0] if syns else None)
    row["pubchem_fetch_status"] = "ok"
    return row, last_ts


def main():
    if not SEED_P.exists():
        print(f"Missing {SEED_P}. Run seed_compile.py first."); sys.exit(1)

    con = duckdb.connect()
    seed = con.execute(f"SELECT * FROM '{SEED_P}'").df()
    print(f"Loaded {len(seed)} seed CAS")

    # Resume support: read existing chemicals.parquet, skip already-fetched OK rows
    already = {}
    if OUT_P.exists():
        prev = con.execute(f"SELECT * FROM '{OUT_P}'").df()
        for _, r in prev.iterrows():
            if r["pubchem_fetch_status"] == "ok":
                already[r["cas"]] = r.to_dict()
        print(f"Resume: {len(already)} already fetched, skipping")

    todo_seed = seed[~seed["cas"].isin(already.keys())].reset_index(drop=True)
    print(f"To fetch: {len(todo_seed)}")

    results: list[dict] = list(already.values())
    last_ts = 0.0
    t0 = time.time()
    for i, sr in todo_seed.iterrows():
        cas = sr["cas"]
        row, last_ts = fetch_one(cas, last_ts)
        # Merge seed metadata
        row["name_en"] = sr.get("name_en") or row.get("top_synonym") or row.get("iupac_name") or ""
        row["category_seed"] = sr.get("category_seed", "other")
        row["source_tags"] = sr.get("source_tags", "")
        row["fetched_at"] = datetime.now(timezone.utc).isoformat()
        results.append(row)
        if (i + 1) % 25 == 0 or (i + 1) == len(todo_seed):
            rate = (i + 1) / (time.time() - t0)
            print(f"  [{i+1}/{len(todo_seed)}] {cas} → {row['pubchem_fetch_status']} ({rate:.1f}/s)")
        # Periodic flush every 100
        if (i + 1) % 100 == 0:
            df = pd.DataFrame(results)
            df.to_parquet(OUT_P, index=False)

    df = pd.DataFrame(results)
    # Stable column order
    cols = ["cas", "pubchem_cid", "name_en", "iupac_name", "molecular_formula",
            "molecular_weight", "inchikey", "smiles", "synonyms_count", "top_synonym",
            "category_seed", "source_tags", "pubchem_fetch_status", "fetched_at"]
    df = df[[c for c in cols if c in df.columns]]
    df.to_parquet(OUT_P, index=False)
    print(f"\nWrote {OUT_P}: {len(df)} rows")
    print("\nFetch status:")
    print(df["pubchem_fetch_status"].value_counts())
    print("\nBy category_seed:")
    print(df["category_seed"].value_counts())


if __name__ == "__main__":
    main()
