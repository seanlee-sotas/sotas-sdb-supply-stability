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
import scoring  # noqa: E402
import scoring_llm  # noqa: E402
import gemini_client as gemini  # noqa: E402 (avoid stdlib `gc` collision)
import source_inspector  # noqa: E402

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

    st.divider()
    source_inspector.render_source("comtrade_trade", parquet, key_suffix="axis4")


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

    st.divider()
    st.markdown("### 📂 ソース生データ — 軸5 規制リスク")
    source_inspector.render_source("echa_svhc", svhc_p)
    source_inspector.render_source("meti_critical", meti_p)
    source_inspector.render_source("pops", pops_p)


EDINET_EXTRA_DIR = ROOT / "data" / "edinet"
DART_DIR = ROOT / "data" / "dart"
TDNET_DIR = ROOT / "data" / "tdnet"
TWSE_DIR = ROOT / "data" / "twse"
NITE_DIR = ROOT / "data" / "nite"
AXIS6_CLS_DIR = ROOT / "data" / "axis6_classified"


def _render_disruption_subtab(source_id: str, parquet_path, *, columns, classified_glob: str | None = None):
    """Helper for each axis6 subsource subtab — table view + LLM-classified HIGH filter."""
    if parquet_path is None or not Path(parquet_path).exists():
        st.warning("データ未取得。対応 ingest スクリプトを実行してください。")
        return
    con = duckdb.connect()
    try:
        df = con.execute(f"SELECT {', '.join(columns)} FROM '{parquet_path}' ORDER BY 1 DESC LIMIT 100").df()
    except Exception as e:
        st.error(f"読み込み失敗: {e}")
        return
    st.caption(f"`{Path(parquet_path).name}` — 直近100件")
    st.dataframe(df, use_container_width=True, hide_index=True, height=400)

    # Optional LLM-classified HIGH supply_relevance rows for this source
    if classified_glob:
        from glob import glob
        files = sorted(glob(str(AXIS6_CLS_DIR / classified_glob)))
        if files:
            cls = pd.read_parquet(files[-1])
            high = cls[cls["supply_relevance"] == "HIGH"]
            if len(high):
                st.markdown(f"**🚨 LLM分類 HIGH 供給関連イベント ({len(high)}件)**")
                st.dataframe(
                    high[["source_id", "event_type", "summary_ja", "key_facility", "key_product"]],
                    use_container_width=True, hide_index=True, height=240,
                )
            else:
                st.success("✅ 直近の分類結果に HIGH 供給関連イベントなし")


def _load_axis6_classified() -> pd.DataFrame:
    """Union all axis6_classified parquets + SEC item801_classified into a single
    dataframe with normalised columns (source, source_id, event_type, summary_ja,
    supply_relevance, key_facility, key_product)."""
    from glob import glob
    dfs = []

    # 1. JP/KR/TW: data/axis6_classified/<source>_classified_*.parquet
    files = sorted(glob(str(AXIS6_CLS_DIR / "*_classified_*.parquet")))
    latest_per_source: dict[str, str] = {}
    for f in files:
        stem = Path(f).stem
        source = stem.rsplit("_classified_", 1)[0]
        latest_per_source[source] = f
    for source, f in latest_per_source.items():
        df = pd.read_parquet(f)
        if "source" not in df.columns:
            df["source"] = source
        dfs.append(df)

    # 2. SEC item801_classified (separate parquet, slightly different schema)
    sec_cls_p = latest_parquet(SEC_DIR, "item801_classified")
    if sec_cls_p is not None:
        sec_df = pd.read_parquet(sec_cls_p)
        # Normalise to common schema
        sec_norm = pd.DataFrame({
            "source_id": sec_df["accession"].astype(str),
            "source": "sec_8k_item801",
            "event_type": sec_df["event_type"],
            "summary_ja": sec_df["summary_ja"],
            "supply_relevance": sec_df["supply_relevance"],
            "key_facility": sec_df.get("key_facility", ""),
            "key_product": sec_df.get("key_product", ""),
            "_classified_at": sec_df.get("_classified_at", ""),
        })
        dfs.append(sec_norm)

    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True, sort=False)


def _enrich_with_origin(df_cls: pd.DataFrame) -> pd.DataFrame:
    """Join classification rows back to their origin source rows to recover company / date metadata."""
    if df_cls.empty:
        return df_cls
    out_rows = []
    source_to_origin = {
        "edinet_extraordinary": (latest_parquet(EDINET_EXTRA_DIR, "extraordinary_reports"), "doc_id", ["submit_date", "company", "industry", "viewer_url"]),
        "dart_major_matters":   (latest_parquet(DART_DIR, "dart_major_matters"), "rcept_no", ["rcept_dt", "corp_name", "industry", "viewer_url"]),
        "tdnet_disclosure":     (latest_parquet(TDNET_DIR, "tdnet_disclosure"), "pdf_url", ["date", "company", "industry", "pdf_url"]),
        "twse_material_info":   (latest_parquet(TWSE_DIR, "twse_material_info"), "subject", ["filing_date", "company_name", "market"]),
        # SEC: item801_classified already contains all metadata, but join via accession for consistency
        "sec_8k_item801":       (latest_parquet(SEC_DIR, "item801_classified"), "accession", ["filing_date", "company_name", "ticker", "accession_url"]),
    }
    by_source = {s: latest for s, (latest, *_rest) in source_to_origin.items() if latest is not None}
    # Cache origin dataframes per source
    origin_dfs: dict[str, pd.DataFrame] = {}
    for s, (p, _, _) in source_to_origin.items():
        if p is not None:
            try:
                origin_dfs[s] = pd.read_parquet(p)
            except Exception:
                pass

    for _, r in df_cls.iterrows():
        meta = {"_date": "", "_company": "", "_industry": "", "_url": ""}
        s = r["source"]
        if s in source_to_origin and s in origin_dfs:
            _, id_col, cols = source_to_origin[s]
            odf = origin_dfs[s]
            match = odf[odf[id_col].astype(str) == str(r["source_id"])]
            if len(match):
                m = match.iloc[0]
                if s == "edinet_extraordinary":
                    meta = {"_date": m["submit_date"], "_company": m["company"], "_industry": m["industry"], "_url": m["viewer_url"]}
                elif s == "dart_major_matters":
                    meta = {"_date": m["rcept_dt"], "_company": m["corp_name"], "_industry": m["industry"], "_url": m["viewer_url"]}
                elif s == "tdnet_disclosure":
                    meta = {"_date": m["date"], "_company": m["company"], "_industry": m["industry"], "_url": m["pdf_url"]}
                elif s == "twse_material_info":
                    meta = {"_date": m["filing_date"], "_company": m["company_name"], "_industry": m["market"], "_url": ""}
                elif s == "sec_8k_item801":
                    meta = {"_date": str(m.get("filing_date", "")), "_company": m.get("company_name", ""), "_industry": "米化学", "_url": m.get("accession_url", "")}
        out_rows.append({**r.to_dict(), **meta})
    return pd.DataFrame(out_rows)


SOURCE_FLAG = {
    "edinet_extraordinary": "🇯🇵 EDINET",
    "tdnet_disclosure":     "🇯🇵 TDnet",
    "dart_major_matters":   "🇰🇷 DART",
    "twse_material_info":   "🇹🇼 TWSE",
    "sec_8k_item801":       "🇺🇸 SEC 8-K",
}

CHEMICALS_COMPANY_MAP_P = ROOT / "data" / "chemicals" / "chemicals_company_map.parquet"


@st.cache_data
def _load_company_map() -> pd.DataFrame:
    if not CHEMICALS_COMPANY_MAP_P.exists():
        return pd.DataFrame()
    return pd.read_parquet(CHEMICALS_COMPANY_MAP_P)


def _events_for_companies(
    us_tickers: list, jp_edinet: list, kr_corp: list, tw_tickers: list,
    df_cls_enriched: pd.DataFrame,
) -> pd.DataFrame:
    """Filter enriched classifier output to rows matching any of the given codes."""
    if df_cls_enriched.empty:
        return df_cls_enriched
    # Origin-source-specific matching:
    # - SEC ticker matches US ticker (handled separately as item801 not in axis6_classified)
    # - EDINET edinet_code: needs original parquet; we'll match by company name proxy via meta
    # - DART corp_code: same
    # - TDnet ticker: 4-digit
    # - TWSE ticker: 4-digit
    # Since enriched df has _company and _industry but not direct codes, we need to
    # re-load origin parquets and join. Simpler: pre-join everything by code here.
    return _filter_axis6_by_codes(us_tickers, jp_edinet, kr_corp, tw_tickers, df_cls_enriched)


def _filter_axis6_by_codes(us, jp_e, kr_c, tw, df_cls):
    """Join classifier output to origin parquets and filter by company codes."""
    if df_cls.empty:
        return df_cls
    # Load origin parquets
    edinet_p = latest_parquet(EDINET_EXTRA_DIR, "extraordinary_reports")
    dart_p = latest_parquet(DART_DIR, "dart_major_matters")
    tdnet_p = latest_parquet(TDNET_DIR, "tdnet_disclosure")
    twse_p = latest_parquet(TWSE_DIR, "twse_material_info")

    matched_ids: set[tuple[str, str]] = set()  # (source, source_id)

    if edinet_p and jp_e:
        odf = pd.read_parquet(edinet_p)
        hits = odf[odf["edinet_code"].isin(jp_e)]
        matched_ids.update(("edinet_extraordinary", str(d)) for d in hits["doc_id"])
    if dart_p and kr_c:
        odf = pd.read_parquet(dart_p)
        hits = odf[odf["corp_code"].isin(kr_c)]
        matched_ids.update(("dart_major_matters", str(r)) for r in hits["rcept_no"])
    if tdnet_p:
        odf = pd.read_parquet(tdnet_p)
        # TDnet uses 4-digit ticker; we accept US-style + jp_e (but JP TDnet → use ticker)
        # The user-provided tickers in 'us' field are US — TDnet only matches 4-digit JP tickers.
        # We don't have a separate jp_tickers field; skip TDnet by-code filter for now.
        # Future: add jp_tickers to seed.
        pass
    if twse_p and tw:
        odf = pd.read_parquet(twse_p)
        hits = odf[odf["ticker"].isin(tw)]
        matched_ids.update(("twse_material_info", str(s)) for s in hits["subject"])

    # SEC 8-K is its own dataset (not in axis6_classified). Handled in caller.
    df_match = df_cls[df_cls.apply(lambda r: (r["source"], str(r["source_id"])) in matched_ids, axis=1)]
    return df_match


_SEC_EMPTY = pd.DataFrame(columns=["ticker", "filing_date", "company_name", "event_type", "summary_ja", "supply_relevance", "accession_url"])


def _sec_events_for_tickers(us_tickers: list) -> pd.DataFrame:
    """Pull SEC 8-K item801 classified HIGH/MED events for given tickers.

    Always returns a DataFrame with the expected columns even when empty —
    callers do `.["supply_relevance"]` on the result.
    """
    if not us_tickers:
        return _SEC_EMPTY.copy()
    cls_p = latest_parquet(SEC_DIR, "item801_classified")
    if cls_p is None:
        return _SEC_EMPTY.copy()
    df = pd.read_parquet(cls_p)
    hits = df[df["ticker"].isin(us_tickers) & df["supply_relevance"].isin(["HIGH", "MED"])]
    if hits.empty:
        return _SEC_EMPTY.copy()
    return hits


# ---------- tab 6 ----------
def render_axis6():
    sec_p = latest_parquet(SEC_DIR, "filings_8k")

    st.info(
        "**軸6「過去の供給途絶」** | SEC EDGAR 8-K（米化学メジャー15社の臨時開示）"
        " + 日本 (EDINET臨時報告書・TDnet適時開示・NITE化学事故)"
        " + 韓国 (DART 주요사항보고서)"
        " + 台湾 (TWSE/TPEX 重大訊息)。"
        "Item 8.01 (Other Events) と Item 2.06 (Material Impairments) が FM 発令・大規模事故・撤退の主な箱。"
        "出現頻度がその企業/業界のオペレーションリスクの粗い代理指標。"
    )

    # === A: 6ソース横断 HIGH/MED 統合ビュー (最上段) ===
    st.markdown("## 🚨 6ソース横断 HIGH/MED イベント (最新)")
    df_cls_all = _load_axis6_classified()
    if df_cls_all.empty:
        st.info("LLM分類済データなし。`ingest/disruption_classify.py` 実行 (各ソース ~120件)")
    else:
        hm_all = df_cls_all[df_cls_all["supply_relevance"].isin(["HIGH", "MED"])].copy()
        hm_all = _enrich_with_origin(hm_all)
        if hm_all.empty:
            st.success("✅ 直近の HIGH/MED 供給関連イベントなし (4ソース全体)")
        else:
            # Metrics row
            high = hm_all[hm_all["supply_relevance"] == "HIGH"]
            med = hm_all[hm_all["supply_relevance"] == "MED"]
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("🚨 HIGH", len(high), help="操業停止/火災/災害損害/リコール等")
            mc2.metric("⚠️ MED", len(med), help="事業譲渡/訴訟/規制違反")
            mc3.metric("ソース数", hm_all["source"].nunique())
            mc4.metric("企業数", hm_all["_company"].nunique())

            # Source filter
            cols_f = st.columns([2, 1, 1])
            with cols_f[0]:
                src_pick = st.multiselect(
                    "ソース",
                    list(SOURCE_FLAG.keys()),
                    default=list(SOURCE_FLAG.keys()),
                    format_func=lambda s: SOURCE_FLAG.get(s, s),
                    key="axis6_top_src",
                )
            with cols_f[1]:
                sev_pick = st.multiselect(
                    "重要度",
                    ["HIGH", "MED"],
                    default=["HIGH", "MED"],
                    key="axis6_top_sev",
                )
            with cols_f[2]:
                limit_pick = st.selectbox("表示件数", [50, 100, 200, 500], index=1, key="axis6_top_limit")

            view = hm_all[hm_all["source"].isin(src_pick) & hm_all["supply_relevance"].isin(sev_pick)].copy()
            view["旗"] = view["source"].map(lambda s: SOURCE_FLAG.get(s, s))
            view = view.sort_values("_date", ascending=False).head(limit_pick)
            view_disp = view[["_date", "旗", "supply_relevance", "event_type", "_company", "_industry", "summary_ja", "_url"]].copy()
            view_disp.columns = ["日付", "ソース", "重要度", "Event", "企業", "業種", "要約", "リンク"]
            st.dataframe(view_disp, use_container_width=True, hide_index=True, height=420)

    st.divider()

    # === B: 物質ごと 供給途絶イベントカウント (Claude手動マッピング 135物質) ===
    st.markdown("## 🧪 物質ごと 供給途絶イベントカウント")
    comp_map = _load_company_map()
    if comp_map.empty:
        st.info(
            "化学品→製造企業マップ未生成。`uv run python ingest/chemicals/build_company_map.py` 実行。"
        )
    else:
        st.caption(
            f"Claude知識ベースで {len(comp_map)} 物質をマッピング済 "
            f"(US {(comp_map['us_tickers'].str.len()>0).sum()} / JP {(comp_map['jp_edinet_codes'].str.len()>0).sum()} / "
            f"KR {(comp_map['kr_corp_codes'].str.len()>0).sum()} / TW {(comp_map['tw_tickers'].str.len()>0).sum()} 物質に主要製造企業)。"
            "残り 334 物質はカテゴリ偏り (規制POPs/SVHC等) で活発な製造企業不明 — Phase 2 で拡張予定。"
        )

        # Pre-load classifier output once
        df_cls_full = _load_axis6_classified()
        # Aggregate counts per CAS
        agg_rows = []
        for _, row in comp_map.iterrows():
            cas = row["cas"]
            us_list = list(row["us_tickers"]) if row["us_tickers"] is not None else []
            jp_list = list(row["jp_edinet_codes"]) if row["jp_edinet_codes"] is not None else []
            kr_list = list(row["kr_corp_codes"]) if row["kr_corp_codes"] is not None else []
            tw_list = list(row["tw_tickers"]) if row["tw_tickers"] is not None else []
            axis6_hits = _filter_axis6_by_codes(us_list, jp_list, kr_list, tw_list, df_cls_full)
            sec_hits = _sec_events_for_tickers(us_list)
            high = int((axis6_hits["supply_relevance"] == "HIGH").sum()) + int((sec_hits["supply_relevance"] == "HIGH").sum())
            med = int((axis6_hits["supply_relevance"] == "MED").sum()) + int((sec_hits["supply_relevance"] == "MED").sum())
            agg_rows.append({
                "CAS": cas,
                "物質名": row["name_en"],
                "カテゴリ": row["category_norm"],
                "🚨HIGH": high,
                "⚠️MED": med,
                "US社数": len(us_list),
                "JP社数": len(jp_list),
                "KR社数": len(kr_list),
                "TW社数": len(tw_list),
            })
        agg_df = pd.DataFrame(agg_rows).sort_values(["🚨HIGH", "⚠️MED"], ascending=[False, False])
        st.dataframe(agg_df, use_container_width=True, hide_index=True, height=400)

        st.markdown("**🔍 物質を選んで詳細イベント一覧**")
        cas_options = comp_map["cas"].tolist()
        cas_pick = st.selectbox(
            "CAS番号",
            cas_options,
            format_func=lambda c: f"{c} — {comp_map[comp_map['cas']==c].iloc[0]['name_en']}",
            key="axis6_b_cas",
        )
        sel = comp_map[comp_map["cas"] == cas_pick].iloc[0]
        us_list = list(sel["us_tickers"]) if sel["us_tickers"] is not None else []
        jp_list = list(sel["jp_edinet_codes"]) if sel["jp_edinet_codes"] is not None else []
        kr_list = list(sel["kr_corp_codes"]) if sel["kr_corp_codes"] is not None else []
        tw_list = list(sel["tw_tickers"]) if sel["tw_tickers"] is not None else []
        st.caption(
            f"**製造企業群:** US={', '.join(us_list) or '—'} | "
            f"JP edinet={', '.join(jp_list) or '—'} | "
            f"KR corp={', '.join(kr_list) or '—'} | "
            f"TW={', '.join(tw_list) or '—'}"
        )
        axis6_hits = _filter_axis6_by_codes(us_list, jp_list, kr_list, tw_list, df_cls_full)
        axis6_hits = _enrich_with_origin(axis6_hits)
        sec_hits = _sec_events_for_tickers(us_list)
        # Common columns we display downstream
        DISPLAY_COLS = ["_date", "source", "supply_relevance", "event_type", "_company", "summary_ja", "_url"]
        # Normalize axis6_hits (already has _date/_company/_industry/_url from _enrich_with_origin)
        for col in DISPLAY_COLS:
            if col not in axis6_hits.columns:
                axis6_hits[col] = ""
        # Normalize sec_hits
        if not sec_hits.empty:
            sec_hits = sec_hits.assign(
                source="sec_8k_item801",
                _date=sec_hits["filing_date"].astype(str),
                _company=sec_hits["company_name"],
                _url=sec_hits.get("accession_url", ""),
            )
        for col in DISPLAY_COLS:
            if col not in sec_hits.columns:
                sec_hits[col] = ""
        merged = pd.concat(
            [axis6_hits[DISPLAY_COLS], sec_hits[DISPLAY_COLS]],
            ignore_index=True,
        )
        if merged.empty:
            st.info("該当イベントなし")
        else:
            merged["旗"] = merged["source"].map(lambda s: SOURCE_FLAG.get(s, "🇺🇸 SEC" if "sec" in str(s) else s))
            disp = merged.sort_values("_date", ascending=False)[["_date", "旗", "supply_relevance", "event_type", "_company", "summary_ja", "_url"]].copy()
            disp.columns = ["日付", "ソース", "重要度", "Event", "企業", "要約", "リンク"]
            st.dataframe(disp, use_container_width=True, hide_index=True, height=320)

    st.divider()

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

    st.divider()
    st.markdown("### 🌏 JP / KR / TW 拡張ソース (2026-05 追加)")
    edinet_ex_p = latest_parquet(EDINET_EXTRA_DIR, "extraordinary_reports")
    dart_p = latest_parquet(DART_DIR, "dart_major_matters")
    tdnet_p = latest_parquet(TDNET_DIR, "tdnet_disclosure")
    twse_p = latest_parquet(TWSE_DIR, "twse_material_info")
    nite_p = latest_parquet(NITE_DIR, "nite_accidents")

    asia_tabs = st.tabs([
        "🇯🇵 EDINET 臨時",
        "🇯🇵 TDnet 適時",
        "🇰🇷 DART 주요사항",
        "🇹🇼 TWSE 重大訊息",
        "🇯🇵 NITE 化学事故",
    ])
    with asia_tabs[0]:
        _render_disruption_subtab(
            "edinet_extraordinary", edinet_ex_p,
            columns=["submit_date", "company", "industry", "doc_description", "viewer_url"],
            classified_glob="edinet_extraordinary_classified_*.parquet",
        )
    with asia_tabs[1]:
        _render_disruption_subtab(
            "tdnet_disclosure", tdnet_p,
            columns=["date", "time", "company", "industry", "title", "pdf_url"],
            classified_glob="tdnet_disclosure_classified_*.parquet",
        )
    with asia_tabs[2]:
        _render_disruption_subtab(
            "dart_major_matters", dart_p,
            columns=["rcept_dt", "corp_name", "industry", "report_nm", "viewer_url"],
            classified_glob="dart_major_matters_classified_*.parquet",
        )
    with asia_tabs[3]:
        _render_disruption_subtab(
            "twse_material_info", twse_p,
            columns=["filing_date", "filing_time", "company_name", "market", "subject"],
            classified_glob="twse_material_info_classified_*.parquet",
        )
    with asia_tabs[4]:
        _render_disruption_subtab(
            "nite_accidents", nite_p,
            columns=["date", "title", "url"],
        )

    st.divider()
    st.markdown("### 📂 ソース生データ — 軸6 過去の供給途絶")
    source_inspector.render_source("sec_8k", sec_p)
    source_inspector.render_source("sec_item801", classified_p)
    source_inspector.render_source("edinet_extraordinary", edinet_ex_p)
    source_inspector.render_source("dart_major_matters", dart_p)
    source_inspector.render_source("tdnet_disclosure", tdnet_p)
    source_inspector.render_source("twse_material_info", twse_p)
    source_inspector.render_source("nite_accidents", nite_p)
    from glob import glob
    axis6_cls_files = sorted(glob(str(AXIS6_CLS_DIR / "*_classified_*.parquet")))
    if axis6_cls_files:
        source_inspector.render_source("axis6_classified", Path(axis6_cls_files[-1]))


# ---------- tab 1 ----------
def render_axis1():
    st.info(
        "**軸1「生産能力・新増設」** | EDINET 有報・統合報告書・中計から「生産能力／設備能力／年産」"
        "等のキーワード周辺snippetを抽出。LLM構造化で製品×工場×能力テーブル化済。"
    )
    st.warning(
        "⚠️ **個別物質 (CAS) 粒度の評価は現状未対応** — スニペット抽出トリガーが化学品名でなく"
        "一般キーワードのため。Phase B (JA alias生成 + product紐付け) まで生データのみ公開。"
    )
    st.divider()
    st.markdown("### 📂 ソース生データ")
    p = latest_parquet(EDINET_DIR, "capacity_snippets")
    structured_p = latest_parquet(EDINET_DIR, "capacity_structured")
    source_inspector.render_source("edinet_snippets", p)
    source_inspector.render_source("edinet_structured", structured_p)


# ---------- tab 7 ----------
def render_axis7():
    st.info(
        "**軸7「価格変動性」** | World Bank Pink Sheet 月次商品価格（1960年〜現在）。"
        "ゴム TSR20/RSS3、原油、天然ガス、ベース金属など 15品目のみ。"
    )
    st.warning(
        "⚠️ **個別化学品 (CAS) 粒度の評価は現状未対応** — 15品目のみで、"
        "化学品マスタ469中のごく一部しかカバーしていない。NYMEX/EIA/JCN等の価格ソース追加 + "
        "CAS→commodity マッピング充実までは生データのみ公開。"
    )
    st.divider()
    st.markdown("### 📂 ソース生データ")
    p = latest_parquet(WB_DIR, "prices_monthly")
    source_inspector.render_source("wb_prices", p)


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

    st.divider()
    st.subheader("⚙️ JPCA 月次 エチレンクラッカー実質稼働率")
    jpca_util_p = latest_parquet(ROOT / "data" / "jpca", "jpca_utilization")
    if jpca_util_p is None:
        st.info("JPCA 稼働率データ未取得。`uv run python ingest/jpca_utilization.py` 実行。")
    else:
        udf = pd.read_parquet(jpca_util_p).sort_values("period")
        st.caption(
            f"`{jpca_util_p.name}` — {len(udf)}ヶ月分 ({udf['period'].min()}〜{udf['period'].max()}). "
            "「稼働プラントの実質稼働率試算」を石化協メモPDFから抽出。化学業界が見る代表的需給シグナル。"
        )
        latest_u = udf.iloc[-1]
        mu1, mu2, mu3, mu4 = st.columns(4)
        mu1.metric("当月", f"{latest_u['util_current']:.1f}%", help=f"{latest_u['period']}")
        mu2.metric("前月", f"{latest_u['util_prev_month']:.1f}%")
        mu3.metric("前年同月", f"{latest_u['util_prev_year_same_month']:.1f}%")
        diff_yoy = latest_u['util_current'] - latest_u['util_prev_year_same_month']
        mu4.metric("YoY 差", f"{diff_yoy:+.1f}pt")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=udf["period"], y=udf["util_current"],
            mode="lines+markers", name="実質稼働率",
            line=dict(color=ACCENT, width=3), marker=dict(size=6),
            hovertemplate="<b>%{x}</b><br>稼働率: %{y:.1f}%<extra></extra>",
        ))
        fig.add_hline(y=85, line_dash="dash", line_color="#10B981", annotation_text="健全 (85%+)", annotation_position="right")
        fig.add_hline(y=70, line_dash="dash", line_color="#F59E0B", annotation_text="注意 (70%)", annotation_position="right")
        fig.add_hline(y=60, line_dash="dash", line_color=DANGER, annotation_text="危険 (60%)", annotation_position="right")
        fig.update_yaxes(title="稼働率 %", range=[50, 100])
        fig.update_xaxes(title="期間")
        st.plotly_chart(styled_fig(fig, height=320), use_container_width=True)
        st.markdown("**直近6ヶ月の詳細**")
        recent = udf.tail(6)[["period", "util_current", "util_prev_month", "util_prev_year_same_month", "teishu_current", "ethylene_kton", "ethylene_mom_pct", "ethylene_yoy_pct"]].copy()
        recent.columns = ["期間", "当月%", "前月%", "前年同月%", "定修", "エチレン千t", "MoM%", "YoY%"]
        st.dataframe(recent, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📰 化学業界 disruption ニュース (Google News)")
    news_p = latest_parquet(ROOT / "data" / "chem_news", "chem_news")
    if news_p is None:
        st.info("ニュース未取得。`uv run python ingest/chem_news_rss.py` 実行。")
    else:
        ndf = pd.read_parquet(news_p).sort_values("pub_date_iso", ascending=False)
        st.caption(
            f"`{news_p.name}` — {len(ndf)}件 / クエリ {ndf['query_name'].nunique()}種 / "
            f"ソース {ndf['source_name'].nunique()}媒体"
        )
        cn1, cn2 = st.columns([2, 1])
        with cn1:
            q_opts = sorted(ndf["query_name"].unique())
            q_pick = st.multiselect(
                "クエリ", q_opts, default=q_opts, key="news_q",
            )
        with cn2:
            limit_pick = st.selectbox("表示", [25, 50, 100, 200], index=1, key="news_lim")
        view = ndf[ndf["query_name"].isin(q_pick)].head(limit_pick).copy()
        view["link_md"] = view["link"].map(lambda u: f"[詳細]({u})")
        disp_news = view[["pub_date_iso", "query_name", "source_name", "title", "link_md"]].copy()
        disp_news.columns = ["公開", "クエリ", "媒体", "タイトル", "リンク"]
        st.dataframe(disp_news, use_container_width=True, hide_index=True, height=420)

    st.divider()
    st.subheader("🏭 JPCA 月次生産実績 (1999年〜)")
    jpca_p = latest_parquet(ROOT / "data" / "jpca", "jpca_monthly")
    if jpca_p is None:
        st.info("JPCA 月次データ未取得。`uv run python ingest/jpca_monthly.py` 実行。")
    else:
        jdf = pd.read_parquet(jpca_p)
        st.caption(f"`{jpca_p.name}` — {len(jdf):,} rows, {jdf['cas'].nunique()} CAS, {jdf['period'].min()}〜{jdf['period'].max()}")
        # CAS picker (only CAS in JPCA)
        cas_options = sorted(jdf["cas"].dropna().unique().tolist())
        chem_map = cl.all_chemicals().set_index("cas")["_display_name"].to_dict()
        pick = st.selectbox(
            "物質",
            cas_options,
            format_func=lambda c: f"{c} — {chem_map.get(c, '?')}",
            key="jpca_cas",
        )
        sub = jdf[jdf["cas"] == pick].sort_values("period")
        if len(sub) == 0:
            st.warning("該当データなし")
        else:
            # Time-series plot
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=sub["period"], y=sub["value"],
                mode="lines+markers",
                line=dict(color=ACCENT, width=2),
                marker=dict(size=4),
                hovertemplate="<b>%{x}</b><br>生産量: %{y:.1f} 千トン<extra></extra>",
            ))
            fig.update_yaxes(title="生産量 (千トン)")
            fig.update_xaxes(title="期間")
            st.plotly_chart(styled_fig(fig, height=320), use_container_width=True)
            # Recent 12 months table
            st.markdown("**直近12ヶ月**")
            recent = sub.tail(12)[["period", "product", "value", "unit"]].copy()
            st.dataframe(recent, use_container_width=True, hide_index=True)
            # YoY change
            if len(sub) >= 13:
                last = sub.iloc[-1]
                yoy = sub.iloc[-13]
                pct = (last["value"] / yoy["value"] - 1) * 100 if yoy["value"] else None
                if pct is not None:
                    st.metric(f"直近 ({last['period']}) YoY", f"{pct:+.1f}%", help=f"前年同月 {yoy['period']} 比")

    st.divider()
    source_inspector.render_source("comtrade_trade", parquet, key_suffix="axis2")
    source_inspector.render_source("jpca_utilization", jpca_util_p)
    source_inspector.render_source("chem_news", news_p)
    source_inspector.render_source("jpca_monthly", jpca_p)
    estat_p = latest_parquet(ROOT / "data" / "estat", "estat_trade")
    source_inspector.render_source("estat_trade", estat_p)


# ---------- tab 3 ----------
def render_axis3():
    st.info(
        "**軸3「サプライヤー集中度」(proxy)** | "
        "EDINET 言及数ベースで国内サプライヤー数を数え、3バンドで色分けした暫定指標。"
    )
    st.warning(
        "⚠️ **17ピン留め素材のみ対応**。化学品マスタ 469 物質中の 3.6% しかカバーしてない上、"
        "「言及あり = サプライヤー」という仮定の精度も粗い。本格 HHI は各社生産能力数値が必要だが"
        "EDINET XBRL では構造化されていない。Phase 2 で拡張までは生データのみ公開。"
    )
    st.divider()
    st.markdown("### 📂 ソース生データ")
    p = latest_parquet(SUPPLIER_DIR, "jp_supplier_count")
    source_inspector.render_source("jp_supplier", p)


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

    # === Axis 1: per-chemical view disabled — see Phase B plan ===
    st.subheader("🏭 軸1 生産能力・新増設")
    st.warning(
        "**個別物質ベースでは現状未対応**　\n"
        "EDINET snippet は「生産能力／設備能力／年産」等の一般キーワードで抽出されており、"
        "化学品 CAS にひもづいていません。chemicals.parquet 469件のうち日本語 alias を持つのは "
        "17件のみで、残り452件 (96%) は日本語有報を LIKE 検索しても 0 件ヒットになるか、"
        "ノイズだらけ（タイヤ生産設備・塗装工場など）になります。\n\n"
        "**次フェーズ (Phase B)**: LLM で全469物質に JA aliases を生成し、"
        "`capacity_structured.product` 列と紐付けて CAS 粒度に再構築予定。\n\n"
        "**現状で見たい場合**: 上部の「🏭 軸1 生産能力」タブで企業活動の粗い proxy として閲覧可能。"
    )

    st.divider()
    st.caption(
        "📂 各軸の原典 parquet（カラム定義・プレビュー・CSV ダウンロード）は、"
        "上部の各「軸N」タブ末尾の「📂 ソース生データ」セクションから開けます。"
    )


# ---------- score tab — comparison sub-view ----------
COMPARE_COLORS = ["#0F766E", "#7C3AED", "#DC2626", "#F59E0B"]
COMPARE_FILL = ["rgba(15,118,110,0.18)", "rgba(124,58,237,0.18)", "rgba(220,38,38,0.18)", "rgba(245,158,11,0.18)"]


def render_compare(cas_list: list[str], industry: str):
    """Overlay radar chart + side-by-side score table for 2-4 chemicals."""
    chems = [cl.get_chemical(c) for c in cas_list]
    chems = [c for c in chems if c is not None]
    if not chems:
        st.error("物質詳細取得失敗")
        return

    # Compute scores per material
    with st.spinner(f"{len(chems)}物質 × 7軸スコア計算中..."):
        per_material = []
        for chem in chems:
            sub = scoring.compute_all(chem["cas"])
            comp = scoring.composite(sub, industry=industry)
            per_material.append({"chem": chem, "sub": sub, "comp": comp})

    # --- Headline composite cards ---
    cols = st.columns(len(per_material))
    grade_colors = {"A": "#10B981", "B": "#22C55E", "C": "#F59E0B", "D": "#FB923C", "E": "#EF4444", "F": "#7F1D1D"}
    for i, (col, m) in enumerate(zip(cols, per_material)):
        with col:
            name = m["chem"]["display_name"][:30]
            border = COMPARE_COLORS[i % len(COMPARE_COLORS)]
            if m["comp"]["composite"] is not None:
                v = m["comp"]["composite"]
                grade = m["comp"]["grade"]
                gc = grade_colors.get(grade, MUTED)
                st.markdown(
                    f"<div style='padding:8px;border-radius:8px;background:{gc}10;border:2px solid {border};text-align:center;'>"
                    f"<div style='font-size:11px;color:#334155;font-weight:600;'>{name}</div>"
                    f"<div style='font-size:30px;font-weight:700;color:{gc};line-height:1.1;margin-top:4px;'>{v:.0f}</div>"
                    f"<div style='font-size:18px;font-weight:600;color:{gc};line-height:1.0;'>{grade}</div>"
                    f"<div style='font-size:10px;color:#64748B;margin-top:3px;'>{m['comp']['scored_axes']}/7 軸</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='padding:8px;border-radius:8px;background:#F1F5F9;border:2px dashed {border};text-align:center;'>"
                    f"<div style='font-size:11px;color:#334155;font-weight:600;'>{name}</div>"
                    f"<div style='font-size:18px;font-weight:600;color:{MUTED};margin-top:8px;'>データ不足</div>"
                    f"<div style='font-size:10px;color:#64748B;margin-top:3px;'>{m['comp']['scored_axes']}/7 軸</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )

    st.divider()

    # --- Overlaid radar chart ---
    st.markdown("**7軸レーダー重ね描き** (外周=安定/100, 中心=リスク/0)")
    axes_order = scoring.AXIS_KEYS
    axis_labels = [scoring.AXIS_LABELS_JA[k] for k in axes_order]
    theta = axis_labels + [axis_labels[0]]

    fig = go.Figure()
    # Background caution/danger reference rings
    fig.add_trace(go.Scatterpolar(
        r=[30] * (len(axes_order) + 1), theta=theta, mode="lines",
        line=dict(color="#FCA5A5", width=1, dash="dot"),
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatterpolar(
        r=[60] * (len(axes_order) + 1), theta=theta, mode="lines",
        line=dict(color="#FDE68A", width=1, dash="dot"),
        hoverinfo="skip", showlegend=False,
    ))
    for i, m in enumerate(per_material):
        sub = m["sub"]
        scores = [sub[k]["score"] if sub[k]["score"] is not None else 0 for k in axes_order]
        r_actual = scores + [scores[0]]
        color = COMPARE_COLORS[i % len(COMPARE_COLORS)]
        fill = COMPARE_FILL[i % len(COMPARE_FILL)]
        name = m["chem"]["display_name"][:25]
        fig.add_trace(go.Scatterpolar(
            r=r_actual, theta=theta, mode="lines+markers", fill="toself",
            line=dict(color=color, width=2),
            fillcolor=fill,
            marker=dict(size=6, color=color),
            name=name,
            hovertemplate=f"<b>{name}</b><br>%{{theta}}<br>%{{r:.0f}}/100<extra></extra>",
        ))
    fig.update_layout(
        template="plotly_white",
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], tickvals=[0, 30, 60, 100],
                            gridcolor="#E2E8F0", tickfont=dict(size=10, color=MUTED)),
            angularaxis=dict(tickfont=dict(size=11, color="#334155"), gridcolor="#E2E8F0"),
            bgcolor="white",
        ),
        showlegend=True,
        legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
        height=480,
        margin=dict(l=60, r=60, t=20, b=80),
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Per-axis comparison table ---
    st.markdown("**軸別スコア比較表**")
    rows = []
    for axis in axes_order:
        row = {"軸": scoring.AXIS_LABELS_JA[axis].replace("軸", "").strip()[:18]}
        # Find winner
        scores_now = [(i, m["sub"][axis]["score"]) for i, m in enumerate(per_material)]
        valid_scores = [(i, s) for i, s in scores_now if s is not None]
        winner_idx = max(valid_scores, key=lambda x: x[1])[0] if valid_scores else None
        for i, m in enumerate(per_material):
            s = m["sub"][axis]["score"]
            if s is None:
                row[m["chem"]["display_name"][:15]] = "—"
            else:
                badge = " 👑" if i == winner_idx else ""
                row[m["chem"]["display_name"][:15]] = f"{s:.0f}{badge}"
        rows.append(row)
    tdf = pd.DataFrame(rows)
    st.dataframe(tdf, use_container_width=True, hide_index=True)
    st.caption("👑 = 各軸での最高スコア（複数同点の場合は最左）")

    # --- Aggregated narrative ---
    st.divider()
    st.markdown("### 📝 比較総評")
    parts = []
    # Best overall
    composites = [(i, m["comp"]["composite"]) for i, m in enumerate(per_material) if m["comp"]["composite"] is not None]
    if composites:
        best_i, best_v = max(composites, key=lambda x: x[1])
        worst_i, worst_v = min(composites, key=lambda x: x[1])
        best_name = per_material[best_i]["chem"]["display_name"]
        worst_name = per_material[worst_i]["chem"]["display_name"]
        if best_i != worst_i:
            parts.append(
                f"総合スコア最高は **{best_name}** ({best_v:.0f}/100)、最低は **{worst_name}** ({worst_v:.0f}/100)、"
                f"差分 {best_v - worst_v:.0f}点。"
            )
        else:
            parts.append(f"評価可能な物質は **{best_name}** のみ、{best_v:.0f}/100。")

    # Axis-level dispersion
    high_dispersion_axes = []
    for axis in axes_order:
        valid = [m["sub"][axis]["score"] for m in per_material if m["sub"][axis]["score"] is not None]
        if len(valid) >= 2:
            spread = max(valid) - min(valid)
            if spread >= 40:
                high_dispersion_axes.append((axis, spread, max(valid), min(valid)))
    if high_dispersion_axes:
        high_dispersion_axes.sort(key=lambda x: -x[1])
        spread_lines = [
            f"- **{scoring.AXIS_LABELS_JA[a]}**: スコア差 {sp:.0f}点 (最高 {mx:.0f} / 最低 {mn:.0f})"
            for a, sp, mx, mn in high_dispersion_axes[:3]
        ]
        parts.append("\n**🎯 物質間で差が大きい軸:**\n" + "\n".join(spread_lines))

    # Industry-specific guidance
    ind = cl.industries().get(industry) or cl.industries().get("default") or {}
    ind_name = ind.get("name_ja", industry)
    weights = ind.get("weights") or {}
    top_weighted = sorted(weights.items(), key=lambda x: -x[1])[:2]
    if top_weighted:
        parts.append(
            f"\n**📊 {ind_name}業界の重視軸:** "
            + " / ".join(f"{scoring.AXIS_LABELS_JA[k]} ({v*100:.0f}%)" for k, v in top_weighted)
            + " — この軸でのスコアが調達判断に最も効く"
        )

    if parts:
        st.markdown("\n".join(parts))
    else:
        st.info("評価可能な物質が不足のため比較総評を生成できません。")
    st.caption("🤖 ルールベース比較。LLM 文脈考慮型レビューは API 連携後の next step。")


# ---------- score tab (composite + radar + narrative) ----------
def render_score():
    chem_df = load_all_chemicals_df()
    if chem_df.empty:
        st.error("`data/chemicals/chemicals.parquet` なし。")
        return

    pinned_count = int(chem_df["is_pinned"].sum())
    st.info(
        "**🏆 総合スコア** | 7軸プロキシ指標を 0–100 で正規化し、業界別重みで合成 → A–F 判定。"
        f"7軸のうち {scoring.MIN_SCORED_AXES} 軸以上のデータが揃わない場合は「評価データ不足」として明示。"
        "総評は現時点ではルールベース生成（API予算復活時に LLM 化）。"
    )

    # --- Selectors ---
    col_search, col_cat, col_ind = st.columns([2, 1, 1])
    with col_search:
        query = st.text_input(
            "🔍 物質名 / CAS番号で検索（部分一致）",
            "",
            placeholder="例: ethylene / 74-85-1 / SBR",
            key="score_search",
        )
    with col_cat:
        categories_meta = cl.categories()
        cat_options = ["（全カテゴリ）"] + [c["id"] for c in categories_meta]
        cat_labels = {c["id"]: c["name_ja"] for c in categories_meta}
        selected_cat = st.selectbox(
            "カテゴリ絞り込み",
            cat_options,
            format_func=lambda c: c if c == "（全カテゴリ）" else f"{cat_labels.get(c, c)}",
            key="score_cat",
        )
    with col_ind:
        industries = cl.industries()
        ind_options = list(industries.keys())
        ind_labels = {k: v.get("name_ja", k) for k, v in industries.items()}
        # Put "default" first if exists
        if "rubber_tire" in ind_options:
            ind_options.remove("rubber_tire"); ind_options.insert(0, "rubber_tire")
        selected_industry = st.selectbox(
            "業界（重み）",
            ind_options,
            format_func=lambda i: f"{ind_labels.get(i, i)}",
            key="score_industry",
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

    def fmt_row(cas: str) -> str:
        r = filtered[filtered["cas"] == cas].iloc[0]
        pin = "⭐ " if r["is_pinned"] else ""
        nm = r["_display_name"] or cas
        return f"{pin}{nm}　[{cas}]　— {r['category_label_ja']}"

    cas_options = filtered["cas"].tolist()

    # --- Comparison mode toggle ---
    compare_mode = st.toggle(
        "🔀 比較モード（2-4物質をレーダー重ね描き）",
        value=False,
        key="score_compare_toggle",
        help="ONにすると複数物質を選んで横比較できる",
    )

    if compare_mode:
        # Pre-select pinned items by default for fast demo
        default_cas = [c for c in cas_options if filtered[filtered["cas"] == c].iloc[0]["is_pinned"]][:3]
        selected_cas_list = st.multiselect(
            "物質を選択（最大4件）",
            cas_options,
            default=default_cas,
            format_func=fmt_row,
            max_selections=4,
            key="score_cas_multi",
        )
        if not selected_cas_list:
            st.warning("物質を1件以上選択してください。")
            return
        render_compare(selected_cas_list, selected_industry)
        return

    selected_cas = st.selectbox(
        "物質を選択",
        cas_options,
        format_func=fmt_row,
        key="score_cas",
    )

    chem = cl.get_chemical(selected_cas)
    if not chem:
        st.error("物質詳細の取得に失敗")
        return

    # --- Compute scores ---
    with st.spinner("7軸スコア計算中..."):
        sub = scoring.compute_all(selected_cas)
        comp = scoring.composite(sub, industry=selected_industry)

    # --- Headline metrics ---
    st.markdown(f"## {chem['display_name']}  <small>　[CAS {chem['cas']}]</small>", unsafe_allow_html=True)
    if chem.get("pinned_note"):
        st.caption(f"📌 {chem['pinned_note']}")

    hm1, hm2, hm3, hm4 = st.columns([1.2, 1, 1, 1])
    if comp["composite"] is not None:
        # Grade color
        grade = comp["grade"]
        grade_colors = {"A": "#10B981", "B": "#22C55E", "C": "#F59E0B", "D": "#FB923C", "E": "#EF4444", "F": "#7F1D1D"}
        gc = grade_colors.get(grade, MUTED)
        hm1.markdown(
            f"<div style='padding:10px;border-radius:10px;background:{gc}15;border:2px solid {gc};text-align:center;'>"
            f"<div style='font-size:11px;color:#475569;'>総合スコア</div>"
            f"<div style='font-size:42px;font-weight:700;color:{gc};line-height:1.0;margin-top:3px;'>{comp['composite']:.0f}</div>"
            f"<div style='font-size:32px;font-weight:700;color:{gc};line-height:1.0;'>{grade}</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        hm1.markdown(
            f"<div style='padding:10px;border-radius:10px;background:#F1F5F9;border:2px dashed {MUTED};text-align:center;'>"
            f"<div style='font-size:11px;color:#475569;'>総合スコア</div>"
            f"<div style='font-size:24px;font-weight:600;color:{MUTED};margin-top:6px;'>評価データ不足</div>"
            f"<div style='font-size:11px;color:#475569;margin-top:3px;'>{comp['scored_axes']}/7軸のみ</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    hm2.metric("評価軸数", f"{comp['scored_axes']} / 7")
    hm3.metric("データ信頼度", {"high": "高", "medium": "中", "low": "低"}.get(comp.get("confidence"), "—"))
    ind_label = cl.industries().get(comp["industry"], {}).get("name_ja", comp["industry"])
    hm4.metric("適用重み", ind_label)

    st.divider()

    # --- Radar chart + sub-score table ---
    col_radar, col_table = st.columns([1.2, 1])
    with col_radar:
        st.markdown("**7軸レーダー** (外周=安定/100, 中心=リスク/0)")
        axes_order = scoring.AXIS_KEYS
        axis_labels = [scoring.AXIS_LABELS_JA[k] for k in axes_order]
        scores = [sub[k]["score"] if sub[k]["score"] is not None else 0 for k in axes_order]
        has_data = [sub[k]["score"] is not None for k in axes_order]
        # Close the polygon
        theta = axis_labels + [axis_labels[0]]
        r_actual = scores + [scores[0]]
        r_ref_caution = [60] * (len(axes_order) + 1)
        r_ref_danger = [30] * (len(axes_order) + 1)

        fig = go.Figure()
        # Background reference rings
        fig.add_trace(go.Scatterpolar(
            r=r_ref_danger, theta=theta, mode="lines", line=dict(color="#FCA5A5", width=1, dash="dot"),
            name="高リスクライン (30)", hoverinfo="skip",
        ))
        fig.add_trace(go.Scatterpolar(
            r=r_ref_caution, theta=theta, mode="lines", line=dict(color="#FDE68A", width=1, dash="dot"),
            name="注意ライン (60)", hoverinfo="skip",
        ))
        # Actual scores
        fig.add_trace(go.Scatterpolar(
            r=r_actual, theta=theta, mode="lines+markers", fill="toself",
            line=dict(color=ACCENT, width=2),
            fillcolor="rgba(15,118,110,0.25)",
            marker=dict(size=8, color=[ACCENT if h else "#CBD5E1" for h in has_data] + [ACCENT if has_data[0] else "#CBD5E1"]),
            name="軸スコア",
            hovertemplate="<b>%{theta}</b><br>%{r:.0f}/100<extra></extra>",
        ))
        fig.update_layout(
            template="plotly_white",
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 100], tickvals=[0, 30, 60, 100],
                                gridcolor="#E2E8F0", tickfont=dict(size=10, color=MUTED)),
                angularaxis=dict(tickfont=dict(size=11, color="#334155"), gridcolor="#E2E8F0"),
                bgcolor="white",
            ),
            showlegend=False,
            height=420,
            margin=dict(l=60, r=60, t=20, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("⚫ 灰色マーカー = 評価データ不足の軸（0点扱いではない）")

    with col_table:
        st.markdown("**軸別サブスコア**")
        tbl_rows = []
        for k in scoring.AXIS_KEYS:
            info = sub[k]
            s = info["score"]
            tbl_rows.append({
                "軸": scoring.AXIS_LABELS_JA[k].replace("軸", "").strip()[:18],
                "スコア": f"{s:.0f}" if s is not None else "—",
                "重み": f"{comp['weights'].get(k, 0)*100:.0f}%",
                "値": str(info["value"])[:30],
            })
        tdf = pd.DataFrame(tbl_rows)
        st.dataframe(tdf, use_container_width=True, hide_index=True, height=330)

        # Notes
        with st.expander("軸別 詳細メモ"):
            for k in scoring.AXIS_KEYS:
                info = sub[k]
                s = f"{info['score']:.0f}" if info["score"] is not None else "—"
                st.markdown(
                    f"**{scoring.AXIS_LABELS_JA[k]}**: {s} 点  \n　{info['note']}",
                    unsafe_allow_html=True,
                )

    st.divider()

    # --- Narrative review ---
    st.markdown("### 📝 総評")
    llm_available = gemini.is_available()
    if llm_available:
        col_a, col_b = st.columns([4, 1])
        with col_b:
            use_llm = st.toggle("LLM生成", value=True, key=f"score_llm_toggle_{selected_cas}",
                                help="Gemini 2.5 Flash で文脈考慮型レビュー生成 (~1秒)")
    else:
        use_llm = False

    if use_llm:
        with st.spinner("Gemini 2.5 Flash で総評生成中..."):
            review = scoring_llm.llm_narrative(chem, sub, comp)
        st.markdown(review)
        st.caption("🤖 Gemini 2.5 Flash 生成 (無料枠 1500 RPD)")
    else:
        review = scoring.narrative(chem, sub, comp)
        st.markdown(review)
        if llm_available:
            st.caption("🔧 ルールベース生成 (上の toggle で LLM 生成に切替可)")
        else:
            st.caption(
                "🔧 ルールベース生成（Gemini key 未設定）。"
                "`~/.config/gemini/keys.json` に `{\"api_key\": \"...\"}` を設置すると LLM 版に切替可"
            )


# ---------- Top-level tabs ----------
tab_overview, tab_score, tab_cross, tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
    ["🏠 Overview", "🏆 総合スコア", "🔗 素材横串", "🏭 軸1 生産能力", "⚖️ 軸2 需給バランス", "🤝 軸3 サプライヤー集中", "🌐 軸4 地政学", "📋 軸5 規制リスク", "💥 軸6 供給途絶", "💹 軸7 価格変動性"]
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

with tab_score:
    render_score()

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
