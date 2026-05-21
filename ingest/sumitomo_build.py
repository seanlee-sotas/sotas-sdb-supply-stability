"""Build Sumitomo materials parquet from YAML + chemicals.parquet + hs_map.parquet.

Output: data/sumitomo/materials.parquet (one row per material, flattened citations)
        data/sumitomo/citations.parquet (one row per citation, foreign key = material id)
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parent.parent
YAML_PATH = REPO / "app" / "sumitomo_materials.yml"
OUT_DIR = REPO / "data" / "sumitomo"
CHEM_PATH = REPO / "data" / "chemicals" / "chemicals.parquet"
HS_PATH = REPO / "data" / "chemicals" / "chemicals_hs_map.parquet"
COMPANY_PATH = REPO / "data" / "chemicals" / "chemicals_company_map.parquet"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with YAML_PATH.open() as f:
        doc = yaml.safe_load(f)

    materials = doc["materials"]
    segments = doc["business_segments"]
    layers = doc["evidence_layers"]

    chem = pd.read_parquet(CHEM_PATH)
    hs = pd.read_parquet(HS_PATH)
    company = pd.read_parquet(COMPANY_PATH)

    chem_idx = chem.set_index("cas")
    hs_idx = hs.set_index("cas")
    company_idx = company.set_index("cas")

    rows = []
    citations_rows = []

    for m in materials:
        cas = m.get("cas")
        is_pseudo_cas = False
        if not cas:
            # Pseudo CAS scheme matches ingest/sumitomo_data_expand._pseudo_cas
            cas = f"SR-{m['id'].upper().replace('_', '-')[:48]}"
            is_pseudo_cas = True
        chem_row = chem_idx.loc[cas].to_dict() if cas and cas in chem_idx.index else {}

        hs6 = m.get("hs6_override")
        hs_label = None
        if not hs6 and cas and cas in hs_idx.index:
            sub = hs.loc[hs["cas"] == cas]
            if len(sub):
                hs6 = sub.iloc[0]["hs6"]
                hs_label = sub.iloc[0]["hs_label"]

        has_company = bool(cas and cas in company_idx.index)

        row = {
            "id": m["id"],
            "cas": cas,
            "is_pseudo_cas": is_pseudo_cas,
            "name_ja": m["name_ja"],
            "name_en": m.get("name_en"),
            "aliases": json.dumps(m.get("aliases", []), ensure_ascii=False),
            "status": m["status"],
            "primary_segment": m["primary_segment"],
            "segments": json.dumps(m.get("segments", []), ensure_ascii=False),
            "usage_note": m.get("usage_note"),
            "evidence_layer": m["evidence_layer"],
            "evidence_layer_label": layers[m["evidence_layer"]]["label"],
            "evidence_layer_color": layers[m["evidence_layer"]]["color"],
            "risk_tags": json.dumps(m.get("risk_tags", []), ensure_ascii=False),
            "citation_count": len(m.get("citations", [])),
            # chemicals.parquet からの enrichment
            "pubchem_cid": chem_row.get("pubchem_cid"),
            "iupac_name": chem_row.get("iupac_name"),
            "molecular_formula": chem_row.get("molecular_formula"),
            "molecular_weight": chem_row.get("molecular_weight"),
            "inchikey": chem_row.get("inchikey"),
            "smiles": chem_row.get("smiles"),
            "category_norm": chem_row.get("category_norm"),
            # HS マッピング
            "hs6": hs6,
            "hs_label": hs_label,
            # 既存 supplier_concentration へヒットするか
            "has_jp_supplier_data": has_company,
            "build_ts": datetime.now(timezone.utc).isoformat(),
        }
        rows.append(row)

        for c in m.get("citations", []):
            citations_rows.append({
                "material_id": m["id"],
                "source": c.get("source"),
                "line": c.get("line"),
                "text": c.get("text"),
            })

    df = pd.DataFrame(rows)
    cit = pd.DataFrame(citations_rows)

    materials_out = OUT_DIR / "materials.parquet"
    citations_out = OUT_DIR / "citations.parquet"
    df.to_parquet(materials_out, index=False)
    cit.to_parquet(citations_out, index=False)

    segments_out = OUT_DIR / "segments.json"
    layers_out = OUT_DIR / "layers.json"
    metadata_out = OUT_DIR / "metadata.json"
    with segments_out.open("w") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    with layers_out.open("w") as f:
        json.dump(layers, f, ensure_ascii=False, indent=2)
    with metadata_out.open("w") as f:
        json.dump(doc["metadata"], f, ensure_ascii=False, indent=2)

    print(f"OK: {len(df)} materials, {len(cit)} citations")
    print(f"  pinned: {(df['status']=='pinned').sum()}, watch: {(df['status']=='watch').sum()}")
    print(f"  CAS:   {df['cas'].notna().sum()} / {len(df)}")
    print(f"  HS6:   {df['hs6'].notna().sum()} / {len(df)}")
    print(f"  with chemicals.parquet enrichment: {df['pubchem_cid'].notna().sum()} / {len(df)}")
    print(f"  with JP supplier data:             {df['has_jp_supplier_data'].sum()} / {len(df)}")
    print(f"output: {materials_out}, {citations_out}")


if __name__ == "__main__":
    main()
