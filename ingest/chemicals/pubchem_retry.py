"""Retry PubChem lookup for the 62 entries that failed CAS-based lookup.

Strategies (in order, first success wins):
1. Lookup by `name_en` (cleaned)
2. Lookup by simplified polymer name (e.g., "Nylon 6" → "polycaprolactam")
3. PubChem Substance API (some regulated SVHC live there, not in Compound)
4. Last resort: keep the row with status 'no_pubchem_record' (deliberate, not a bug)

Output: overwrites the failed rows in data/chemicals/chemicals.parquet in place.
"""
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
CHEM_P = ROOT / "data" / "chemicals" / "chemicals.parquet"

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
UA = "sotas-sdb-supply-stability/1.0 (research; sean@sotas.co.jp)"
SESS = requests.Session()
SESS.headers["User-Agent"] = UA
PROPS = "IUPACName,InChIKey,ConnectivitySMILES,MolecularFormula,MolecularWeight"

# Polymer CAS → cleaner lookup name (PubChem typically lists by monomer or simplified)
POLYMER_ALIASES = {
    "9002-88-4": "polyethylene",
    "9003-07-0": "polypropylene",
    "9003-53-6": "polystyrene",
    "9002-86-2": "polyvinyl chloride",
    "25038-59-9": "polyethylene terephthalate",
    "9011-14-7": "polymethyl methacrylate",
    "25037-45-0": "polycarbonate",
    "9003-56-9": "ABS resin",
    "9006-04-6": "natural rubber",
    "9003-55-8": "styrene butadiene rubber",
    "9003-17-2": "polybutadiene",
    "9003-18-3": "nitrile rubber",
    "25038-36-2": "EPDM rubber",
    "9010-98-4": "polychloroprene",
    "63148-62-9": "polydimethylsiloxane",
    "9002-89-5": "polyvinyl alcohol",
    "25038-54-4": "polycaprolactam",
    "32131-17-2": "polyhexamethylene adipamide",
    "24937-79-9": "polyvinylidene fluoride",
    "9002-84-0": "polytetrafluoroethylene",
    "29658-26-2": "polyetheretherketone",
    "26022-09-3": "polyoxymethylene",
    "9035-69-2": "polyphenylene sulfide",
    "26009-03-0": "polylactic acid",
    "9038-95-3": "polypropylene oxide",
    "9016-87-9": "polymeric MDI",
    "25068-38-6": "epoxy resin",
    "9003-08-1": "melamine formaldehyde",
    "25322-68-3": "polyethylene glycol",
    "25322-69-4": "polypropylene glycol",
    "26586-90-7": "polyacrylamide",
    "9003-01-4": "polyacrylic acid",
    "25085-50-1": "styrene maleic anhydride copolymer",
    "9011-04-5": "carboxymethyl cellulose",
    "9004-32-4": "sodium carboxymethyl cellulose",
    "9004-34-6": "cellulose",
    "9000-30-0": "guar gum",
    "9012-76-4": "chitosan",
    "9050-36-6": "maltodextrin",
    # Regulated / mixtures that have a simpler equivalent
    "1336-36-3": "polychlorinated biphenyls",
    "36355-01-8": "hexabromobiphenyl",
    "70776-03-3": "polychlorinated naphthalenes",
    "5120-73-0": "polychlorinated dibenzofurans",
    "85535-84-8": "chlorinated paraffin C10-13",
    "85535-85-9": "chlorinated paraffin C14-17",
    "61788-32-7": "hydrogenated terphenyl",
    # Simple ones (PubChem-CAS resolution glitch)
    "1317-65-3": "calcium carbonate",
    "12042-91-0": "aluminum chlorohydrate",
    "1310-93-6": "trichlorosilane",
    "1330-20-7": "xylene",
    "11102-15-5": "indium tin oxide",
    "9000-90-2": "alpha amylase",
    "9002-93-1": "triton x-100",
    "26780-96-1": "polymerized trimethyl dihydroquinoline",
    "7632-04-4": "sodium perborate",
}


def lookup_cid_by_name(name: str) -> int | None:
    try:
        r = SESS.get(f"{BASE}/compound/name/{name}/cids/JSON", timeout=15)
        if r.status_code == 200:
            cids = r.json().get("IdentifierList", {}).get("CID", [])
            if cids:
                return int(cids[0])
    except requests.exceptions.RequestException:
        pass
    return None


def lookup_sid_substance(name: str) -> int | None:
    """Substance DB sometimes has entries Compound DB lacks."""
    try:
        r = SESS.get(f"{BASE}/substance/name/{name}/sids/JSON", timeout=15)
        if r.status_code == 200:
            sids = r.json().get("IdentifierList", {}).get("SID", [])
            if sids:
                return int(sids[0])
    except requests.exceptions.RequestException:
        pass
    return None


def fetch_props(cid: int) -> dict | None:
    try:
        r = SESS.get(f"{BASE}/compound/cid/{cid}/property/{PROPS}/JSON", timeout=15)
        if r.status_code == 200:
            return r.json()["PropertyTable"]["Properties"][0]
    except (requests.exceptions.RequestException, KeyError, IndexError):
        pass
    return None


def fetch_synonyms(cid: int) -> list[str]:
    try:
        r = SESS.get(f"{BASE}/compound/cid/{cid}/synonyms/JSON", timeout=15)
        if r.status_code == 200:
            return r.json()["InformationList"]["Information"][0].get("Synonym", [])
    except (requests.exceptions.RequestException, KeyError, IndexError):
        pass
    return []


def retry_one(row: pd.Series) -> dict:
    """Try multiple strategies; return updated row dict (preserves all input fields)."""
    cas = row["cas"]
    name_en = (row.get("name_en") or "").strip()

    attempts: list[tuple[str, str]] = []

    # Strategy 1: clean name_en (strip parenthetical content)
    clean_name = re.sub(r"\s*\(.*?\)\s*", " ", name_en).strip() if name_en else ""
    if clean_name and clean_name.lower() != cas.lower():
        attempts.append(("name_clean", clean_name))
    # Strategy 2: polymer alias
    if cas in POLYMER_ALIASES:
        attempts.append(("polymer_alias", POLYMER_ALIASES[cas]))
    # Strategy 3: first word of name_en (e.g., "Polyethylene")
    if name_en:
        first_word = name_en.split()[0]
        if len(first_word) > 4 and first_word not in [a[1] for a in attempts]:
            attempts.append(("first_word", first_word.lower()))

    for strat, name in attempts:
        time.sleep(0.25)  # rate limit
        cid = lookup_cid_by_name(name)
        if cid:
            props = fetch_props(cid)
            if props:
                row = row.copy()
                row["pubchem_cid"] = int(cid)
                row["iupac_name"] = props.get("IUPACName")
                row["molecular_formula"] = props.get("MolecularFormula")
                mw = props.get("MolecularWeight")
                try:
                    row["molecular_weight"] = float(mw) if mw else None
                except (ValueError, TypeError):
                    row["molecular_weight"] = None
                row["inchikey"] = props.get("InChIKey")
                row["smiles"] = props.get("ConnectivitySMILES")
                syns = fetch_synonyms(cid)
                row["synonyms_count"] = len(syns)
                short = [s for s in syns if len(s) <= 40 and not s.replace("-", "").isdigit()]
                row["top_synonym"] = short[0] if short else (syns[0] if syns else None)
                row["pubchem_fetch_status"] = f"ok_via_{strat}"
                row["fetched_at"] = datetime.now(timezone.utc).isoformat()
                return row.to_dict()

    # Strategy 4: substance DB (lighter — just record SID for traceability)
    for strat, name in attempts[:1]:
        time.sleep(0.25)
        sid = lookup_sid_substance(name)
        if sid:
            row = row.copy()
            row["pubchem_fetch_status"] = f"substance_only_sid_{sid}"
            row["fetched_at"] = datetime.now(timezone.utc).isoformat()
            return row.to_dict()

    # Final: explicit no-record marker
    row = row.copy()
    row["pubchem_fetch_status"] = "no_pubchem_record"
    row["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return row.to_dict()


def main():
    if not CHEM_P.exists():
        print(f"Missing {CHEM_P}"); sys.exit(1)
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM '{CHEM_P}'").df()
    failed = df[~df["pubchem_fetch_status"].str.startswith("ok", na=False)].copy()
    print(f"Retry candidates: {len(failed)}")

    updated_map: dict[str, dict] = {}
    for i, (_, row) in enumerate(failed.iterrows()):
        result = retry_one(row)
        updated_map[result["cas"]] = result
        if (i + 1) % 10 == 0 or (i + 1) == len(failed):
            print(f"  [{i+1}/{len(failed)}] {result['cas']} → {result['pubchem_fetch_status']}")

    # Merge back
    def update_row(r):
        c = r["cas"]
        if c in updated_map:
            return pd.Series(updated_map[c])
        return r
    df = df.apply(update_row, axis=1)
    df.to_parquet(CHEM_P, index=False)

    print()
    print("Updated status distribution:")
    print(df["pubchem_fetch_status"].value_counts())


if __name__ == "__main__":
    main()
