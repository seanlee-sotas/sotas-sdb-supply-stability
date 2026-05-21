"""戦略物資3国フラグ — EU CRMA 2024 / US DOI Critical Minerals 2022 / METI 特定重要物資.

各物質に対して「EU 戦略原材料」「US 重要鉱物」「JP 特定重要物資」の認定有無を統合。
住友ゴム関連物質は CAS / 元素記号 / 物質名で照合可能。

出力:
  data/regulations/strategic_materials_20YYMMDD.parquet
    columns: token | eu_crma | us_critical_2022 | jp_meti | strategic_count | source_links
  token は CAS or 元素記号 or 物質名スラッグ (柔軟マッチ用)
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "regulations"

# ===== EU Critical Raw Materials Act 2024 (Regulation 2024/1252) =====
# Annex I: Strategic Raw Materials (16)
EU_STRATEGIC = {
    "bismuth", "boron", "cobalt", "copper", "gallium", "germanium", "lithium",
    "magnesium_metal", "manganese", "natural_graphite", "nickel",
    "platinum_group_metals", "rare_earth_elements_heavy", "rare_earth_elements_light",
    "silicon_metal", "titanium_metal", "tungsten",
}
# Annex II: Critical Raw Materials (34, includes Strategic plus more)
EU_CRITICAL = EU_STRATEGIC | {
    "aluminium_bauxite", "antimony", "arsenic", "baryte", "beryllium",
    "coking_coal", "feldspar", "fluorspar", "hafnium", "helium", "iron_ore",
    "niobium", "phosphate_rock", "phosphorus", "scandium", "strontium",
    "tantalum", "vanadium",
}

# ===== US DOI/USGS Critical Minerals List 2022 (50 materials) =====
US_CRITICAL_2022 = {
    "aluminum", "antimony", "arsenic", "barite", "beryllium", "bismuth", "cerium",
    "cesium", "chromium", "cobalt", "dysprosium", "erbium", "europium", "fluorspar",
    "gadolinium", "gallium", "germanium", "graphite", "hafnium", "holmium", "indium",
    "iridium", "lanthanum", "lithium", "lutetium", "magnesium", "manganese",
    "neodymium", "nickel", "niobium", "palladium", "platinum", "praseodymium",
    "rhodium", "rubidium", "ruthenium", "samarium", "scandium", "tantalum",
    "tellurium", "terbium", "thulium", "tin", "titanium", "tungsten", "vanadium",
    "ytterbium", "yttrium", "zinc", "zirconium",
}

# ===== METI 特定重要物資 (経済安保法、2022年認定 + 2023追加) =====
# https://www.meti.go.jp/policy/economy/economic_security/index.html
# カテゴリ名 (broad) と、住友ゴムが該当しうる広解釈の物質
METI_CRITICAL_CATEGORIES = {
    "semiconductor": "半導体",
    "cloud_program": "クラウドプログラム",
    "battery": "蓄電池",
    "machine_tool_robot": "工作機械・産業用ロボット",
    "critical_minerals": "重要鉱物",   # ← レアアース / Li / Co / Ni / Mn / W / Ti を含む広義カテゴリ
    "antibacterial": "抗菌性物質製剤",
    "permanent_magnet": "永久磁石",
    "aircraft_parts": "航空機部品",
    "natural_gas": "天然ガス",
    "ship_parts": "船舶部品",
    "uranium": "ウラン",
    "fertilizer": "肥料",
}
# 「重要鉱物」カテゴリに含まれると公式に明記された / 解釈される元素
METI_CRITICAL_MINERALS_ELEMENTS = {
    "Li", "Co", "Ni", "Mn", "W", "Ti", "Ga", "Ge", "In",
    "REE",  # レアアース全般
    "Pt", "Pd", "Rh",
}

# ===== トークン → 各リスト hit の判定 =====

# Sumitomo Rubber 関連物質に focus した token list
# token = lower-case identifier (element symbol, CAS, or slug)
SUMITOMO_RELEVANT_TOKENS: list[dict] = [
    # element-keyed (USGS と一致)
    {"token": "W",  "cas": "7440-33-7",  "name": "Tungsten",  "element": "W"},
    {"token": "Ti", "cas": None,          "name": "Titanium (metal/合金)", "element": "Ti"},
    {"token": "Zn", "cas": "1314-13-2",   "name": "Zinc (ZnO)", "element": "Zn"},
    {"token": "Li", "cas": "12136-58-2",  "name": "Lithium compounds", "element": "Li"},
    {"token": "C_graphite", "cas": "7782-42-5", "name": "Graphite / Graphene", "element": "C"},
    {"token": "Cu", "cas": None,          "name": "Copper (steel cord brass)", "element": "Cu"},
    {"token": "S",  "cas": "7704-34-9",   "name": "Sulfur", "element": "S"},
    {"token": "Si_metal", "cas": "7631-86-9", "name": "Silicon (silica)", "element": "Si"},
    # tire-specific (CAS 駆動)
    {"token": "natural_rubber", "cas": "9006-04-6", "name": "Natural rubber", "element": None},
    {"token": "semiconductor",  "cas": None,        "name": "車載半導体 (Viaduct関連)", "element": None},
    {"token": "battery",        "cas": None,        "name": "リチウム硫黄電池 (新規事業)", "element": None},
]


def _check_eu(token: str, element: str | None) -> tuple[bool, bool]:
    """Returns (in_strategic, in_critical)."""
    e = (element or "").lower()
    t = (token or "").lower()
    # Map common element symbols to EU CRMA category names
    map_eu = {
        "w": "tungsten", "ti": "titanium_metal", "zn": None,  # Zn は EU CRMA 未認定
        "li": "lithium", "co": "cobalt", "ni": "nickel", "mn": "manganese",
        "cu": "copper", "s": None, "si": "silicon_metal", "c": "natural_graphite",
    }
    cand = map_eu.get(e)
    in_strat = cand in EU_STRATEGIC if cand else False
    in_crit = cand in EU_CRITICAL if cand else False
    # special tokens
    if t == "natural_rubber":
        # CRMA 2024 では正式 Annex には未掲載 (要確認)
        return False, False
    return in_strat, in_crit


def _check_us(element: str | None) -> bool:
    e = (element or "").lower()
    map_us = {
        "w": "tungsten", "ti": "titanium", "zn": "zinc",
        "li": "lithium", "co": "cobalt", "ni": "nickel", "mn": "manganese",
        "cu": None,  # Cu は US 2022 list には未掲載
        "s": None, "si": None, "c": "graphite",
    }
    cand = map_us.get(e)
    return cand in US_CRITICAL_2022 if cand else False


def _check_meti(element: str | None, token: str) -> tuple[bool, str | None]:
    """Returns (hit, category_jp)."""
    e = (element or "").upper()
    t = token.lower()
    if e in METI_CRITICAL_MINERALS_ELEMENTS:
        return True, METI_CRITICAL_CATEGORIES["critical_minerals"]
    if t == "semiconductor":
        return True, METI_CRITICAL_CATEGORIES["semiconductor"]
    if t == "battery":
        return True, METI_CRITICAL_CATEGORIES["battery"]
    return False, None


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    rows = []
    for entry in SUMITOMO_RELEVANT_TOKENS:
        token, element, cas = entry["token"], entry["element"], entry["cas"]
        eu_strat, eu_crit = _check_eu(token, element)
        us_hit = _check_us(element)
        meti_hit, meti_cat = _check_meti(element, token)

        strategic_count = sum([eu_strat, us_hit, meti_hit])
        critical_count = sum([eu_crit, us_hit, meti_hit])

        rows.append({
            "token": token,
            "cas": cas,
            "name": entry["name"],
            "element": element,
            # EU CRMA 2024 (Strategic 16 ⊂ Critical 34)
            "eu_strategic": eu_strat,
            "eu_critical": eu_crit,
            # US Critical Minerals 2022 (50)
            "us_critical_2022": us_hit,
            # METI 特定重要物資
            "meti_critical": meti_hit,
            "meti_category": meti_cat,
            # サマリー
            "strategic_count": strategic_count,   # max 3 (EU strategic + US critical + JP meti)
            "critical_count": critical_count,     # max 3 (EU critical 含む)
            # 出典
            "eu_source": "EU Regulation 2024/1252 (Critical Raw Materials Act)",
            "us_source": "USGS / DOI 2022 Critical Minerals List (Federal Register Vol.87)",
            "jp_source": "METI 経済安全保障推進法 特定重要物資",
            "_fetched_at": ts,
        })

    df = pd.DataFrame(rows)
    out = OUT_DIR / f"strategic_materials_{datetime.now().strftime('%Y%m%d')}.parquet"
    df.to_parquet(out, index=False)
    print(f"saved: {out} ({len(df)} tokens)")
    print()
    print("=== Strategic Materials Flag Summary ===")
    print(df[["token", "name", "eu_strategic", "us_critical_2022", "meti_critical", "strategic_count"]].to_string(index=False))


if __name__ == "__main__":
    main()
