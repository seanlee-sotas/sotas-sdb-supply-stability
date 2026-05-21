"""住友ゴム Mock 用データ拡充スクリプト — タスク1〜6 を一気に実行.

Steps:
  1. sumitomo_overrides.yml を生成 (CAS → wb_commodity / sec_tickers / hs6_extra)
  2. chemicals.parquet に CAS あり 10物質を PubChem fetch + substance-only fallback 追加
  3. chemicals_hs_map.parquet に sumitomo hs6_override 全部マージ
  4. CAS未確定 26物質に pseudo CAS (SR-XXX) を発行、chemicals + hs_map に substance-only 追加
  5. data/supplier/jp_supplier_count_*.parquet を sumitomo CAS で再集計
  6. (軸6) sumitomo_overrides.yml の sec_tickers で chemicals_loader が混ぜる仕組み (別途 patch)

Output:
  app/sumitomo_overrides.yml          — auto-generated CAS-level overrides
  data/chemicals/chemicals.parquet    — 追加更新
  data/chemicals/chemicals_hs_map.parquet — 追加更新
  data/supplier/jp_supplier_count_YYYYMMDD.parquet — 新規生成
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
DATA = ROOT / "data"

YAML_PATH = APP / "sumitomo_materials.yml"
OVERRIDES_PATH = APP / "sumitomo_overrides.yml"
CHEM_PATH = DATA / "chemicals" / "chemicals.parquet"
HS_PATH = DATA / "chemicals" / "chemicals_hs_map.parquet"
SNIPPETS_PATH = DATA / "edinet" / "capacity_snippets_20260520.parquet"
SUPPLIER_DIR = DATA / "supplier"

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
UA = "sotas-sdb-supply-stability/1.0 (research; sean@sotas.co.jp)"
PROPS = "IUPACName,InChIKey,ConnectivitySMILES,MolecularFormula,MolecularWeight"


# -----------------------------------------------------------------------------
# Step 1: overrides.yml の生成 (wb_commodity / sec_tickers / hs6_extra)
# -----------------------------------------------------------------------------

# 物質id → WB商品 / SEC tickers のキュレート表
# tickers = sec_8k.py で取得対象の米化学メジャー 15社のサブセット
WB_AND_SEC_BY_ID: dict[str, dict] = {
    # --- タイヤ基幹 ---
    "nr_natural_rubber":       {"wb": "RUBBER_TSR20", "tickers": ["GT"]},
    "ssbr":                    {"wb": "CRUDE_BRENT", "tickers": ["LYB", "WLK", "CE"]},
    "esbr":                    {"wb": "CRUDE_BRENT", "tickers": ["LYB", "WLK"]},
    "br":                      {"wb": "CRUDE_BRENT", "tickers": ["LYB", "DOW"]},
    "butadiene":               {"wb": "CRUDE_BRENT", "tickers": ["LYB", "DOW", "EMN"]},
    "styrene":                 {"wb": "CRUDE_BRENT", "tickers": ["LYB", "DOW", "CE"]},
    "carbon_black":            {"wb": "CRUDE_BRENT", "tickers": ["ASH", "DOW"]},
    "silica_precipitated":     {"wb": None,          "tickers": ["PPG", "SHW"]},
    "silane_tespt":            {"wb": None,          "tickers": ["DOW"]},
    "sulfur":                  {"wb": None,          "tickers": ["LYB", "OLN"]},
    "zinc_oxide":              {"wb": "Zinc",        "tickers": ["OLN"]},
    "stearic_acid":            {"wb": None,          "tickers": ["EMN"]},
    "cbs_accelerator":         {"wb": None,          "tickers": ["EMN", "LYB"]},
    "tbbs_accelerator":        {"wb": None,          "tickers": ["EMN", "LYB"]},
    "ppd6_antioxidant":        {"wb": None,          "tickers": ["EMN", "LYB"]},
    "tdae_oil":                {"wb": "CRUDE_BRENT", "tickers": ["LYB"]},
    "pet_cord":                {"wb": None,          "tickers": ["EMN"]},
    "nylon66_cord":            {"wb": None,          "tickers": ["DD", "CE"]},
    "rayon_viscose":           {"wb": None,          "tickers": []},
    "aramid_kevlar":           {"wb": None,          "tickers": ["DD"]},
    "steel_cord":              {"wb": None,          "tickers": []},
    "iir_butyl":               {"wb": "CRUDE_BRENT", "tickers": ["LYB", "WLK"]},
    "halobutyl":               {"wb": "CRUDE_BRENT", "tickers": ["LYB"]},
    "tackifier_resin":         {"wb": "CRUDE_BRENT", "tickers": ["EMN"]},
    # --- スポーツ ---
    "ionomer_resin":           {"wb": None,          "tickers": ["DOW"]},
    "tpu_urethane":            {"wb": None,          "tickers": ["DOW", "LYB"]},
    "titanium_alloy":          {"wb": None,          "tickers": []},
    "tungsten":                {"wb": None,          "tickers": []},
    "carbon_fiber":            {"wb": None,          "tickers": []},
    "tennis_ball_felt":        {"wb": "COTTON_A_INDX","tickers": []},
    # --- 産業品 ---
    "bromobutyl":              {"wb": "CRUDE_BRENT", "tickers": ["LYB"]},
    "pdms_silicone":           {"wb": None,          "tickers": ["DOW"]},
    "high_damping_rubber":     {"wb": "RUBBER_TSR20","tickers": []},
    "ldp_natural_rubber_latex":{"wb": "RUBBER_TSR20","tickers": []},
    "artificial_turf_pe":      {"wb": "CRUDE_BRENT", "tickers": ["LYB", "DOW"]},
    "sbr_chip_filler":         {"wb": "CRUDE_BRENT", "tickers": ["LYB"]},
    "oa_conductive_rubber":    {"wb": None,          "tickers": []},
    # --- watch / タイヤ ---
    "recycled_carbon_black":   {"wb": "CRUDE_BRENT", "tickers": ["ASH"]},
    "eudr_compliant_nr":       {"wb": "RUBBER_TSR20","tickers": []},
    "enr_epoxidized_nr":       {"wb": "RUBBER_TSR20","tickers": []},
    "dpnr_high_purity":        {"wb": "RUBBER_TSR20","tickers": []},
    "bio_butadiene":           {"wb": "CRUDE_BRENT", "tickers": ["DOW"]},
    "rpet_cord":               {"wb": None,          "tickers": ["EMN"]},
    "rice_husk_silica":        {"wb": None,          "tickers": []},
    "hydrogen":                {"wb": "NGAS_US",     "tickers": ["APD", "LIN"]},
    "active_tread_water_switch":{"wb": None,          "tickers": []},
    "active_tread_temp_switch": {"wb": None,          "tickers": []},
    "active_tread_third_switch":{"wb": None,          "tickers": []},
    "hsbr_hnbr":               {"wb": "CRUDE_BRENT", "tickers": []},
    "airless_tire_resin":      {"wb": None,          "tickers": []},
    "ev_acoustic_foam":        {"wb": None,          "tickers": ["DOW"]},
    "ppd6_substitute":         {"wb": None,          "tickers": ["EMN", "LYB"]},
    # --- watch / sports ---
    "bio_polyol_corn":         {"wb": None,          "tickers": ["DOW"]},
    "recycled_golf_ball_rubber":{"wb": None,         "tickers": []},
    # --- watch / industrial ---
    "biopharma_low_extract_gasket":{"wb": None,      "tickers": []},
    "ptfe_etfe_film":          {"wb": None,          "tickers": ["CC", "CE"]},
    "new_marine_fender":       {"wb": "RUBBER_TSR20","tickers": []},
    "microplastic_alt_filler": {"wb": None,          "tickers": []},
    # --- watch / new business ---
    "li_s_battery_sulfur":     {"wb": None,          "tickers": ["ALB"]},
    "li_compounds":            {"wb": None,          "tickers": ["ALB"]},
    "graphene":                {"wb": None,          "tickers": []},
    "cancer_cell_polymer":     {"wb": None,          "tickers": []},
    "3d_printer_rubber":       {"wb": None,          "tickers": []},
    "automotive_semiconductor":{"wb": None,          "tickers": []},
}


# CAS未確定物質に発行する pseudo CAS のスキーム
# 形式: "SR-<segment>-<seq>" (Sumitomo Rubber prefix で衝突回避)
def _pseudo_cas(material_id: str) -> str:
    return f"SR-{material_id.upper().replace('_', '-')[:48]}"


# substance-only 物質に推定する HS6 章レベル
# 配合系・複合素材は HS6 完全マッピングは難しいので章レベルのみ
PSEUDO_HS6_HINTS: dict[str, str] = {
    "steel_cord":              "731210",  # 真鍮メッキ鋼線
    "tackifier_resin":         "390290",  # その他重合体
    "ionomer_resin":           "390390",  # スチレン重合体
    "titanium_alloy":          "810890",  # チタン製品
    "carbon_fiber":            "680159",  # その他炭素繊維
    "tennis_ball_felt":        "591190",  # 工業用繊維製品
    "high_damping_rubber":     "400259",  # その他合成ゴム
    "artificial_turf_pe":      "540249",  # ポリエチレン繊維
    "sbr_chip_filler":         "400400",  # ゴム廃品・くず
    "oa_conductive_rubber":    "400259",  # 導電性ゴム
    "enr_epoxidized_nr":       "400122",  # 天然ゴム (TSNR)
    "dpnr_high_purity":        "400122",  # 同上
    "active_tread_water_switch":"400219", # その他合成ゴム
    "active_tread_temp_switch":"400219",
    "active_tread_third_switch":"400219",
    "hsbr_hnbr":               "400259",  # 水素添加合成ゴム
    "ev_acoustic_foam":        "392113",  # ポリウレタンフォーム
    "ppd6_substitute":         "292142",  # 環状アミン
    "bio_polyol_corn":         "290949",  # ポリオール
    "recycled_golf_ball_rubber":"400400", # ゴム廃品
    "biopharma_low_extract_gasket":"400291",# 加硫ゴム製品
    "new_marine_fender":       "400259",  # 加硫ゴム
    "microplastic_alt_filler": "450190",  # コルク等 (代替材)
    "cancer_cell_polymer":     "390690",  # 医療用ポリマー
    "3d_printer_rubber":       "400259",  # 造形用ゴム
    "automotive_semiconductor":"854239",  # 半導体集積回路
}


def step1_generate_overrides_yml():
    """sumitomo_overrides.yml を生成."""
    with YAML_PATH.open() as f:
        doc = yaml.safe_load(f)
    materials = doc["materials"]

    overrides = {}
    for m in materials:
        mid = m["id"]
        cfg = WB_AND_SEC_BY_ID.get(mid, {})

        # CAS or pseudo CAS
        cas = m.get("cas") or _pseudo_cas(mid)

        ov = {
            "id": mid,
            "name_ja": m["name_ja"],
            "wb_commodity": cfg.get("wb"),
            "sec_tickers": cfg.get("tickers", []),
            "hs6": m.get("hs6_override") or PSEUDO_HS6_HINTS.get(mid),
            "is_pseudo_cas": not m.get("cas"),
        }
        overrides[cas] = ov

    OVERRIDES_PATH.write_text(
        "# Auto-generated by ingest/sumitomo_data_expand.py — do not edit manually.\n"
        "# sumitomo_materials.yml の各物質に対する CAS-level overrides (wb_commodity / sec_tickers / hs6).\n"
        "# chemicals_loader.get_chemical() がこのファイルをマージして scoring に渡します.\n"
        + yaml.safe_dump({"overrides": overrides}, allow_unicode=True, sort_keys=False)
    )
    print(f"  [step1] wrote {OVERRIDES_PATH} ({len(overrides)} entries)")
    return overrides


# -----------------------------------------------------------------------------
# Step 2: chemicals.parquet に CAS あり 10物質を追加
# -----------------------------------------------------------------------------

# CAS あるが chemicals.parquet 未登録の物質 (sumitomo_coverage_audit より)
CAS_TO_ADD = [
    ("9003-17-4",  "Polybutadiene", "elastomer"),
    ("40372-72-3", "Bis(triethoxysilylpropyl)tetrasulfide", "silane"),
    ("64742-46-7", "Distillates (petroleum), solvent-refined heavy paraffinic", "oil"),
    ("24938-64-5", "Poly(p-phenylene terephthalamide)", "polymer"),
    ("9010-85-9",  "Polyisobutylene-co-isoprene", "elastomer"),
    ("68441-14-5", "Bromobutyl rubber", "elastomer"),
    ("9009-54-5",  "Polyurethane", "polymer"),
    ("31694-16-3", "Poly(ether ether ketone)", "polymer"),
    ("12136-58-2", "Lithium sulfide", "inorganic"),
    ("9002-84-0",  "Polytetrafluoroethylene", "polymer"),
]


def _pubchem_fetch(name_query: str) -> dict | None:
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    try:
        r = sess.get(f"{PUBCHEM_BASE}/compound/name/{requests.utils.quote(name_query)}/property/{PROPS}/JSON", timeout=8)
        if r.status_code != 200:
            return None
        d = r.json().get("PropertyTable", {}).get("Properties", [])
        if not d:
            return None
        return d[0]
    except Exception:
        return None


def step2_add_cas_chemicals(overrides: dict):
    """chemicals.parquet に未登録 10物質を追加."""
    chem = pd.read_parquet(CHEM_PATH)
    existing = set(chem["cas"].tolist())

    ts = datetime.now(timezone.utc).isoformat()
    new_rows = []

    for cas, query, cat in CAS_TO_ADD:
        if cas in existing:
            print(f"  [step2] skip {cas} (already in chemicals.parquet)")
            continue
        # PubChem fetch
        props = _pubchem_fetch(query)
        time.sleep(0.3)
        if props:
            row = {
                "cas": cas,
                "pubchem_cid": float(props.get("CID") or 0) or None,
                "name_en": query,
                "iupac_name": props.get("IUPACName"),
                "molecular_formula": props.get("MolecularFormula"),
                "molecular_weight": float(props.get("MolecularWeight")) if props.get("MolecularWeight") else None,
                "inchikey": props.get("InChIKey"),
                "smiles": props.get("ConnectivitySMILES"),
                "synonyms_count": 0,
                "top_synonym": query,
                "category_seed": "sumitomo_added",
                "source_tags": "sumitomo",
                "pubchem_fetch_status": "ok",
                "fetched_at": ts,
                "category_norm": cat,
            }
            print(f"  [step2] +CAS {cas:>14s} {query[:40]:40s} PubChem CID={props.get('CID')}")
        else:
            # substance-only fallback
            row = {
                "cas": cas, "pubchem_cid": None, "name_en": query,
                "iupac_name": None, "molecular_formula": None, "molecular_weight": None,
                "inchikey": None, "smiles": None,
                "synonyms_count": 0, "top_synonym": query,
                "category_seed": "sumitomo_added", "source_tags": "sumitomo",
                "pubchem_fetch_status": "no_pubchem_record",
                "fetched_at": ts, "category_norm": cat,
            }
            print(f"  [step2] +CAS {cas:>14s} {query[:40]:40s} substance-only fallback")
        new_rows.append(row)

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        merged = pd.concat([chem, new_df], ignore_index=True)
        merged.to_parquet(CHEM_PATH, index=False)
        print(f"  [step2] saved chemicals.parquet: {len(chem)} → {len(merged)}")
    else:
        print(f"  [step2] no new CAS to add")


# -----------------------------------------------------------------------------
# Step 3/5: chemicals_hs_map.parquet に sumitomo hs6 (override + pseudo) をマージ
# -----------------------------------------------------------------------------

def step3_merge_hs6(overrides: dict):
    hs = pd.read_parquet(HS_PATH)
    ts = datetime.now(timezone.utc).isoformat()
    new_rows = []
    existing = set(zip(hs["cas"], hs["hs6"]))

    for cas, ov in overrides.items():
        hs6 = ov.get("hs6")
        if not hs6:
            continue
        if (cas, hs6) in existing:
            continue
        chapter = str(hs6)[:2] if hs6 else None
        new_rows.append({
            "cas": cas,
            "hs6": str(hs6),
            "hs_chapter": chapter,
            "hs_label": None,
            "confidence": 0.7,
            "source": "sumitomo_override",
            "created_at": ts,
            "rationale": f"sumitomo_materials.yml hs6_override or PSEUDO_HS6_HINTS for {ov['id']}",
        })

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        merged = pd.concat([hs, new_df], ignore_index=True)
        merged.to_parquet(HS_PATH, index=False)
        print(f"  [step3] hs_map: {len(hs)} → {len(merged)} (+{len(new_rows)} sumitomo overrides)")
    else:
        print(f"  [step3] no new HS6 entries to add")


# -----------------------------------------------------------------------------
# Step 4: CAS未確定 26物質に pseudo CAS で chemicals.parquet にエントリ追加
# -----------------------------------------------------------------------------

def step4_add_substance_only(overrides: dict):
    chem = pd.read_parquet(CHEM_PATH)
    existing = set(chem["cas"].tolist())
    ts = datetime.now(timezone.utc).isoformat()
    new_rows = []

    with YAML_PATH.open() as f:
        doc = yaml.safe_load(f)

    for m in doc["materials"]:
        if m.get("cas"):
            continue
        mid = m["id"]
        pcas = _pseudo_cas(mid)
        if pcas in existing:
            continue
        new_rows.append({
            "cas": pcas,
            "pubchem_cid": None,
            "name_en": m.get("name_en") or m["name_ja"],
            "iupac_name": None, "molecular_formula": None, "molecular_weight": None,
            "inchikey": None, "smiles": None,
            "synonyms_count": 0,
            "top_synonym": m["name_ja"],
            "category_seed": "sumitomo_substance_only",
            "source_tags": "sumitomo",
            "pubchem_fetch_status": "substance_only_pseudo_cas",
            "fetched_at": ts,
            "category_norm": "mixture",
        })

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        merged = pd.concat([chem, new_df], ignore_index=True)
        merged.to_parquet(CHEM_PATH, index=False)
        print(f"  [step4] chemicals.parquet: +{len(new_rows)} substance-only (pseudo CAS)")
    else:
        print(f"  [step4] no substance-only entries to add")


# -----------------------------------------------------------------------------
# Step 5: jp_supplier_count を sumitomo CAS で再集計
# -----------------------------------------------------------------------------

def step5_expand_jp_supplier_count():
    if not SNIPPETS_PATH.exists():
        print(f"  [step5] {SNIPPETS_PATH} not found — skip")
        return

    SUPPLIER_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    out_path = SUPPLIER_DIR / f"jp_supplier_count_{ts.strftime('%Y%m%d')}.parquet"

    # Load existing legacy count (if any) to preserve 17 pinned materials
    # Legacy schema is keyed by `material_id` (string ID, not CAS) — augment with CAS via materials.yml
    existing_files = sorted(SUPPLIER_DIR.glob("jp_supplier_count_*.parquet"))
    existing_legacy = (
        pd.read_parquet(existing_files[-1])
        if existing_files
        else pd.DataFrame()
    )
    if len(existing_legacy) and "cas" not in existing_legacy.columns:
        legacy_mats_p = ROOT / "app" / "materials.yml"
        mid_to_cas = {}
        if legacy_mats_p.exists():
            ldoc = yaml.safe_load(legacy_mats_p.read_text()) or {}
            for lm in ldoc.get("materials", []):
                if lm.get("id") and lm.get("cas"):
                    mid_to_cas[lm["id"]] = lm["cas"]
        existing_legacy = existing_legacy.copy()
        existing_legacy["cas"] = existing_legacy["material_id"].map(mid_to_cas)

    # sumitomo マスタ × EDINET スニペット
    with YAML_PATH.open() as f:
        doc = yaml.safe_load(f)

    # Search keywords per material (name_ja + aliases + name_en)
    con = duckdb.connect()
    con.execute(f"CREATE VIEW snip AS SELECT * FROM '{SNIPPETS_PATH}'")

    rows = []
    for m in doc["materials"]:
        cas = m.get("cas")
        if not cas:
            cas = _pseudo_cas(m["id"])
        keywords = [m["name_ja"]]
        if m.get("name_en"):
            keywords.append(m["name_en"])
        for a in m.get("aliases", []):
            s = str(a).strip() if a is not None else ""
            if s:
                keywords.append(s)
        # Filter useful keywords (>=2 chars, no obvious noise)
        keywords = [k for k in keywords if k and isinstance(k, str) and len(k) >= 2]
        if not keywords:
            continue

        like_clauses = " OR ".join(["snippet LIKE ?"] * len(keywords))
        params = [f"%{k}%" for k in keywords]
        try:
            r = con.execute(
                f"SELECT COUNT(DISTINCT company) AS n FROM snip WHERE {like_clauses}", params
            ).fetchone()
            n = int(r[0]) if r else 0
        except Exception:
            n = 0
        rows.append({
            "cas": cas,
            "name_ja": m["name_ja"],
            "name_en": m.get("name_en"),
            "jp_supplier_count": n,
            "matched_keywords": json.dumps(keywords, ensure_ascii=False),
            "source": "sumitomo_expand",
            "_built_at": ts.isoformat(),
        })

    sumitomo_df = pd.DataFrame(rows)

    # Merge legacy + sumitomo, prefer legacy entries (17 pinned materials)
    if len(existing_legacy):
        # Keep legacy for matching CAS, add sumitomo for new
        legacy_cas = set(existing_legacy["cas"].tolist())
        sumi_new = sumitomo_df[~sumitomo_df["cas"].isin(legacy_cas)]
        out_df = pd.concat([existing_legacy, sumi_new], ignore_index=True)
    else:
        out_df = sumitomo_df

    out_df.to_parquet(out_path, index=False)
    print(f"  [step5] {out_path.name}: {len(out_df)} rows ({len(sumitomo_df)} sumitomo + legacy)")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    print("=== Sumitomo Mock — Data Expansion (Tasks 1–6) ===\n")
    overrides = step1_generate_overrides_yml()
    print()
    step2_add_cas_chemicals(overrides)
    print()
    step4_add_substance_only(overrides)  # substance-only を先に追加して CAS pool を埋める
    print()
    step3_merge_hs6(overrides)  # その後 HS6 マッピングをマージ
    print()
    step5_expand_jp_supplier_count()
    print()
    print("=== Done. Now run: python -m ingest.sumitomo_build && python -m ingest.sumitomo_coverage_audit ===")


if __name__ == "__main__":
    main()
