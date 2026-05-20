"""SDB 供給安定性 dashboard — 7軸プロキシビュー."""
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chemicals_loader as cl  # noqa: E402

ACCENT = "#0F766E"
ACCENT_LIGHT = "#5EEAD4"
DANGER = "#DC2626"
MUTED = "#64748B"

PLOT_TEMPLATE = "simple_white"


def styled_fig(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        template=PLOT_TEMPLATE,
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        font=dict(family="sans-serif", size=12),
        hoverlabel=dict(bgcolor="white", font_size=12),
        showlegend=False,
    )
    fig.update_xaxes(showline=True, linecolor="#E2E8F0")
    fig.update_yaxes(showline=True, linecolor="#E2E8F0", gridcolor="#F1F5F9")
    return fig

ROOT = Path(__file__).resolve().parent.parent
COMTRADE_DIR = ROOT / "data" / "comtrade"
ECHA_DIR = ROOT / "data" / "echa"
REG_DIR = ROOT / "data" / "regulations"
SEC_DIR = ROOT / "data" / "sec"
EDINET_DIR = ROOT / "data" / "edinet"
WB_DIR = ROOT / "data" / "worldbank"
SUPPLIER_DIR = ROOT / "data" / "supplier"

AXES = [
    # (code, name, proxy_indicator, data_source)
    ("軸1", "生産能力・新増設",
     "新増設・能力変動の方向（new/expand/reduce/maintain）と件数",
     "EDINET 有報・統合報告書・中計テキスト"),
    ("軸2", "需給バランス",
     "日本の純輸出比率 (輸出−輸入)/総貿易額  ＋1=供給過剰 / −1=輸入依存",
     "UN Comtrade 年次貿易統計"),
    ("軸3", "サプライヤー集中度",
     "JP上場サプライヤー社数（3バンド：≤3/4-10/11+）",
     "EDINET テキスト由来の言及社数"),
    ("軸4", "地政学・原産地",
     "輸出国HHI / Top-1単一国依存度 / Top-3シェア",
     "UN Comtrade 年次貿易統計"),
    ("軸5", "政策・規制リスク",
     "規制リスト該当数 ＋ 直近収載日（早期警報）",
     "ECHA SVHC ・ Stockholm POPs ・ METI 特定重要物資"),
    ("軸6", "過去の供給途絶",
     "供給関連イベント頻度（LLM分類で FM/事故/停止 を抽出）",
     "SEC EDGAR 8-K ＋ Claude 分類"),
    ("軸7", "価格変動性",
     "12ヶ月 年率ボラティリティ ＋ YoY 変化率",
     "World Bank Pink Sheet 月次商品価格"),
]

st.set_page_config(page_title="SDB 供給安定性", layout="wide")

# Custom CSS: make form inputs more obviously interactive
st.markdown("""
<style>
/* Selectbox: visible border + hover state + chevron clarity */
div[data-baseweb="select"] > div {
    background-color: #FFFFFF !important;
    border: 1px solid #94A3B8 !important;
    border-radius: 6px !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
div[data-baseweb="select"] > div:hover {
    border-color: #0F766E !important;
    box-shadow: 0 0 0 1px rgba(15, 118, 110, 0.15);
    cursor: pointer;
}
div[data-baseweb="select"] svg {
    color: #475569 !important;
}
/* Text input + textarea */
.stTextInput input, .stTextArea textarea, .stNumberInput input {
    background-color: #FFFFFF !important;
    border: 1px solid #94A3B8 !important;
    border-radius: 6px !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #0F766E !important;
    box-shadow: 0 0 0 1px rgba(15, 118, 110, 0.15);
}
/* Slider: handle visibility */
.stSlider [data-baseweb="slider"] [role="slider"] {
    border: 2px solid #0F766E !important;
}
/* Tab indicator: more prominent active state */
.stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
    color: #0F766E !important;
    font-weight: 600 !important;
}
/* Labels above inputs: tiny weight bump so the form structure reads */
.stSelectbox label, .stTextInput label, .stSlider label {
    font-weight: 500 !important;
    color: #334155 !important;
}
</style>
""", unsafe_allow_html=True)

st.title("SDB 供給安定性 dashboard")
st.caption("7要素プロキシ指標による素材別供給リスクの可視化")

with st.sidebar:
    st.subheader("7軸プロキシ指標")
    for code, name, proxy, source in AXES:
        st.markdown(
            f"**{code}** {name}  \n　<small>{proxy}</small>",
            unsafe_allow_html=True,
        )


# ---------- shared loaders ----------
@st.cache_data
def load_reporters() -> dict[int, str]:
    p = COMTRADE_DIR / "ref_reporters.json"
    if not p.exists():
        return {}
    return {r["reporterCode"]: r["reporterDesc"] for r in json.loads(p.read_text())}


@st.cache_data
def load_hs_desc() -> dict[str, str]:
    p = COMTRADE_DIR / "ref_hs.json"
    if not p.exists():
        return {}
    out = {}
    for r in json.loads(p.read_text()):
        code = r.get("id", "")
        text = r.get("text", "")
        out[code] = text.split(" - ", 1)[1] if " - " in text else text
    return out


def latest_parquet(directory: Path, prefix: str):
    files = sorted(directory.glob(f"{prefix}_*.parquet"))
    non_quick = [p for p in files if "_quick" not in p.stem]
    if non_quick:
        return max(non_quick)
    return max(files) if files else None


# ---------- tab 4 ----------
def render_axis4():
    parquet = latest_parquet(COMTRADE_DIR, "trade")
    if parquet is None:
        st.error("`data/comtrade/trade_*.parquet` なし。`uv run python ingest/comtrade.py --quick` 実行。")
        return

    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW trade AS SELECT * FROM '{parquet}'")
    reporters = load_reporters()
    hs_desc = load_hs_desc()
    total_rows = con.execute("SELECT COUNT(*) FROM trade").fetchone()[0]

    st.info(
        "**軸4「地政学・原産地」** | UN Comtrade年次貿易統計から、HS6コードごとの世界輸出/輸入の国別集中度を計算。"
        "HHI・Top-Nシェア・単一国依存度で素材別の供給リスクの粗いシグナルを得る。"
    )
    st.caption(f"データ: `{parquet.name}` ({total_rows:,} rows)")

    c1, c2, c3 = st.columns(3)
    with c1:
        hs_codes = [r[0] for r in con.execute("SELECT DISTINCT cmdCode FROM trade ORDER BY cmdCode").fetchall()]
        selected_hs = st.selectbox(
            "HS6コード", hs_codes,
            format_func=lambda c: f"{c} — {hs_desc.get(c, '?')[:60]}", key="ax4_hs",
        )
    with c2:
        flows = [r[0] for r in con.execute("SELECT DISTINCT flowCode FROM trade").fetchall()]
        flow_labels = {"X": "輸出 (輸出国別シェア)", "M": "輸入 (輸入国別シェア)"}
        selected_flow = st.selectbox("フロー", flows, format_func=lambda x: flow_labels.get(x, x), key="ax4_flow")
    with c3:
        periods = [r[0] for r in con.execute("SELECT DISTINCT period FROM trade ORDER BY period DESC").fetchall()]
        selected_period = st.selectbox("期間", periods, key="ax4_period")

    df = con.execute(
        """SELECT reporterCode, primaryValue, qty, netWgt FROM trade
           WHERE cmdCode = ? AND flowCode = ? AND period = ?
             AND partner2Code = 0 AND primaryValue > 0
           ORDER BY primaryValue DESC""",
        [selected_hs, selected_flow, str(selected_period)],
    ).df()

    if df.empty:
        st.warning("該当データなし。")
        return

    df["reporter"] = df["reporterCode"].map(lambda c: reporters.get(c, f"M49 {c}"))
    total = df["primaryValue"].sum()
    df["share_pct"] = df["primaryValue"] / total * 100
    hhi = (df["share_pct"] ** 2).sum()

    st.markdown(f"### HS {selected_hs} — {hs_desc.get(selected_hs, '?')}")
    st.caption(f"{flow_labels.get(selected_flow, selected_flow)}　|　{selected_period}年")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("世界貿易額", f"${total / 1e9:,.2f}B")
    m2.metric("報告国数", len(df))
    m3.metric("HHI (0–10000)", f"{hhi:,.0f}", help="<1500 低集中 / 1500–2500 中集中 / >2500 高集中")
    m4.metric("Top-1 シェア", f"{df.iloc[0]['share_pct']:.1f}%", help=str(df.iloc[0]["reporter"]))
    m5.metric("Top-3 シェア", f"{df.head(3)['share_pct'].sum():.1f}%")

    st.subheader("国別シェア Top 20")
    top20 = df.head(20)
    fig = px.bar(
        top20, x="reporter", y="primaryValue",
        hover_data={"share_pct": ":.2f", "primaryValue": ":,.0f"},
        labels={"reporter": "国", "primaryValue": "貿易額 (USD)"},
        color_discrete_sequence=[ACCENT],
    )
    fig.update_traces(hovertemplate="<b>%{x}</b><br>貿易額: $%{y:,.0f}<br>シェア: %{customdata[0]:.2f}%<extra></extra>")
    st.plotly_chart(styled_fig(fig, height=420), use_container_width=True)

    with st.expander("全ランキング"):
        disp = df.assign(
            primaryValue=df["primaryValue"].map(lambda v: f"${v / 1e6:,.1f}M"),
            share_pct=df["share_pct"].map(lambda v: f"{v:.2f}%"),
        )[["reporter", "primaryValue", "share_pct", "qty", "netWgt"]]
        disp.columns = ["国", "貿易額", "シェア", "数量", "正味重量 (kg)"]
        st.dataframe(disp, use_container_width=True, hide_index=True)

    st.subheader("HHI 年次推移")
    trend = con.execute(
        """WITH per_reporter AS (
             SELECT period, reporterCode, SUM(primaryValue) AS v FROM trade
             WHERE cmdCode = ? AND flowCode = ?
               AND partner2Code = 0 AND primaryValue > 0
             GROUP BY period, reporterCode
           ),
           period_total AS (SELECT period, SUM(v) AS total FROM per_reporter GROUP BY period)
           SELECT pr.period, SUM(POW(pr.v / pt.total * 100, 2)) AS hhi
           FROM per_reporter pr JOIN period_total pt USING (period)
           GROUP BY pr.period ORDER BY pr.period""",
        [selected_hs, selected_flow],
    ).df()
    if len(trend) > 1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=trend["period"], y=trend["hhi"], mode="lines+markers",
            line=dict(color=ACCENT, width=3), marker=dict(size=8),
            hovertemplate="<b>%{x}</b><br>HHI: %{y:,.0f}<extra></extra>",
        ))
        # Concentration thresholds
        fig.add_hline(y=1500, line_dash="dash", line_color=MUTED, annotation_text="中集中ライン (1500)", annotation_position="right")
        fig.add_hline(y=2500, line_dash="dash", line_color=DANGER, annotation_text="高集中ライン (2500)", annotation_position="right")
        fig.update_yaxes(title="HHI", rangemode="tozero")
        fig.update_xaxes(title="期間")
        st.plotly_chart(styled_fig(fig, height=320), use_container_width=True)
    else:
        st.info("現データは1期のみ。`uv run python ingest/comtrade.py` で全期間ingest。")


# ---------- tab 5 ----------
def render_axis5():
    svhc_p = latest_parquet(ECHA_DIR, "svhc")
    meti_p = latest_parquet(REG_DIR, "meti_critical")
    pops_p = latest_parquet(REG_DIR, "pops")

    st.info(
        "**軸5「政策・規制リスク」** | 3つの規制リストから素材ごとのウォッチリスト構築。"
        "ECHA SVHC = EU高懸念物質、METI特定重要物資 = 日本経済安保、Stockholm POPs = 国際残留性有機汚染物質。"
    )

    sub_tab1, sub_tab2, sub_tab3, sub_tab4 = st.tabs(["🇪🇺 ECHA SVHC", "🇯🇵 METI 特定重要物資", "🌐 Stockholm POPs", "🔗 CAS横串検索"])

    with sub_tab1:
        if svhc_p is None:
            st.error("`data/echa/svhc_*.parquet` なし。")
        else:
            con = duckdb.connect(":memory:")
            con.execute(f"CREATE VIEW svhc AS SELECT * FROM '{svhc_p}'")
            total = con.execute("SELECT COUNT(*) FROM svhc").fetchone()[0]
            with_cas = con.execute("SELECT COUNT(*) FROM svhc WHERE cas_number IS NOT NULL AND cas_number != '-'").fetchone()[0]
            latest = con.execute("SELECT MAX(date_of_inclusion) FROM svhc").fetchone()[0]
            reasons = con.execute("SELECT COUNT(DISTINCT reason) FROM svhc").fetchone()[0]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("SVHC 総数", total)
            c2.metric("CAS番号付き", f"{with_cas} / {total}")
            c3.metric("最新収載", str(latest)[:10] if latest else "—")
            c4.metric("収載理由 種類", reasons)
            st.caption(f"データ: `{svhc_p.name}` | source: ECHA Candidate List")

            st.markdown("**収載理由 Top 10**")
            reason_df = con.execute(
                "SELECT reason, COUNT(*) AS cnt FROM svhc GROUP BY reason ORDER BY cnt DESC LIMIT 10"
            ).df()
            fig = px.bar(
                reason_df, x="cnt", y="reason", orientation="h",
                color_discrete_sequence=[ACCENT],
                labels={"cnt": "件数", "reason": ""},
            )
            fig.update_traces(hovertemplate="<b>%{y}</b><br>%{x}件<extra></extra>")
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(styled_fig(fig, height=320), use_container_width=True)

            st.markdown("**年次収載トレンド（規制リスクの早期警報）**")
            yearly = con.execute(
                """SELECT EXTRACT(YEAR FROM date_of_inclusion) AS year, COUNT(*) AS additions
                   FROM svhc WHERE date_of_inclusion IS NOT NULL
                   GROUP BY year ORDER BY year"""
            ).df()
            if not yearly.empty:
                yearly["year"] = yearly["year"].astype(int)
                fig = px.bar(
                    yearly, x="year", y="additions",
                    color_discrete_sequence=[ACCENT_LIGHT],
                    labels={"year": "年", "additions": "新規収載数"},
                )
                fig.update_traces(hovertemplate="<b>%{x}</b>年: %{y}件<extra></extra>")
                st.plotly_chart(styled_fig(fig, height=260), use_container_width=True)

            st.markdown("**直近10件（規制追加 = 該当素材は将来制限の可能性）**")
            recent = con.execute(
                """SELECT date_of_inclusion, substance_name, cas_number, reason FROM svhc
                   ORDER BY date_of_inclusion DESC NULLS LAST LIMIT 10"""
            ).df()
            recent["date_of_inclusion"] = recent["date_of_inclusion"].astype(str).str[:10]
            recent.columns = ["収載日", "物質名", "CAS番号", "理由"]
            st.dataframe(recent, use_container_width=True, hide_index=True)

    with sub_tab2:
        if meti_p is None:
            st.error("`data/regulations/meti_critical_*.parquet` なし。")
        else:
            meti = pd.read_parquet(meti_p)
            st.metric("特定重要物資 指定数", len(meti))
            st.caption(f"データ: `{meti_p.name}` | source: 経産省 経済安全保障推進法")
            st.markdown("**カテゴリ別**")
            cat_count = meti["category"].value_counts()
            st.bar_chart(cat_count, height=240)
            disp = meti[["id", "name_ja", "name_en", "category", "designated_date"]].copy()
            disp.columns = ["ID", "名称（日）", "名称（英）", "カテゴリ", "指定日"]
            st.dataframe(disp, use_container_width=True, hide_index=True)

    with sub_tab3:
        if pops_p is None:
            st.error("`data/regulations/pops_*.parquet` なし。")
        else:
            pops = pd.read_parquet(pops_p)
            c1, c2, c3 = st.columns(3)
            c1.metric("Annex A (廃絶)", (pops["annex"].str.startswith("A")).sum())
            c2.metric("Annex B (制限)", (pops["annex"].str.startswith("B")).sum())
            c3.metric("Annex C (非意図的)", (pops["annex"].str.contains("C")).sum())
            st.caption(f"データ: `{pops_p.name}` | source: Stockholm Convention COP")
            st.markdown("**タイプ別**")
            st.bar_chart(pops["type"].value_counts(), height=240)
            disp = pops[["id", "name_en", "cas", "annex", "type"]].copy()
            disp.columns = ["ID", "物質名", "CAS", "Annex", "タイプ"]
            st.dataframe(disp, use_container_width=True, hide_index=True)

    with sub_tab4:
        q = st.text_input("CAS番号で複数規制リストを横串検索 (例: 110-54-3, 50-29-3, 1763-23-1)", "")
        if q:
            cas = q.strip()
            results = []
            if svhc_p:
                con = duckdb.connect(":memory:")
                con.execute(f"CREATE VIEW svhc AS SELECT * FROM '{svhc_p}'")
                hit = con.execute(
                    "SELECT substance_name, date_of_inclusion, reason FROM svhc WHERE cas_number = ?", [cas]
                ).df()
                if not hit.empty:
                    results.append(("ECHA SVHC (EU)", hit.iloc[0]["substance_name"], f"{str(hit.iloc[0]['date_of_inclusion'])[:10]} | {hit.iloc[0]['reason']}"))
            if pops_p:
                pops = pd.read_parquet(pops_p)
                phit = pops[pops["cas"] == cas]
                if not phit.empty:
                    results.append(("Stockholm POPs", phit.iloc[0]["name_en"], f"Annex {phit.iloc[0]['annex']} | {phit.iloc[0]['type']}"))
            if results:
                st.success(f"CAS {cas} は {len(results)} 規制リストに該当")
                for src, name, detail in results:
                    st.markdown(f"- **{src}**: {name}  \n  　{detail}")
            else:
                st.info(f"CAS {cas} は現在ingest済の規制リストには該当なし。")


# ---------- tab 6 ----------
def render_axis6():
    sec_p = latest_parquet(SEC_DIR, "filings_8k")

    st.info(
        "**軸6「過去の供給途絶」** | SEC EDGAR 8-K（米化学メジャー15社の臨時開示）。"
        "Item 8.01 (Other Events) と Item 2.06 (Material Impairments) が FM 発令・大規模事故・撤退の主な箱。"
        "出現頻度がその企業/業界のオペレーションリスクの粗い代理指標。"
    )

    if sec_p is None:
        st.error("`data/sec/filings_8k_*.parquet` なし。`uv run python ingest/sec_8k.py` 実行。")
        return

    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW sec AS SELECT * FROM '{sec_p}'")
    total = con.execute("SELECT COUNT(*) FROM sec").fetchone()[0]
    cos = con.execute("SELECT COUNT(DISTINCT ticker) FROM sec").fetchone()[0]
    st.caption(f"データ: `{sec_p.name}` ({total:,} filings, {cos} companies, since 2023)")

    SUPPLY_ITEMS = ["1.02", "1.03", "2.04", "2.06", "8.01"]
    supply_filter = ",".join(f"'{x}'" for x in SUPPLY_ITEMS)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("全 8-K filings", total)
    sd_count = con.execute(f"""
        SELECT COUNT(*) FROM sec
        WHERE list_has(string_split(items, ','), '8.01')
           OR list_has(string_split(items, ','), '2.06')
           OR list_has(string_split(items, ','), '2.04')
           OR list_has(string_split(items, ','), '1.02')
           OR list_has(string_split(items, ','), '1.03')
    """).fetchone()[0]
    c2.metric("供給途絶関連 (推定)", sd_count, help="Item 1.02/1.03/2.04/2.06/8.01 を含むfiling数")
    earliest = con.execute("SELECT MIN(filing_date) FROM sec").fetchone()[0]
    latest = con.execute("SELECT MAX(filing_date) FROM sec").fetchone()[0]
    c3.metric("最初の filing", earliest)
    c4.metric("最新の filing", latest)

    st.markdown("**企業別 8-K filing数（2023年以降）**")
    by_co = con.execute("""
        SELECT ticker, COUNT(*) AS filings,
               COUNT(*) FILTER (WHERE list_has(string_split(items, ','), '8.01')) AS item_801,
               COUNT(*) FILTER (WHERE list_has(string_split(items, ','), '2.06')) AS item_206
        FROM sec GROUP BY ticker ORDER BY filings DESC
    """).df()
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=by_co["ticker"], y=by_co["filings"],
        marker_color=ACCENT, name="全filing",
        customdata=by_co[["item_801", "item_206"]].values,
        hovertemplate="<b>%{x}</b><br>全filing: %{y}<br>Item 8.01: %{customdata[0]}<br>Item 2.06: %{customdata[1]}<extra></extra>",
    ))
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title="filing数")
    st.plotly_chart(styled_fig(fig, height=300), use_container_width=True)

    st.markdown("**Item 8.01 (Other Events) の頻度 — FM・事故・大規模イベント候補**")
    item_801 = con.execute("""
        SELECT filing_date, ticker, company_name, items, primary_desc, accession_url
        FROM sec
        WHERE list_has(string_split(items, ','), '8.01')
        ORDER BY filing_date DESC LIMIT 25
    """).df()
    if not item_801.empty:
        item_801["link"] = item_801["accession_url"].map(lambda u: f"[開示]({u})")
        disp = item_801[["filing_date", "ticker", "company_name", "items", "primary_desc", "link"]]
        disp.columns = ["日付", "Ticker", "企業名", "Items", "種別", "リンク"]
        st.dataframe(disp, use_container_width=True, hide_index=True)

    # LLM-classified subset
    classified_p = latest_parquet(SEC_DIR, "item801_classified")
    if classified_p is not None:
        st.divider()
        st.subheader("🤖 LLM分類 — Item 8.01 直近30件の詳細イベント分類")
        st.caption("Claude Sonnet 4.6で各filingの本文を読み、event_type / supply_relevance を構造化")
        cls_df = pd.read_parquet(classified_p)
        # Event type breakdown
        col_evt, col_sup = st.columns(2)
        with col_evt:
            st.markdown("**Event type 内訳**")
            evt_count = cls_df["event_type"].value_counts()
            fig = px.bar(
                x=evt_count.values, y=evt_count.index, orientation="h",
                color_discrete_sequence=[ACCENT],
                labels={"x": "件数", "y": ""},
            )
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(styled_fig(fig, height=280), use_container_width=True)
        with col_sup:
            st.markdown("**Supply relevance 内訳**")
            sup_count = cls_df["supply_relevance"].value_counts()
            colors = {"HIGH": DANGER, "MED": "#F59E0B", "LOW": "#10B981"}
            fig = px.pie(
                values=sup_count.values, names=sup_count.index,
                color=sup_count.index, color_discrete_map=colors, hole=0.4,
            )
            fig.update_traces(textinfo="label+value")
            st.plotly_chart(styled_fig(fig, height=280), use_container_width=True)

        st.markdown("**HIGH 供給関連イベントのみ抽出**")
        high = cls_df[cls_df["supply_relevance"] == "HIGH"].sort_values("filing_date", ascending=False)
        if high.empty:
            st.success("直近30件にHIGH供給関連イベントなし")
        else:
            high_disp = high[["filing_date", "ticker", "event_type", "summary_ja", "key_facility", "key_product", "accession_url"]].copy()
            high_disp["link"] = high_disp["accession_url"].map(lambda u: f"[開示]({u})")
            high_disp = high_disp.drop(columns=["accession_url"])
            high_disp.columns = ["日付", "Ticker", "Event Type", "要約 (LLM生成)", "施設", "製品", "リンク"]
            st.dataframe(high_disp, use_container_width=True, hide_index=True)

        with st.expander("全分類結果"):
            full = cls_df[["filing_date", "ticker", "event_type", "supply_relevance", "summary_ja", "accession_url"]].copy()
            full["link"] = full["accession_url"].map(lambda u: f"[開示]({u})")
            full = full.drop(columns=["accession_url"])
            full.columns = ["日付", "Ticker", "Event Type", "影響度", "要約", "リンク"]
            st.dataframe(full, use_container_width=True, hide_index=True)

    with st.expander("Item 2.06 (Material Impairments) 全件"):
        item_206 = con.execute("""
            SELECT filing_date, ticker, company_name, items, primary_desc, accession_url
            FROM sec WHERE list_has(string_split(items, ','), '2.06') ORDER BY filing_date DESC
        """).df()
        if item_206.empty:
            st.info("該当なし")
        else:
            item_206["link"] = item_206["accession_url"].map(lambda u: f"[開示]({u})")
            disp = item_206[["filing_date", "ticker", "company_name", "primary_desc", "link"]]
            disp.columns = ["日付", "Ticker", "企業名", "種別", "リンク"]
            st.dataframe(disp, use_container_width=True, hide_index=True)


# ---------- tab 1 ----------
def render_axis1():
    p = latest_parquet(EDINET_DIR, "capacity_snippets")

    st.info(
        "**軸1「生産能力・新増設」** | "
        "化学系443社の有報・統合報告書・中期経営計画から「生産能力」「年産」「設備能力」等のキーワード周辺テキストを抽出。"
        "現在は**スニペット索引**段階。構造化（製品×工場×年間能力 表化）はLLM抽出を別ステップで予定。"
    )
    if p is None:
        st.error("`data/edinet/capacity_snippets_*.parquet` なし。`uv run python ingest/edinet_capacity.py` 実行。")
        return

    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW snip AS SELECT * FROM '{p}'")
    total = con.execute("SELECT COUNT(*) FROM snip").fetchone()[0]
    companies = con.execute("SELECT COUNT(DISTINCT company) FROM snip").fetchone()[0]
    doctypes = con.execute("SELECT COUNT(DISTINCT doctype) FROM snip").fetchone()[0]
    st.caption(f"データ: `{p.name}` ({total:,} snippets, {companies} companies, {doctypes} doctypes)")

    c1, c2, c3 = st.columns(3)
    c1.metric("スニペット総数", f"{total:,}")
    c2.metric("企業数（言及あり）", companies)
    c3.metric("文書種類", doctypes)

    st.markdown("**文書種別の内訳**")
    dt = con.execute("SELECT doctype, COUNT(*) AS cnt FROM snip GROUP BY doctype ORDER BY cnt DESC").df()
    st.bar_chart(dt.set_index("doctype")["cnt"], height=240)

    st.markdown("**スニペット数 Top 20 企業（生産能力に関する記述が多い ＝ 投資・再編が活発）**")
    top_co = con.execute("SELECT company, COUNT(*) AS cnt FROM snip GROUP BY company ORDER BY cnt DESC LIMIT 20").df()
    st.bar_chart(top_co.set_index("company")["cnt"], height=320)

    st.divider()
    st.markdown("**スニペット閲覧**")
    co_list = con.execute("SELECT DISTINCT company FROM snip ORDER BY company").df()["company"].tolist()
    chosen = st.selectbox("企業", co_list, key="ax1_co")
    snips = con.execute(
        """SELECT period, doctype, snippet, file_path FROM snip WHERE company = ?
           ORDER BY period DESC, doctype""",
        [chosen],
    ).df()
    if snips.empty:
        st.info("該当データなし")
    else:
        for _, r in snips.iterrows():
            with st.expander(f"[{r['period']}] {r['doctype']} — {r['snippet'][:80]}..."):
                st.markdown(f"> {r['snippet']}")
                st.caption(f"出典: `{r['file_path']}`")


# ---------- tab 7 ----------
def render_axis7():
    p = latest_parquet(WB_DIR, "prices_monthly")

    st.info(
        "**軸7「価格変動性」** | World Bank Pink Sheet 月次商品価格（1960年〜現在）。"
        "ゴム TSR20/RSS3、原油（Brent/WTI/Dubai）、天然ガス（JP/EU/US）、ベース金属など、"
        "rubber/tire/petchem 関連の主要15品目で月次ボラティリティと長期トレンドを可視化。"
    )

    if p is None:
        st.error("`data/worldbank/prices_monthly_*.parquet` なし。`uv run python ingest/worldbank_prices.py` 実行。")
        return

    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW prices AS SELECT * FROM '{p}'")
    total = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    commodities = con.execute("SELECT COUNT(DISTINCT commodity) FROM prices").fetchone()[0]
    drange = con.execute("SELECT MIN(date), MAX(date) FROM prices").fetchone()
    st.caption(f"データ: `{p.name}` ({total:,} rows, {commodities} commodities, {drange[0].date()}〜{drange[1].date()})")

    co_list = con.execute("SELECT DISTINCT commodity, name FROM prices ORDER BY commodity").df()
    co_map = dict(zip(co_list["commodity"], co_list["name"]))
    selected = st.selectbox(
        "商品",
        co_list["commodity"].tolist(),
        format_func=lambda c: f"{co_map.get(c, c)} ({c})",
        index=co_list["commodity"].tolist().index("RUBBER_TSR20") if "RUBBER_TSR20" in co_map else 0,
        key="ax7_co",
    )

    years_back = st.slider("表示期間（年）", 1, 30, 10, key="ax7_years")

    cutoff = pd.Timestamp.now() - pd.DateOffset(years=years_back)
    df = con.execute(
        """SELECT date, price, unit FROM prices
           WHERE commodity = ? AND date >= ?
           ORDER BY date""",
        [selected, cutoff],
    ).df()

    if df.empty:
        st.warning("該当データなし。")
        return

    unit = df["unit"].iloc[0]
    df["yoy_pct"] = df["price"].pct_change(12) * 100
    df["rolling_vol_12m"] = df["price"].pct_change().rolling(12).std() * (12 ** 0.5) * 100  # annualized vol %

    latest_p = df.iloc[-1]["price"]
    latest_yoy = df.iloc[-1]["yoy_pct"]
    avg_vol = df["rolling_vol_12m"].dropna().mean()
    max_p = df["price"].max()
    min_p = df["price"].min()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("直近価格", f"{latest_p:,.2f} {unit}")
    c2.metric("YoY 変化", f"{latest_yoy:+.1f}%" if pd.notna(latest_yoy) else "—")
    c3.metric("年率ボラティリティ平均", f"{avg_vol:.1f}%", help="12ヶ月rolling, 月次リターンの年率化標準偏差")
    c4.metric("レンジ", f"{min_p:.2f} – {max_p:.2f}")

    st.subheader(f"{co_map.get(selected, selected)} — 月次価格推移")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["price"], mode="lines", name="価格",
        line=dict(color=ACCENT, width=2),
        hovertemplate=f"<b>%{{x|%Y-%m}}</b><br>%{{y:,.2f}} {unit}<extra></extra>",
    ))
    fig.update_yaxes(title=unit)
    st.plotly_chart(styled_fig(fig, height=340), use_container_width=True)

    col_yoy, col_vol = st.columns(2)
    with col_yoy:
        st.markdown("**YoY 変化率（前年同月比）**")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["yoy_pct"], mode="lines",
            line=dict(color=ACCENT, width=2), fill="tozeroy",
            fillcolor="rgba(15,118,110,0.15)",
            hovertemplate="<b>%{x|%Y-%m}</b><br>%{y:+.1f}%<extra></extra>",
        ))
        fig.add_hline(y=0, line_color=MUTED, line_width=1)
        fig.update_yaxes(title="%", ticksuffix="%")
        st.plotly_chart(styled_fig(fig, height=260), use_container_width=True)
    with col_vol:
        st.markdown("**年率ボラティリティ（12ヶ月rolling）**")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["rolling_vol_12m"], mode="lines",
            line=dict(color="#7C3AED", width=2),
            hovertemplate="<b>%{x|%Y-%m}</b><br>vol: %{y:.1f}%<extra></extra>",
        ))
        fig.update_yaxes(title="%", ticksuffix="%", rangemode="tozero")
        st.plotly_chart(styled_fig(fig, height=260), use_container_width=True)

    st.divider()
    st.subheader("全商品の直近YoY変化率")
    latest = con.execute(
        """WITH ranked AS (
             SELECT commodity, name, date, price,
                    LAG(price, 12) OVER (PARTITION BY commodity ORDER BY date) AS price_12m_ago,
                    ROW_NUMBER() OVER (PARTITION BY commodity ORDER BY date DESC) AS rn
             FROM prices
           )
           SELECT name, commodity, date, price,
                  (price / price_12m_ago - 1) * 100 AS yoy_pct
           FROM ranked WHERE rn = 1 ORDER BY yoy_pct DESC NULLS LAST"""
    ).df()
    latest["price"] = latest["price"].map(lambda v: f"{v:,.2f}")
    latest["yoy_pct"] = latest["yoy_pct"].map(lambda v: f"{v:+.1f}%" if pd.notna(v) else "—")
    latest["date"] = latest["date"].astype(str).str[:10]
    latest.columns = ["商品", "コード", "直近月", "価格", "YoY"]
    st.dataframe(latest, use_container_width=True, hide_index=True)


# ---------- tab 2 ----------
def render_axis2():
    parquet = latest_parquet(COMTRADE_DIR, "trade")
    if parquet is None:
        st.error("`data/comtrade/trade_*.parquet` なし。")
        return

    st.info(
        "**軸2「需給バランス」(proxy)** | "
        "本格的な軸2は石化協月次稼働率/METI生産動態統計が必要だが、proxyとして "
        "**UN Comtradeの日本側貿易フロー** から「純輸出比率」(=(輸出-輸入)/総貿易額) を計算。"
        "+1に近い=日本が完全に輸出超過(国内供給過剰)、-1に近い=完全に輸入依存。"
        "時系列変化が需給逼迫/緩和の早期警報になる。"
    )

    hs_desc = load_hs_desc()
    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW trade AS SELECT * FROM '{parquet}'")

    # All HS codes with both X and M flows for Japan
    df_all = con.execute("""
        SELECT
          cmdCode, period,
          SUM(CASE WHEN flowCode='X' THEN primaryValue ELSE 0 END) AS exports,
          SUM(CASE WHEN flowCode='M' THEN primaryValue ELSE 0 END) AS imports,
          (SUM(CASE WHEN flowCode='X' THEN primaryValue ELSE 0 END)
           - SUM(CASE WHEN flowCode='M' THEN primaryValue ELSE 0 END))
           / NULLIF(SUM(primaryValue), 0) AS net_export_ratio
        FROM trade
        WHERE reporterCode = 392 AND partner2Code = 0 AND primaryValue > 0
        GROUP BY cmdCode, period
        HAVING SUM(primaryValue) > 0
    """).df()

    if df_all.empty:
        st.warning("日本の貿易データなし。")
        return

    st.caption(f"データ: `{parquet.name}` | 日本 (M49=392) 視点")

    # Latest period snapshot
    latest_period = df_all["period"].max()
    latest = df_all[df_all["period"] == latest_period].copy()
    latest["material"] = latest["cmdCode"].map(lambda c: f"{c} — {hs_desc.get(c, '?')[:30]}")
    latest = latest.sort_values("net_export_ratio")

    c1, c2, c3 = st.columns(3)
    c1.metric("対象期間", latest_period)
    c2.metric("対象HS数", len(latest))
    importer = (latest["net_export_ratio"] < 0).sum()
    c3.metric("輸入超過HS", importer, help="日本が純輸入国の素材数（軸2リスク高）")

    st.subheader(f"{latest_period}年 — HS別 純輸出比率（日本視点）")
    fig = px.bar(
        latest, x="net_export_ratio", y="material", orientation="h",
        color="net_export_ratio",
        color_continuous_scale=[(0, DANGER), (0.5, "#F59E0B"), (1, "#10B981")],
        range_color=[-1, 1],
        labels={"net_export_ratio": "純輸出比率 (-1=輸入依存, +1=輸出超過)", "material": ""},
    )
    fig.add_vline(x=0, line_dash="dash", line_color=MUTED)
    fig.update_layout(coloraxis_showscale=False, showlegend=False)
    st.plotly_chart(styled_fig(fig, height=500), use_container_width=True)

    # Time series for a selected HS
    st.subheader("HS別 純輸出比率の年次推移")
    hs_options = sorted(df_all["cmdCode"].unique())
    selected_hs = st.selectbox(
        "HS6コード", hs_options,
        format_func=lambda c: f"{c} — {hs_desc.get(c, '?')[:60]}",
        key="ax2_hs",
    )
    trend = df_all[df_all["cmdCode"] == selected_hs].sort_values("period")
    if not trend.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=trend["period"], y=trend["net_export_ratio"],
            mode="lines+markers", line=dict(color=ACCENT, width=3), marker=dict(size=10),
            hovertemplate="<b>%{x}</b><br>純輸出比率: %{y:.2f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_color=MUTED, line_dash="dash", annotation_text="均衡 (0)")
        fig.update_yaxes(range=[-1, 1], title="純輸出比率")
        fig.update_xaxes(title="期間")
        st.plotly_chart(styled_fig(fig, height=300), use_container_width=True)

        # Show raw numbers
        with st.expander("生数値"):
            disp = trend[["period", "exports", "imports", "net_export_ratio"]].copy()
            disp["exports"] = disp["exports"].map(lambda v: f"${v/1e6:,.1f}M")
            disp["imports"] = disp["imports"].map(lambda v: f"${v/1e6:,.1f}M")
            disp["net_export_ratio"] = disp["net_export_ratio"].map(lambda v: f"{v:+.3f}")
            disp.columns = ["期間", "輸出", "輸入", "純輸出比率"]
            st.dataframe(disp, use_container_width=True, hide_index=True)

    st.caption("📝 注: これは「日本の貿易フロー」由来のproxy。本格的な需給バランス（稼働率・在庫水準）は別途METI/JPCAデータ整備で精緻化予定。")


# ---------- tab 3 ----------
def render_axis3():
    p = latest_parquet(SUPPLIER_DIR, "jp_supplier_count")

    st.info(
        "**軸3「サプライヤー集中度」(proxy)** | "
        "本格的なHHIには各社の生産能力数値が必要だが、EDINET XBRLでは構造化されていない。"
        "暫定proxy: 「素材名を有報/中計/サステナレポートで言及している」JP上場企業の数を数え、"
        "「3社以下＝高集中」「4-10社＝中集中」「11社以上＝低集中」の3バンドで色分け。"
        "国内供給多様性のラフな代理指標として、軸4（global集中度）と組み合わせて読む。"
    )

    if p is None:
        st.error("`data/supplier/jp_supplier_count_*.parquet` なし。`uv run python ingest/supplier_concentration.py` 実行。")
        return

    df = pd.read_parquet(p)
    st.caption(f"データ: `{p.name}` ({len(df)} materials, JP-listed chemical universe 385社が母集団)")

    BAND_LABEL = {
        "high_concentration": "🔴 高集中 (3社以下)",
        "moderate_concentration": "🟡 中集中 (4-10社)",
        "low_concentration": "🟢 低集中 (11社以上)",
        "no_data": "⚪ データなし",
    }
    BAND_ORDER = ["high_concentration", "moderate_concentration", "low_concentration", "no_data"]

    counts = df["concentration_band"].value_counts().reindex(BAND_ORDER, fill_value=0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 高集中", counts["high_concentration"], help="JP上場サプライヤー≤3社の素材数")
    c2.metric("🟡 中集中", counts["moderate_concentration"])
    c3.metric("🟢 低集中", counts["low_concentration"])
    c4.metric("⚪ データなし", counts["no_data"])

    st.markdown("**🔴 高集中素材リスト（国内供給リスク要監視）**")
    high = df[df["concentration_band"] == "high_concentration"].sort_values("jp_supplier_count")
    if not high.empty:
        disp = high[["name_ja", "category", "jp_supplier_count", "top_companies"]].copy()
        disp.columns = ["素材", "カテゴリ", "JPサプライヤー数", "Top企業"]
        st.dataframe(disp, use_container_width=True, hide_index=True)
    else:
        st.success("高集中素材なし")

    st.markdown("**全素材ランキング (JP上場サプライヤー数の昇順)**")
    sorted_df = df.sort_values("jp_supplier_count")
    sorted_df["band_label"] = sorted_df["concentration_band"].map(BAND_LABEL)
    fig = px.bar(
        sorted_df,
        x="jp_supplier_count", y="name_ja", orientation="h",
        color="concentration_band",
        color_discrete_map={
            "high_concentration": DANGER,
            "moderate_concentration": "#F59E0B",
            "low_concentration": "#10B981",
            "no_data": MUTED,
        },
        hover_data={"top_companies": True, "concentration_band": False, "name_ja": False},
        labels={"jp_supplier_count": "JP上場サプライヤー数", "name_ja": ""},
    )
    fig.update_layout(showlegend=False)
    st.plotly_chart(styled_fig(fig, height=520), use_container_width=True)

    with st.expander("全データ"):
        disp = df.copy()
        disp["band_label"] = disp["concentration_band"].map(BAND_LABEL)
        disp = disp[["name_ja", "name_en", "category", "jp_supplier_count", "band_label", "top_companies"]]
        disp.columns = ["素材", "英名", "カテゴリ", "サプライヤー数", "集中度バンド", "Top企業"]
        st.dataframe(disp, use_container_width=True, hide_index=True)


# ---------- cross-axis tab (chemicals.parquet-driven) ----------
@st.cache_data
def load_all_chemicals_df():
    return cl.all_chemicals()


def render_cross():
    chem_df = load_all_chemicals_df()
    if chem_df.empty:
        st.error("`data/chemicals/chemicals.parquet` なし。`ingest/chemicals/seed_compile.py → pubchem_ingest.py → hs_map.py` 実行。")
        return

    pinned_count = chem_df["is_pinned"].sum()
    st.info(
        "**🔗 素材横串ビュー** | 化合物マスタDB (469物質, CAS番号で正規化) から1つ選択すると、"
        "7軸全部のデータが集約される。⭐がついた物質はピン留め（鉄板スコープ）、"
        "残りは規制リスト・主要工業化学品由来の拡張スコープ。"
    )

    # Search + selection
    col_search, col_cat = st.columns([2, 1])
    with col_search:
        query = st.text_input(
            "🔍 物質名 / CAS番号で検索（部分一致）",
            "",
            placeholder="例: ethylene / 74-85-1 / フッ素 / SBR",
            key="cross_search",
        )
    with col_cat:
        categories_meta = cl.categories()
        cat_options = ["（全カテゴリ）"] + [c["id"] for c in categories_meta]
        cat_labels = {c["id"]: c["name_ja"] for c in categories_meta}
        selected_cat = st.selectbox(
            "カテゴリ絞り込み",
            cat_options,
            format_func=lambda c: c if c == "（全カテゴリ）" else f"{cat_labels.get(c, c)} ({c})",
            key="cross_cat",
        )

    filtered = chem_df.copy()
    if selected_cat != "（全カテゴリ）":
        filtered = filtered[filtered["category_norm"] == selected_cat]
    if query.strip():
        q = query.strip().lower()
        mask = (
            filtered["cas"].str.lower().str.contains(q, na=False)
            | filtered["name_en"].str.lower().str.contains(q, na=False)
            | filtered["iupac_name"].fillna("").str.lower().str.contains(q, na=False)
            | filtered["top_synonym"].fillna("").str.lower().str.contains(q, na=False)
        )
        filtered = filtered[mask]

    if filtered.empty:
        st.warning(f"該当物質なし。検索を緩めるか、{pinned_count}件のピン留め物質に戻してください。")
        return

    st.caption(f"候補 {len(filtered)} 件（全 {len(chem_df)} 物質中、ピン留め ⭐ {pinned_count} 件）")

    def fmt_row(cas: str) -> str:
        r = filtered[filtered["cas"] == cas].iloc[0]
        pin = "⭐ " if r["is_pinned"] else ""
        nm = r["_display_name"] or cas
        cat = r["category_label_ja"]
        return f"{pin}{nm}　[{cas}]　— {cat}"

    cas_options = filtered["cas"].tolist()
    selected_cas = st.selectbox(
        "物質を選択",
        cas_options,
        format_func=fmt_row,
        key="cross_cas",
    )

    chem = cl.get_chemical(selected_cas)
    if not chem:
        st.error("物質詳細の取得に失敗")
        return

    # ---- Header metadata ----
    pin_badge = "⭐ ピン留め" if chem["is_pinned"] else ""
    st.markdown(f"## {chem['display_name']}　<small>{pin_badge}</small>", unsafe_allow_html=True)
    if chem.get("pinned_note"):
        st.caption(f"📌 {chem['pinned_note']}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("CAS番号", chem["cas"])
    cat_labels = {c["id"]: c["name_ja"] for c in cl.categories()}
    c2.metric("カテゴリ", cat_labels.get(chem.get("category_norm"), chem.get("category_norm") or "—"))
    c3.metric("分子式", chem.get("molecular_formula") or "—")
    mw = chem.get("molecular_weight")
    c4.metric("分子量", f"{mw:.2f}" if mw and not pd.isna(mw) else "—")
    pcid = chem.get("pubchem_cid")
    if pcid and not pd.isna(pcid):
        c5.markdown(f"**PubChem**  \n[CID {int(pcid)}](https://pubchem.ncbi.nlm.nih.gov/compound/{int(pcid)})")
    else:
        c5.metric("PubChem", "未取得")

    # HS codes line
    hs_exact = chem.get("hs6_exact") or []
    hs_chs = chem.get("hs_chapters") or []
    hs_text = ""
    if hs_exact:
        hs_text += f"**HS6 (確定)**: {', '.join(hs_exact)}　"
    if hs_chs:
        hs_text += f"**HSチャプター候補**: {', '.join(hs_chs)} （カテゴリ由来推定）"
    if hs_text:
        st.caption(hs_text)

    st.divider()

    # === Axis 4: HHI snapshot per exact HS6 ===
    st.subheader("🌐 軸4 地政学・原産地 — 直近の輸出集中度")
    trade_p = latest_parquet(COMTRADE_DIR, "trade")
    reporters = load_reporters()
    if trade_p and hs_exact:
        con = duckdb.connect(":memory:")
        con.execute(f"CREATE VIEW trade AS SELECT * FROM '{trade_p}'")
        cols = st.columns(min(len(hs_exact), 3))
        for i, hs in enumerate(hs_exact):
            with cols[i % len(cols)]:
                df = con.execute(
                    """SELECT reporterCode, primaryValue FROM trade
                       WHERE cmdCode=? AND flowCode='X' AND partner2Code=0 AND primaryValue>0
                         AND period = (SELECT MAX(period) FROM trade WHERE cmdCode=?)
                       ORDER BY primaryValue DESC""",
                    [hs, hs],
                ).df()
                if df.empty:
                    st.warning(f"HS {hs}: 軸4データ未ingest")
                    continue
                total = df["primaryValue"].sum()
                df["share"] = df["primaryValue"] / total * 100
                hhi = (df["share"] ** 2).sum()
                top1 = df.iloc[0]
                top1_name = reporters.get(top1["reporterCode"], f"M49 {top1['reporterCode']}")
                st.markdown(f"**HS {hs}** ({total/1e9:.2f}B USD輸出, {len(df)}国)")
                st.metric("HHI", f"{hhi:,.0f}", help="<1500 低 / >2500 高集中")
                st.metric("Top-1", f"{top1['share']:.1f}%", help=f"{top1_name}")
    elif hs_chs:
        st.info(
            f"HS6 確定マッピングなし。カテゴリ由来のチャプター候補: {', '.join(hs_chs)}。"
            "HS6 のマッピング精緻化は LLM 補助で別途予定。"
        )
    else:
        st.info("HSコード未マッピング。")

    st.divider()

    # === Axis 5: regulation hits by CAS ===
    st.subheader("📋 軸5 規制リスク — CAS番号での該当ヒット")
    svhc_p = latest_parquet(ECHA_DIR, "svhc")
    pops_p = latest_parquet(REG_DIR, "pops")
    hits_total = 0
    if svhc_p:
        con = duckdb.connect()
        con.execute(f"CREATE VIEW svhc AS SELECT * FROM '{svhc_p}'")
        hit = con.execute("SELECT substance_name, date_of_inclusion, reason FROM svhc WHERE cas_number = ?", [chem["cas"]]).df()
        if not hit.empty:
            hits_total += len(hit)
            st.error(f"🚨 ECHA SVHC: {len(hit)}件ヒット")
            hit["date_of_inclusion"] = hit["date_of_inclusion"].astype(str).str[:10]
            st.dataframe(hit, use_container_width=True, hide_index=True)
    if pops_p:
        pops = pd.read_parquet(pops_p)
        phit = pops[pops["cas"] == chem["cas"]]
        if not phit.empty:
            hits_total += len(phit)
            st.error(f"🚨 Stockholm POPs: {len(phit)}件ヒット (Annex {phit.iloc[0]['annex']})")
            st.dataframe(phit[["name_en", "annex", "type"]], use_container_width=True, hide_index=True)
    if hits_total == 0:
        st.success(f"✅ CAS {chem['cas']} は現時点で ECHA SVHC / Stockholm POPs に該当なし")

    st.divider()

    # === Axis 6: related company 8-K (only for pinned CAS with SEC tickers) ===
    st.subheader("💥 軸6 関連企業の供給途絶イベント (8-K)")
    sec_p = latest_parquet(SEC_DIR, "filings_8k")
    if sec_p and chem.get("sec_tickers"):
        con = duckdb.connect()
        con.execute(f"CREATE VIEW sec AS SELECT * FROM '{sec_p}'")
        tickers = chem["sec_tickers"]
        placeholders = ",".join(["?"] * len(tickers))
        df = con.execute(
            f"""SELECT filing_date, ticker, company_name, items, primary_desc, accession_url
               FROM sec
               WHERE ticker IN ({placeholders})
                 AND (list_has(string_split(items, ','), '8.01')
                      OR list_has(string_split(items, ','), '2.06')
                      OR list_has(string_split(items, ','), '1.02'))
               ORDER BY filing_date DESC LIMIT 20""",
            tickers,
        ).df()
        st.caption(f"関連企業: {', '.join(tickers)}")
        if df.empty:
            st.info("該当期間内に供給途絶系の臨時開示なし。")
        else:
            df["link"] = df["accession_url"].map(lambda u: f"[開示]({u})")
            disp = df[["filing_date", "ticker", "items", "primary_desc", "link"]]
            disp.columns = ["日付", "Ticker", "Items", "種別", "リンク"]
            st.dataframe(disp, use_container_width=True, hide_index=True)
    else:
        st.info(
            "本物質の SEC ticker マッピングなし。"
            "拡張スコープ物質の場合は materials_scope.yml に sec_tickers を追記するか、"
            "アジア/欧州企業の Disclosure Feed の追加が必要。"
        )

    st.divider()

    # === Axis 7: price chart ===
    st.subheader("💹 軸7 価格変動性")
    wb_p = latest_parquet(WB_DIR, "prices_monthly")
    if wb_p and chem.get("wb_commodity"):
        con = duckdb.connect()
        con.execute(f"CREATE VIEW prices AS SELECT * FROM '{wb_p}'")
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=10)
        df = con.execute(
            "SELECT date, price, unit, name FROM prices WHERE commodity = ? AND date >= ? ORDER BY date",
            [chem["wb_commodity"], cutoff],
        ).df()
        if df.empty:
            st.info("価格データなし")
        else:
            df["yoy_pct"] = df["price"].pct_change(12) * 100
            unit = df["unit"].iloc[0]
            latest = df.iloc[-1]
            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("最新価格", f"{latest['price']:.2f} {unit}", help=f"{str(latest['date'])[:10]}")
            cc2.metric("YoY", f"{latest['yoy_pct']:+.1f}%" if pd.notna(latest["yoy_pct"]) else "—")
            vol = df["price"].pct_change().std() * (12 ** 0.5) * 100
            cc3.metric("年率ボラティリティ", f"{vol:.1f}%")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["price"], mode="lines",
                line=dict(color=ACCENT, width=2),
                hovertemplate=f"<b>%{{x|%Y-%m}}</b><br>%{{y:,.2f}} {unit}<extra></extra>",
            ))
            fig.update_yaxes(title=unit)
            st.plotly_chart(styled_fig(fig, height=260), use_container_width=True)
    else:
        st.info(
            "World Bank Pink Sheet に直接の価格指標なし。"
            "原料連動（原油 CRUDE_BRENT, ナフサ等）で代用、または別データソース（FRED, NYMEX）の追加が必要。"
        )

    st.divider()

    # === Axis 1: capacity snippets ===
    st.subheader("🏭 軸1 生産能力・新増設 — 関連snippet")
    edinet_p = latest_parquet(EDINET_DIR, "capacity_snippets")
    keywords = cl.synonyms_for_search(chem["cas"])
    if edinet_p and keywords:
        con = duckdb.connect()
        con.execute(f"CREATE VIEW snip AS SELECT * FROM '{edinet_p}'")
        like_clauses = " OR ".join(["snippet LIKE ?"] * len(keywords))
        params = [f"%{k}%" for k in keywords]
        df = con.execute(
            f"""SELECT company, period, doctype, snippet
                FROM snip WHERE {like_clauses}
                ORDER BY period DESC LIMIT 15""",
            params,
        ).df()
        st.caption(f"検索キーワード: {', '.join(keywords)}")
        if df.empty:
            st.info("該当snippetなし")
        else:
            for _, r in df.iterrows():
                with st.expander(f"[{r['company']}] {r['period']} — {r['doctype']}"):
                    snippet = r["snippet"]
                    for kw in keywords:
                        snippet = snippet.replace(kw, f"**{kw}**")
                    st.markdown(f"> {snippet}")
    else:
        st.info("検索キーワード生成不可（物質名なし）")


# ---------- Top-level tabs ----------
tab_overview, tab_cross, tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
    ["🏠 Overview", "🔗 素材横串", "🏭 軸1 生産能力", "⚖️ 軸2 需給バランス", "🤝 軸3 サプライヤー集中", "🌐 軸4 地政学", "📋 軸5 規制リスク", "💥 軸6 供給途絶", "💹 軸7 価格変動性"]
)

with tab_overview:
    st.subheader("プロジェクト全体像")
    st.markdown(
        """
        化学品の購買・R&D担当者が素材検索時に直感的に**供給リスク**を把握できることを目指す。

        供給安定性は単一の指標ではなく、**生産能力 / 需給バランス / サプライヤー集中度 / 地政学 / 規制 / 過去事象 / 価格変動** の 7 要素で構成されると整理し、
        各要素について公開データ由来のプロキシ指標を機械算出してダッシュボード化した。

        - 各軸の単独タブで詳細を確認
        - 「🔗 素材横串」タブで個別物質の複数軸ビューを一括表示
        """
    )

    # Chemicals registry summary
    try:
        chem_df_summary = cl.all_chemicals()
        if not chem_df_summary.empty:
            total_chem = len(chem_df_summary)
            pinned_chem = int(chem_df_summary["is_pinned"].sum())
            with_cid = int((chem_df_summary["pubchem_fetch_status"] == "ok").sum())
            cats = chem_df_summary["category_norm"].nunique()
            ov1, ov2, ov3, ov4 = st.columns(4)
            ov1.metric("化合物マスタDB", f"{total_chem} 物質", help="CAS番号で正規化された全物質数")
            ov2.metric("⭐ ピン留め", f"{pinned_chem}", help="鉄板スコープ（タイヤ・ゴム中心）")
            ov3.metric("PubChem連携済", f"{with_cid}", help="PubChem CID取得 + 構造データあり")
            ov4.metric("カテゴリ", f"{cats}", help="モノマー/ポリマー/溶剤/無機等の分類数")
    except Exception:
        pass

    st.subheader("7軸プロキシ指標")
    progress = []
    for code, name, proxy, source in AXES:
        progress.append({
            "軸": code,
            "要素": name,
            "プロキシ指標": proxy,
            "データソース": source,
        })
    st.dataframe(pd.DataFrame(progress), use_container_width=True, hide_index=True)
    st.caption("各軸の詳細は上のタブから。")

with tab_cross:
    render_cross()

with tab1:
    render_axis1()

with tab2:
    render_axis2()

with tab3:
    render_axis3()

with tab4:
    render_axis4()

with tab5:
    render_axis5()

with tab6:
    render_axis6()

with tab7:
    render_axis7()
