"""Build chemicals_hs_map.parquet: CAS → HS6 mapping (1:N).

Strategy (no LLM dependency for now):
1. Known exact mappings from app/materials.yml (~30 high-confidence pairs)
2. Category-based default HS chapter (low confidence, useful for filtering by chapter)
3. (Future) LLM-assisted refinement for HS6-level precision

Output: data/chemicals/chemicals_hs_map.parquet
  Columns: cas, hs6, hs_chapter, hs_label, confidence, source

Also normalises chemicals.parquet's category_seed field (JA → EN).
"""
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHEM_DIR = ROOT / "data" / "chemicals"
CHEM_P = CHEM_DIR / "chemicals.parquet"
OUT_P = CHEM_DIR / "chemicals_hs_map.parquet"

# JA → EN category normalisation (legacy from materials.yml)
CATEGORY_NORMALISE = {
    "モノマー": "monomer",
    "プラスチック": "polymer",
    "天然ポリマー": "polymer",
    "合成ゴム": "polymer",
    "ゴム添加剤": "rubber_chemical",
    "充填剤": "filler",
    "scope": "other",
    "svhc": "regulated",  # regulation-driven seeds get a single label
    "pop": "regulated",
}

# Category → default HS chapter (HS2 level, low-confidence)
CATEGORY_TO_HS_CHAPTER = {
    "monomer": "29",  # organic chemicals
    "solvent": "29",
    "polymer": "39",  # plastics (40 for elastomers — refined per case)
    "inorganic": "28",
    "filler": "28",   # mostly mineral fillers; CaCO3 in 25 but assigning 28
    "additive": "38",  # misc chemical products
    "rubber_chemical": "38",  # vulcanisation accelerators in 38.12
    "plasticizer": "39",  # plasticizer formulations Ch 38, but added in plastics
    "battery_material": "29",  # organic carbonates; LiPF6 in 28
    "semiconductor": "28",  # high-purity gases
    "catalyst": "38",
    "fluorochemical": "29",
    "pigment": "32",  # paint/pigment Ch 32
    "surfactant": "34",  # soap/surfactant Ch 34
    "fertilizer": "31",
    "specialty": "29",
    "regulated": None,  # SVHC/POP — chapter varies; require manual mapping
    "other": None,
}

HS_CHAPTER_LABELS = {
    "25": "塩・硫黄・土石類",
    "27": "鉱物性燃料・油・蝋",
    "28": "無機化学品",
    "29": "有機化学品",
    "30": "医療用品",
    "31": "肥料",
    "32": "なめし用・染料・顔料・塗料・インキ",
    "34": "石けん・界面活性剤・蝋・ワックス",
    "38": "各種化学工業生産品",
    "39": "プラスチック",
    "40": "ゴム",
}


def from_materials_yml() -> list[dict]:
    """Pull known (CAS → HS6) pairs from app/materials.yml."""
    p = ROOT / "app" / "materials.yml"
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    rows = []
    for m in data.get("materials", []):
        cas = m.get("cas")
        if not cas:
            continue
        for hs6 in (m.get("hs_codes") or []):
            hs6 = str(hs6).strip().zfill(6)
            rows.append({
                "cas": cas,
                "hs6": hs6,
                "hs_chapter": hs6[:2],
                "hs_label": HS_CHAPTER_LABELS.get(hs6[:2], hs6[:2]),
                "confidence": 0.95,
                "source": "materials_yml",
            })
    return rows


def chapter_defaults_for_chemicals(chem_df: pd.DataFrame) -> list[dict]:
    """Generate low-confidence chapter-level entries for all chemicals."""
    rows = []
    for _, r in chem_df.iterrows():
        cat = r.get("category_norm")
        ch = CATEGORY_TO_HS_CHAPTER.get(cat)
        if not ch:
            continue
        rows.append({
            "cas": r["cas"],
            "hs6": None,  # chapter only
            "hs_chapter": ch,
            "hs_label": HS_CHAPTER_LABELS.get(ch, ch),
            "confidence": 0.30,
            "source": "category_default",
        })
        # Polymers: rubber chemicals overlap with Ch 40 — add as alternate
        if cat == "polymer":
            name = (r.get("name_en") or "").lower()
            if any(kw in name for kw in ["rubber", "elastomer", "sbr", "nbr", "epdm", "butadiene"]):
                rows.append({
                    "cas": r["cas"], "hs6": None, "hs_chapter": "40",
                    "hs_label": HS_CHAPTER_LABELS["40"],
                    "confidence": 0.40, "source": "category_default_rubber",
                })
    return rows


def normalise_chemicals():
    """Add category_norm column to chemicals.parquet (JA→EN), write back."""
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM '{CHEM_P}'").df()
    df["category_norm"] = df["category_seed"].map(lambda c: CATEGORY_NORMALISE.get(c, c))
    df.to_parquet(CHEM_P, index=False)
    print(f"Normalised category_seed → category_norm in {CHEM_P}")
    return df


def main():
    chem_df = normalise_chemicals()

    rows: list[dict] = []
    rows.extend(from_materials_yml())
    print(f"From materials.yml: {len(rows)} exact (CAS→HS6) mappings")
    n0 = len(rows)

    chap_rows = chapter_defaults_for_chemicals(chem_df)
    rows.extend(chap_rows)
    print(f"+ category defaults: {len(rows) - n0} chapter-level entries")

    df = pd.DataFrame(rows)
    if df.empty:
        print("No mappings, abort"); return
    df["created_at"] = datetime.now(timezone.utc).isoformat()
    df.to_parquet(OUT_P, index=False)
    print(f"\nWrote {OUT_P}: {len(df)} mapping rows")
    print(f"  unique CAS with any HS: {df['cas'].nunique()}")
    print(f"  unique CAS with HS6 (exact): {df[df['hs6'].notna()]['cas'].nunique()}")
    print("\nBy source:")
    print(df["source"].value_counts())
    print("\nBy chapter:")
    print(df["hs_chapter"].value_counts())


if __name__ == "__main__":
    main()
