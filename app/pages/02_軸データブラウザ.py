"""元データ閲覧 — 7軸ごとに生parquet・カラム定義・メタ情報を閲覧."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import source_inspector  # noqa: E402

st.set_page_config(
    page_title="元データ閲覧 | SDB Mock",
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


st.title("📊 元データ閲覧")

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
        "**生産段階の集中度** は USGS / 戦略物資フラグ / FAOSTAT NR で補強。"
    )
    source_inspector.render_source(
        "comtrade_trade", latest_parquet(DATA / "comtrade", "trade"),
        key_suffix="axis4", expanded=True,
    )

    st.markdown("---")
    st.markdown("### 🌐 地政学拡張データ (Comtrade を超えた生産段階)")

    # USGS Mineral Commodity Summaries
    usgs_p = latest_parquet(DATA / "usgs", "mineral_concentration")
    usgs_p = usgs_p if usgs_p and "summary" not in usgs_p.stem else find_glob(DATA / "usgs", "mineral_concentration_2*.parquet")
    if usgs_p and usgs_p.exists():
        with st.expander("⛏ USGS Mineral Commodity Summaries 2025 — 鉱物国別生産シェア", expanded=False):
            import pandas as pd
            usgs_df = pd.read_parquet(usgs_p)
            st.markdown(
                f"**出典**: [USGS MCS 2025](https://pubs.usgs.gov/periodicals/mcs2025/)  "
                f"  ·  **データ年**: {usgs_df['source_year'].iloc[0]}  "
                f"  ·  **対象元素**: {usgs_df['element'].nunique()}種類  "
                f"  ·  **粒度**: 元素 × 国別生産シェア"
            )
            st.markdown(
                "**カラム定義**: element=元素記号 / name=鉱物名 / country=生産国 / share_pct=世界シェア(%) / unit=単位 / source_year=データ年"
            )
            st.dataframe(usgs_df, use_container_width=True, height=420)

        usgs_sum_p = find_glob(DATA / "usgs", "mineral_concentration_summary_*.parquet")
        if usgs_sum_p and usgs_sum_p.exists():
            with st.expander("⛏ USGS 元素別 HHI サマリー", expanded=False):
                sum_df = pd.read_parquet(usgs_sum_p)
                st.dataframe(sum_df.sort_values("hhi", ascending=False), use_container_width=True)

    # Strategic Materials Flag (EU CRMA + US Critical + METI)
    strat_p = latest_parquet(DATA / "regulations", "strategic_materials")
    if strat_p and strat_p.exists():
        with st.expander("🏛 戦略物資 3国認定フラグ (EU CRMA / US Critical / METI)", expanded=False):
            import pandas as pd
            strat_df = pd.read_parquet(strat_p)
            st.markdown(
                "**3地域の戦略原材料リスト統合**:  \n"
                "- 🇪🇺 EU CRMA 2024 (Regulation 2024/1252) — Strategic 16 + Critical 34  \n"
                "- 🇺🇸 US DOI/USGS Critical Minerals List 2022 (50物質)  \n"
                "- 🇯🇵 METI 特定重要物資 (経済安全保障推進法、2022認定)"
            )
            st.markdown(
                "**カラム定義**: token / cas / name / element / eu_strategic / eu_critical / "
                "us_critical_2022 / meti_critical / strategic_count (3国中認定数)"
            )
            st.dataframe(strat_df.sort_values("strategic_count", ascending=False), use_container_width=True)

    # FAOSTAT Natural Rubber
    fao_p = latest_parquet(DATA / "faostat", "natural_rubber_production")
    if fao_p and fao_p.exists():
        with st.expander("🌱 FAOSTAT 天然ゴム国別生産", expanded=False):
            import pandas as pd
            fao_df = pd.read_parquet(fao_p)
            latest_year = fao_df['year'].max()
            sub = fao_df[fao_df['year'] == latest_year].sort_values("value", ascending=False)
            source = sub['source'].iloc[0] if 'source' in sub.columns else "FAOSTAT"
            st.markdown(
                f"**出典**: {source}  ·  **対象年**: {latest_year}  ·  **対象国**: {sub['area'].nunique()}"
            )
            if source == "ANRPC_IRSG_CURATED":
                st.warning(
                    "FAOSTAT API が一時的にダウンしているため、ANRPC/IRSG 公開2023年値で代用しています。"
                    "API復活時に自動で本データに切り替わります。"
                )
            st.dataframe(sub, use_container_width=True)

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
