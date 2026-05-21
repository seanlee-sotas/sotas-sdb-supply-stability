"""軸データブラウザ — 7軸ごとに生parquet・カラム定義・メタ情報を閲覧."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import source_inspector  # noqa: E402

st.set_page_config(
    page_title="軸データブラウザ | SDB Mock",
    page_icon="📊",
    layout="wide",
)

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"


def latest_parquet(directory: Path, prefix: str) -> Path | None:
    if not directory.exists():
        return None
    files = sorted(directory.glob(f"{prefix}_*.parquet"))
    return files[-1] if files else None


def find_glob(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    files = sorted(directory.glob(pattern))
    return files[-1] if files else None


st.title("📊 軸データブラウザ")

st.markdown(
    """
SDB の供給リスク評価で使う **7軸の生データ** を、カラム定義・出典URL・更新日付き で閲覧できます。
このページは「**スコアの中身を疑った時に開く**」ためのものです。

各軸の生データは Parquet 形式で保存されており、CSV ダウンロードも可能です。
"""
)

st.divider()

axis = st.radio(
    "軸を選択",
    options=["axis1", "axis2", "axis3", "axis4", "axis5", "axis6", "axis7"],
    format_func=lambda x: {
        "axis1": "🏭 軸1 生産能力・新増設",
        "axis2": "⚖️ 軸2 需給バランス",
        "axis3": "🤝 軸3 国内供給集中度",
        "axis4": "🌐 軸4 地政学・原産地集中",
        "axis5": "📋 軸5 規制・政策",
        "axis6": "💥 軸6 過去の供給途絶",
        "axis7": "💹 軸7 価格変動性",
    }[x],
    horizontal=True,
)

st.divider()

# -----------------------------------------------------------------------------
# 軸別データソース一覧
# -----------------------------------------------------------------------------

if axis == "axis1":
    st.subheader("🏭 軸1 生産能力・新増設")
    st.caption(
        "EDINET 有価証券報告書から「生産能力」「年産」「設備能力」キーワード周辺をスニペット抽出 → LLM で構造化（製品×拠点×年間能力）。"
    )
    source_inspector.render_source(
        "edinet_snippets", latest_parquet(DATA / "edinet", "capacity_snippets")
    )
    source_inspector.render_source(
        "edinet_structured", latest_parquet(DATA / "edinet", "capacity_structured"),
        expanded=True,
    )

elif axis == "axis2":
    st.subheader("⚖️ 軸2 需給バランス")
    st.caption(
        "UN Comtrade 純輸出比率 (X-M)/(X+M) + JPCA エチレン稼働率 + 化学業界 disruption ニュース。"
    )
    source_inspector.render_source(
        "comtrade_trade", latest_parquet(DATA / "comtrade", "trade"),
        key_suffix="axis2", expanded=True,
    )
    source_inspector.render_source(
        "jpca_utilization", latest_parquet(DATA / "jpca", "utilization")
    )
    source_inspector.render_source(
        "jpca_monthly", latest_parquet(DATA / "jpca", "monthly")
    )
    source_inspector.render_source(
        "chem_news", latest_parquet(DATA / "news", "chem_news")
    )

elif axis == "axis3":
    st.subheader("🤝 軸3 国内供給集中度")
    st.caption(
        "EDINET スニペット + 手動マッピングで、各CASに対する国内上場サプライヤー数を集計（3バンド分類）。"
    )
    source_inspector.render_source(
        "jp_supplier",
        latest_parquet(DATA / "chemicals", "chemicals_company_map")
        or (DATA / "chemicals" / "chemicals_company_map.parquet"),
        expanded=True,
    )

elif axis == "axis4":
    st.subheader("🌐 軸4 地政学・原産地集中")
    st.caption(
        "UN Comtrade 世界輸出データから HHI を算出、Top輸出国上位5を抽出。"
    )
    source_inspector.render_source(
        "comtrade_trade", latest_parquet(DATA / "comtrade", "trade"),
        key_suffix="axis4", expanded=True,
    )

elif axis == "axis5":
    st.subheader("📋 軸5 規制・政策")
    st.caption(
        "ECHA SVHC (REACH高懸念物質候補) + METI 特定重要物資 + Stockholm POPs (残留性有機汚染物質)。"
    )
    source_inspector.render_source(
        "echa_svhc", latest_parquet(DATA / "echa", "svhc"), expanded=True,
    )
    source_inspector.render_source(
        "meti_critical", latest_parquet(DATA / "regulations", "meti_critical")
    )
    source_inspector.render_source(
        "pops", latest_parquet(DATA / "regulations", "pops")
    )

elif axis == "axis6":
    st.subheader("💥 軸6 過去の供給途絶イベント")
    st.caption(
        "SEC 8-K / EDINET 臨時報告書 / DART 主要事項報告 / TDnet 開示 / TWSE 重大情報 / NITE 化学事故 を横断、LLM分類で供給関連イベントのみ抽出。"
    )
    source_inspector.render_source(
        "sec_8k", latest_parquet(DATA / "sec", "filings_8k"), expanded=True,
    )
    source_inspector.render_source(
        "sec_item801", latest_parquet(DATA / "sec", "item801_classified"), expanded=True,
    )
    source_inspector.render_source(
        "edinet_extraordinary",
        latest_parquet(DATA / "edinet", "extraordinary_reports"),
    )
    source_inspector.render_source(
        "dart_major_matters",
        latest_parquet(DATA / "dart", "dart_major_matters"),
    )
    source_inspector.render_source(
        "tdnet_disclosure",
        latest_parquet(DATA / "tdnet", "tdnet_disclosure"),
    )
    source_inspector.render_source(
        "twse_material_info",
        latest_parquet(DATA / "twse", "twse_material_info"),
    )
    source_inspector.render_source(
        "nite_accidents",
        latest_parquet(DATA / "nite", "nite_accidents"),
    )

elif axis == "axis7":
    st.subheader("💹 軸7 価格変動性")
    st.caption(
        "World Bank Pink Sheet (無料月次商品価格、1960年〜)。タイヤ用 rubber TSR20/RSS3、原油 Brent/WTI/Dubai、天然ガス、ベース金属を含む15品目。"
    )
    source_inspector.render_source(
        "wb_prices", latest_parquet(DATA / "worldbank", "prices_monthly"),
        expanded=True,
    )

st.divider()

with st.expander("🧪 自社 chemicals マスタ（CAS→PubChem/HS紐付け）", expanded=False):
    source_inspector.render_source(
        "jp_supplier",
        DATA / "chemicals" / "chemicals.parquet",
        key_suffix="chemicals_master",
    )

st.caption(
    "凡例：🟢 0-39（リスク低）/ 🟡 40-69（注意）/ 🔴 70-100（高リスク） — 軸ごとに方向が異なります（一部は高い=リスク高、一部は逆）。詳細は [📚 出典・methodology] へ"
)
