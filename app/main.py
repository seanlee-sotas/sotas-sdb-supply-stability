"""SDB 供給安定性 dashboard — 7軸プロキシビュー."""
import json
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
COMTRADE_DIR = ROOT / "data" / "comtrade"
ECHA_DIR = ROOT / "data" / "echa"
REG_DIR = ROOT / "data" / "regulations"
SEC_DIR = ROOT / "data" / "sec"
EDINET_DIR = ROOT / "data" / "edinet"
WB_DIR = ROOT / "data" / "worldbank"

AXES = [
    ("軸1", "生産能力・新増設", "EDINET MD（443社）から「生産能力」スニペット抽出", True),
    ("軸2", "需給バランス", "石化協月次稼働率 / METI生産動態統計", False),
    ("軸3", "サプライヤー集中度", "EDINET主要販売先 + 業界団体加盟社能力", False),
    ("軸4", "地政学・原産地", "UN Comtrade年次貿易統計", True),
    ("軸5", "政策・規制リスク", "ECHA SVHC + METI特定重要物資 + Stockholm POPs", True),
    ("軸6", "過去の供給途絶", "SEC EDGAR 8-K (米化学メジャー15社)", True),
    ("軸7", "価格変動性", "World Bank Pink Sheet 月次商品価格 (1960–)", True),
]

st.set_page_config(page_title="SDB 供給安定性", layout="wide")
st.title("SDB 供給安定性 dashboard")
st.caption("[`202605_sdb-supply-stability`](https://github.com/seanlee-sotas/sotas-sdb-supply-stability) | 7要素プロキシ指標による素材別供給リスクの可視化")

with st.sidebar:
    st.subheader("プロジェクト7軸ロードマップ")
    for code, name, source, active in AXES:
        icon = "✅" if active else "🚧"
        st.markdown(f"{icon} **{code}** {name}  \n　<small>{source}</small>", unsafe_allow_html=True)
    st.divider()
    st.caption("詳細: `Projects/202605_sdb-supply-stability/` (Vault)")


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
    st.bar_chart(df.head(20).set_index("reporter")[["primaryValue"]], height=400)

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
        st.line_chart(trend.set_index("period")["hhi"], height=300)
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
            st.bar_chart(reason_df.set_index("reason")["cnt"], height=280)

            st.markdown("**年次収載トレンド（規制リスクの早期警報）**")
            yearly = con.execute(
                """SELECT EXTRACT(YEAR FROM date_of_inclusion) AS year, COUNT(*) AS additions
                   FROM svhc WHERE date_of_inclusion IS NOT NULL
                   GROUP BY year ORDER BY year"""
            ).df()
            if not yearly.empty:
                yearly["year"] = yearly["year"].astype(int)
                st.bar_chart(yearly.set_index("year")["additions"], height=240)

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
    st.bar_chart(by_co.set_index("ticker")["filings"], height=280)

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

    df = con.execute(
        """SELECT date, price, unit FROM prices
           WHERE commodity = ?
             AND date >= date_sub(current_date, INTERVAL ? YEAR)
           ORDER BY date""",
        [selected, years_back],
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
    st.line_chart(df.set_index("date")["price"], height=320)

    st.subheader("YoY 変化率（前年同月比）")
    st.line_chart(df.set_index("date")["yoy_pct"], height=240)

    st.subheader("年率ボラティリティ（12ヶ月rolling）")
    st.line_chart(df.set_index("date")["rolling_vol_12m"], height=240)

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


# ---------- Top-level tabs ----------
tab_overview, tab1, tab4, tab5, tab6, tab7, tab_other = st.tabs(
    ["🏠 Overview", "🏭 軸1 生産能力", "🌐 軸4 地政学", "📋 軸5 規制リスク", "💥 軸6 供給途絶", "💹 軸7 価格変動性", "🚧 他軸 (実装待ち)"]
)

with tab_overview:
    st.subheader("プロジェクト全体像")
    st.markdown(
        """
        住友ゴム梶山さんからの要望「SDBで素材ごとの**供給安定性**を見たい」を起点に、
        供給安定性を**7要素**に分解し、各要素を公開ソース由来のプロキシ指標で機械算出する基盤を構築。

        - **データ収集**: 各軸ごとに ingest スクリプトを `ingest/` に配置、Parquet/JSONで `data/` 配下に蓄積
        - **可視化**: Streamlit + DuckDB でリアルタイムクエリ。データはGit-committedで再現性確保
        - **配信**: Streamlit Cloud で社内メンバーに URL 共有（リモート前提・自前インフラ不要）
        - **ソース**: GitHub private [`sotas-sdb-supply-stability`](https://github.com/seanlee-sotas/sotas-sdb-supply-stability)
        """
    )

    st.subheader("実装進捗")
    progress = []
    for code, name, source, active in AXES:
        progress.append({"軸": code, "要素": name, "状態": "✅ 実装済" if active else "🚧 未着手", "データソース": source})
    st.dataframe(pd.DataFrame(progress), use_container_width=True, hide_index=True)
    st.caption("各軸の詳細は上のタブから。新しい軸が ingest 完了次第、順次タブを追加していく。")

with tab1:
    render_axis1()

with tab4:
    render_axis4()

with tab5:
    render_axis5()

with tab6:
    render_axis6()

with tab7:
    render_axis7()

with tab_other:
    st.markdown(
        """
        ### 未実装の軸

        - **軸2 需給バランス** — 石油化学工業協会の月次エチレン稼働率PDF + METI化学工業生産動態統計（月次品目別生産量）
        - **軸3 サプライヤー集中度** — EDINET主要販売先 + 業界団体加盟社別能力データを統合してHHI算出

        各軸のingest基盤が完成次第、このタブから分岐させる。
        """
    )
