"""Loaders for Sumitomo Rubber Mock — wraps materials.parquet + citations.parquet."""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parent.parent
SUM_DIR = REPO / "data" / "sumitomo"


@st.cache_data(show_spinner=False)
def load_materials() -> pd.DataFrame:
    return pd.read_parquet(SUM_DIR / "materials.parquet")


@st.cache_data(show_spinner=False)
def load_citations() -> pd.DataFrame:
    return pd.read_parquet(SUM_DIR / "citations.parquet")


@st.cache_data(show_spinner=False)
def load_segments() -> dict:
    return json.loads((SUM_DIR / "segments.json").read_text())


@st.cache_data(show_spinner=False)
def load_layers() -> dict:
    return json.loads((SUM_DIR / "layers.json").read_text())


@st.cache_data(show_spinner=False)
def load_metadata() -> dict:
    return json.loads((SUM_DIR / "metadata.json").read_text())


def get_material(material_id: str) -> dict | None:
    df = load_materials()
    sub = df[df["id"] == material_id]
    if not len(sub):
        return None
    return sub.iloc[0].to_dict()


def get_citations(material_id: str) -> pd.DataFrame:
    cit = load_citations()
    return cit[cit["material_id"] == material_id].reset_index(drop=True)


def filter_by_segment(segment: str, status: str | None = None) -> pd.DataFrame:
    df = load_materials()
    df = df[df["segments"].str.contains(f'"{segment}"', regex=False)]
    if status:
        df = df[df["status"] == status]
    return df.reset_index(drop=True)


def axis_signal_emoji(score: float | None) -> str:
    if score is None:
        return "⚪"
    if score >= 70:
        return "🟢"
    if score >= 40:
        return "🟡"
    return "🔴"


@st.cache_data(show_spinner=False)
def load_upstream_chains() -> dict:
    """app/sumitomo_upstream.yml をパース。物質id → 上流系譜 (self + parents tree)."""
    import yaml
    p = Path(__file__).resolve().parent / "sumitomo_upstream.yml"
    if not p.exists():
        return {}
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return doc.get("chains") or {}
    except Exception:
        return {}


def flatten_upstream(chain: dict, depth: int = 0, parent_role: str = "") -> list[dict]:
    """Flatten the upstream tree into a list of nodes with depth annotation."""
    nodes = []
    if "self" in chain:
        s = chain["self"]
        nodes.append({
            "name": s.get("name"),
            "cas": s.get("cas"),
            "role": s.get("role") or "self",
            "depth": 0,
            "is_self": True,
        })
    for p in chain.get("parents", []):
        nodes.extend(_walk_node(p, depth=1))
    return nodes


def _walk_node(node: dict, depth: int) -> list[dict]:
    out = [{
        "name": node.get("name"),
        "cas": node.get("cas"),
        "role": node.get("role"),
        "note": node.get("note"),
        "usgs_element": node.get("usgs_element"),
        "wb_commodity": node.get("wb_commodity"),
        "strategic_token": node.get("strategic_token"),
        "depth": depth,
        "is_self": False,
    }]
    for child in node.get("parents", []) or []:
        out.extend(_walk_node(child, depth + 1))
    return out


AXIS_LABELS = {
    "axis1_capacity": "🏭 軸1 生産能力",
    "axis2_supply_demand": "⚖️ 軸2 需給",
    "axis3_jp_concentration": "🤝 軸3 国内集中",
    "axis4_global_hhi": "🌐 軸4 地政学",
    "axis5_regulation": "📋 軸5 規制",
    "axis6_events": "💥 軸6 供給途絶",
    "axis7_price": "💹 軸7 価格変動",
}
