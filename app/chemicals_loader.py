"""Universal chemicals registry loader for the dashboard.

Merges:
- data/chemicals/chemicals.parquet       (469 chemicals, CAS-keyed master)
- data/chemicals/chemicals_hs_map.parquet (CAS → HS6/chapter, 1:N)
- app/materials_scope.yml                 (pinned subset + per-CAS extras for axis 6/7)

Exposes a single Chemical dataclass-like dict shape consumed by main.py.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CHEM_DIR = ROOT / "data" / "chemicals"
CHEM_P = CHEM_DIR / "chemicals.parquet"
HS_MAP_P = CHEM_DIR / "chemicals_hs_map.parquet"
SCOPE_P = Path(__file__).resolve().parent / "materials_scope.yml"
LEGACY_MATERIALS_P = Path(__file__).resolve().parent / "materials.yml"


@lru_cache(maxsize=1)
def _scope_yaml() -> dict:
    if not SCOPE_P.exists():
        return {"pinned": [], "industries": {}, "categories": []}
    return yaml.safe_load(SCOPE_P.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=1)
def _legacy_materials_by_cas() -> dict[str, dict]:
    """Index legacy materials.yml by CAS for SEC tickers / WB commodity / capacity_keywords."""
    if not LEGACY_MATERIALS_P.exists():
        return {}
    data = yaml.safe_load(LEGACY_MATERIALS_P.read_text(encoding="utf-8")) or {}
    out: dict[str, dict] = {}
    for m in data.get("materials", []):
        cas = m.get("cas")
        if cas:
            out[cas] = m
    return out


@lru_cache(maxsize=1)
def _chemicals_df() -> pd.DataFrame:
    if not CHEM_P.exists():
        return pd.DataFrame(columns=[
            "cas", "pubchem_cid", "name_en", "iupac_name",
            "molecular_formula", "molecular_weight", "inchikey", "smiles",
            "synonyms_count", "top_synonym", "category_seed", "category_norm",
            "source_tags", "pubchem_fetch_status",
        ])
    con = duckdb.connect()
    return con.execute(f"SELECT * FROM '{CHEM_P}'").df()


@lru_cache(maxsize=1)
def _hs_map_df() -> pd.DataFrame:
    if not HS_MAP_P.exists():
        return pd.DataFrame(columns=["cas", "hs6", "hs_chapter", "hs_label", "confidence", "source"])
    con = duckdb.connect()
    return con.execute(f"SELECT * FROM '{HS_MAP_P}'").df()


@lru_cache(maxsize=1)
def _pinned_cas_set() -> set[str]:
    return {p["cas"] for p in (_scope_yaml().get("pinned") or []) if p.get("cas")}


def all_chemicals() -> pd.DataFrame:
    """Return the full chemicals registry with `is_pinned` flag + japanese category label.

    Used to populate the searchable selectbox.
    """
    df = _chemicals_df().copy()
    pinned = _pinned_cas_set()
    df["is_pinned"] = df["cas"].isin(pinned)

    # Map category id → JA label
    cat_meta = {c["id"]: c for c in (_scope_yaml().get("categories") or [])}
    df["category_label_ja"] = df["category_norm"].map(
        lambda c: cat_meta.get(c, {}).get("name_ja", c) if c else "—"
    )
    df["category_sort"] = df["category_norm"].map(
        lambda c: cat_meta.get(c, {}).get("sort", 999) if c else 999
    )
    # Sort: pinned first, then by category sort, then by name
    df["_display_name"] = df["name_en"].fillna(df["top_synonym"]).fillna(df["iupac_name"]).fillna(df["cas"])
    df = df.sort_values(
        ["is_pinned", "category_sort", "_display_name"],
        ascending=[False, True, True],
    ).reset_index(drop=True)
    return df


def get_chemical(cas: str) -> dict | None:
    """Return a denormalised view of a single chemical, merging all sources."""
    df = _chemicals_df()
    matches = df[df["cas"] == cas]
    if matches.empty:
        return None
    row = matches.iloc[0].to_dict()

    # Add HS mappings
    hs_df = _hs_map_df()
    hs_rows = hs_df[hs_df["cas"] == cas]
    row["hs6_exact"] = [h for h in hs_rows[hs_rows["hs6"].notna()]["hs6"].tolist()]
    row["hs_chapters"] = sorted(set(hs_rows["hs_chapter"].dropna().tolist()))

    # Add pinned metadata (note + legacy supplementary tickers / wb_commodity)
    legacy = _legacy_materials_by_cas().get(cas, {})
    row["sec_tickers"] = legacy.get("sec_tickers") or []
    row["wb_commodity"] = legacy.get("wb_commodity")
    row["capacity_keywords"] = legacy.get("capacity_keywords") or []
    row["name_ja_legacy"] = legacy.get("name_ja")

    pinned_meta = next(
        (p for p in (_scope_yaml().get("pinned") or []) if p.get("cas") == cas),
        None,
    )
    row["pinned_note"] = pinned_meta.get("note") if pinned_meta else None
    row["is_pinned"] = pinned_meta is not None

    # Display name: prefer legacy JA name, else top_synonym, else name_en
    row["display_name"] = (
        row.get("name_ja_legacy")
        or row.get("name_en")
        or row.get("top_synonym")
        or row.get("iupac_name")
        or cas
    )
    return row


def industries() -> dict[str, dict]:
    return _scope_yaml().get("industries") or {}


def categories() -> list[dict]:
    return sorted(
        _scope_yaml().get("categories") or [],
        key=lambda c: c.get("sort", 999),
    )


def synonyms_for_search(cas: str) -> list[str]:
    """Best-effort synonym list for EDINET keyword search.

    Combines:
    - Legacy materials.yml capacity_keywords (curated JA)
    - chemicals.parquet name_en + top_synonym
    """
    legacy = _legacy_materials_by_cas().get(cas, {})
    chem = get_chemical(cas)
    out: list[str] = []
    out.extend(legacy.get("capacity_keywords") or [])
    if chem:
        for k in ("name_en", "top_synonym", "iupac_name"):
            v = chem.get(k)
            if v and v not in out:
                out.append(v)
    return out
