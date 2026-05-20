"""SDB 供給安定性 dashboard — 7軸プロキシビュー."""
import json
from pathlib import Path

import duckdb
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
COMTRADE_DIR = ROOT / "data" / "comtrade"
ECHA_DIR = ROOT / "data" / "echa"

AXES = [
    ("軸1", "生産能力・新増設", "EDINET XBRLから有報「生産能力」表抽出", False),
    ("軸2", "需給バランス", "石化協月次稼働率 / METI生産動態統計", False),
    ("軸3", "サプライヤー集中度", "EDINET主要販売先 + 業界団体加盟社能力", False),
    ("軸4", "地政学・原産地", "UN Comtrade年次貿易統計（実装済）", True),
    ("軸5", "政策・規制リスク", "ECHA SVHC + 化審法 + 経産省特定重要物資（部分実装）", True),
    ("軸6", "過去の供給途絶", "化工日報RSSのLLMイベント抽出", False),
    ("軸7", "価格変動性", "化工日報市況欄RSSの数値抽出", False),
]

st.set_page_config(page_title="SDB 供給安定性", layout="wide")
st.title("SDB 供給安定性 dashboard")
st.caption("プロジェクト [`202605_sdb-supply-stability`](https://github.com/seanlee-sotas/sotas-sdb-supply-stability) | 7要素プロキシ指標による素材別供給リスクスコアリング")

with st.sidebar:
    st.subheader("プロジェクト7軸ロードマップ")
    for code, name, source, active in AXES:
        icon = "✅" if active else "🚧"
        st.markdown(f"{icon} **{code}** {name}  \n　<small>{source}</small>", unsafe_allow_html=True)
    st.caption("詳細: `Projects/202605_sdb-supply-stability/` (Vault)")


# ---------- shared loaders ----------
@st.cache_data
def load_reporters() -> dict[int, str]:
    path = COMTRADE_DIR / "ref_reporters.json"
    if not path.exists():
        return {}
    return {r["reporterCode"]: r["reporterDesc"] for r in json.loads(path.read_text())}


@st.cache_data
def load_hs_desc() -> dict[str, str]:
    path = COMTRADE_DIR / "ref_hs.json"
    if not path.exists():
        return {}
    out = {}
    for r in json.loads(path.read_text()):
        code = r.get("id", "")
        text = r.get("text", "")
        out[code] = text.split(" - ", 1)[1] if " - " in text else text
    return out


def latest_parquet(directory: Path, prefix: str):
    files = sorted(directory.glob(f"{prefix}_*.parquet"))
    # Prefer full ingest over _quick samples
    non_quick = [p for p in files if "_quick" not in p.stem]
    if non_quick:
        return max(non_quick)
    return max(files) if files else None


# ---------- tab 4: comtrade ----------
def render_axis4():
    parquet = latest_parquet(COMTRADE_DIR, "trade")
    if parquet is None:
        st.error("`data/comtrade/trade_*.parquet` がありません。`uv run python ingest/comtrade.py --quick` を実行してください。")
        return

    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW trade AS SELECT * FROM '{parquet}'")
    reporters = load_reporters()
    hs_desc = load_hs_desc()
    total_rows = con.execute("SELECT COUNT(*) FROM trade").fetchone()[0]

    st.info(
        "**軸4「地政学・原産地」のプロキシビュー** | "
        "UN Comtrade年次貿易統計から、HS6コードごとの世界輸出/輸入の国別集中度を計算。"
        "HHI・Top-Nシェア・単一国依存度で素材別の供給リスクの粗いシグナルを得る。"
    )
    st.caption(f"データ: `{parquet.name}` ({total_rows:,} rows)")

    col_filter1, col_filter2, col_filter3 = st.columns(3)
    with col_filter1:
        hs_codes = [r[0] for r in con.execute("SELECT DISTINCT cmdCode FROM trade ORDER BY cmdCode").fetchall()]
        selected_hs = st.selectbox(
            "HS6コード",
            hs_codes,
            format_func=lambda c: f"{c} — {hs_desc.get(c, '?')[:60]}",
            key="ax4_hs",
        )
    with col_filter2:
        flows = [r[0] for r in con.execute("SELECT DISTINCT flowCode FROM trade").fetchall()]
        flow_labels = {"X": "輸出 (輸出国別シェア)", "M": "輸入 (輸入国別シェア)"}
        selected_flow = st.selectbox("フロー", flows, format_func=lambda x: flow_labels.get(x, x), key="ax4_flow")
    with col_filter3:
        periods = [r[0] for r in con.execute("SELECT DISTINCT period FROM trade ORDER BY period DESC").fetchall()]
        selected_period = st.selectbox("期間", periods, key="ax4_period")

    df = con.execute(
        """
        SELECT reporterCode, primaryValue, qty, netWgt
        FROM trade
        WHERE cmdCode = ? AND flowCode = ? AND period = ?
          AND partner2Code = 0 AND primaryValue > 0
        ORDER BY primaryValue DESC
        """,
        [selected_hs, selected_flow, str(selected_period)],
    ).df()

    if df.empty:
        st.warning("この組み合わせのデータはありません。")
        return

    df["reporter"] = df["reporterCode"].map(lambda c: reporters.get(c, f"M49 {c}"))
    total = df["primaryValue"].sum()
    df["share_pct"] = df["primaryValue"] / total * 100
    hhi = (df["share_pct"] ** 2).sum()

    st.markdown(f"### HS {selected_hs} — {hs_desc.get(selected_hs, '?')}")
    st.caption(f"{flow_labels.get(selected_flow, selected_flow)}　|　{selected_period}年")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("世界貿易額", f"${total / 1e9:,.2f}B")
    c2.metric("報告国数", len(df))
    c3.metric(
        "HHI (0–10000)",
        f"{hhi:,.0f}",
        help="米司法省/FTC基準: <1500 低集中 / 1500–2500 中集中 / >2500 高集中",
    )
    c4.metric("Top-1 シェア", f"{df.iloc[0]['share_pct']:.1f}%", help=str(df.iloc[0]["reporter"]))
    c5.metric("Top-3 シェア", f"{df.head(3)['share_pct'].sum():.1f}%")

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
        """
        WITH per_reporter AS (
          SELECT period, reporterCode, SUM(primaryValue) AS v
          FROM trade
          WHERE cmdCode = ? AND flowCode = ?
            AND partner2Code = 0 AND primaryValue > 0
          GROUP BY period, reporterCode
        ),
        period_total AS (SELECT period, SUM(v) AS total FROM per_reporter GROUP BY period)
        SELECT pr.period, SUM(POW(pr.v / pt.total * 100, 2)) AS hhi
        FROM per_reporter pr JOIN period_total pt USING (period)
        GROUP BY pr.period ORDER BY pr.period
        """,
        [selected_hs, selected_flow],
    ).df()
    if len(trend) > 1:
        st.line_chart(trend.set_index("period")["hhi"], height=300)
    else:
        st.info("現データは1期のみ。多年次推移を見るには `uv run python ingest/comtrade.py` で全期間ingest。")


# ---------- tab 5: regulation ----------
def render_axis5():
    parquet = latest_parquet(ECHA_DIR, "svhc")
    if parquet is None:
        st.error("`data/echa/svhc_*.parquet` がありません。`uv run python ingest/echa.py` を実行してください。")
        return

    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW svhc AS SELECT * FROM '{parquet}'")

    st.info(
        "**軸5「政策・規制リスク」のプロキシビュー** | "
        "EU ECHAのSVHC候補リスト（Substances of Very High Concern）を起点に、"
        "規制対象物質をSDBの素材CASと突合する基盤を構築。化審法・METI特定重要物資・US TSCA・POPs条約は順次追加。"
    )
    st.caption(f"データ: `{parquet.name}`")

    total = con.execute("SELECT COUNT(*) FROM svhc").fetchone()[0]
    with_cas = con.execute("SELECT COUNT(*) FROM svhc WHERE cas_number IS NOT NULL AND cas_number != '-'").fetchone()[0]
    latest_date = con.execute("SELECT MAX(date_of_inclusion) FROM svhc").fetchone()[0]
    reasons = con.execute("SELECT COUNT(DISTINCT reason) FROM svhc").fetchone()[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SVHC 総数", total)
    c2.metric("CAS番号付き", f"{with_cas} / {total}", help="CASなしのものはポリマーや混合物")
    c3.metric("最新収載日", str(latest_date)[:10] if latest_date else "—")
    c4.metric("収載理由 種類数", reasons)

    st.subheader("収載理由の内訳 (Top 10)")
    reason_df = con.execute(
        """SELECT reason, COUNT(*) AS cnt FROM svhc GROUP BY reason ORDER BY cnt DESC LIMIT 10"""
    ).df()
    st.bar_chart(reason_df.set_index("reason")["cnt"], height=320)

    st.subheader("年次収載トレンド")
    yearly = con.execute(
        """SELECT EXTRACT(YEAR FROM date_of_inclusion) AS year, COUNT(*) AS additions
           FROM svhc WHERE date_of_inclusion IS NOT NULL
           GROUP BY year ORDER BY year"""
    ).df()
    if not yearly.empty:
        yearly["year"] = yearly["year"].astype(int)
        st.bar_chart(yearly.set_index("year")["additions"], height=300)

    st.subheader("最新10件（直近の規制追加 = 早期警報）")
    recent = con.execute(
        """SELECT date_of_inclusion, substance_name, cas_number, reason
           FROM svhc ORDER BY date_of_inclusion DESC NULLS LAST LIMIT 10"""
    ).df()
    recent["date_of_inclusion"] = recent["date_of_inclusion"].astype(str).str[:10]
    recent.columns = ["収載日", "物質名", "CAS番号", "理由"]
    st.dataframe(recent, use_container_width=True, hide_index=True)

    with st.expander("CAS番号で検索"):
        q = st.text_input("CAS番号 (例: 110-54-3)", "")
        if q:
            hits = con.execute(
                "SELECT substance_name, cas_number, date_of_inclusion, reason FROM svhc WHERE cas_number = ?",
                [q.strip()],
            ).df()
            if hits.empty:
                st.info(f"CAS {q} はSVHCリストに該当なし。")
            else:
                st.success(f"CAS {q} はSVHC登録済（{len(hits)}件）")
                st.dataframe(hits, use_container_width=True, hide_index=True)


# ---------- Tabs ----------
tab_overview, tab4, tab5, tab_other = st.tabs(
    ["🏠 Overview", "🌐 軸4 地政学", "📋 軸5 規制リスク", "🚧 他軸 (実装待ち)"]
)

with tab_overview:
    st.subheader("プロジェクト全体像")
    st.markdown(
        """
        住友ゴム梶山さんからの要望「SDBで素材ごとの**供給安定性**を見たい」を起点に、
        供給安定性を**7要素**に分解し、それぞれを公開ソース由来のプロキシ指標で代替できる基盤を構築している。

        - **データ収集**: 各軸ごとに ingest スクリプトを `ingest/` に配置、Parquet/JSONで `data/` 配下に蓄積
        - **可視化**: Streamlit + DuckDB でリアルタイムクエリ
        - **配信**: Streamlit Cloud で社内メンバーに URL 共有（リモート前提）
        - **ソース**: GitHub private `sotas-sdb-supply-stability`
        """
    )

    st.subheader("実装進捗")
    progress_data = []
    for code, name, source, active in AXES:
        progress_data.append({"軸": code, "要素": name, "状態": "✅ 実装済" if active else "🚧 未着手", "ソース": source})
    import pandas as pd
    st.dataframe(pd.DataFrame(progress_data), use_container_width=True, hide_index=True)

    st.caption("各軸の詳細は上のタブから。Overviewはセクションの全体像ガイド。")

with tab4:
    render_axis4()

with tab5:
    render_axis5()

with tab_other:
    st.markdown(
        """
        ### 未実装の軸（順次着手）

        - **軸1 生産能力・新増設** — EDINET API（既に443社XBRL取得済）から有報「生産能力」セクション抽出。`/research-company-jp` skillの成果物を活用
        - **軸2 需給バランス** — 石油化学工業協会の月次エチレン稼働率PDF + METI化学工業生産動態統計
        - **軸3 サプライヤー集中度** — EDINET主要販売先 + 業界団体加盟社別能力データの統合
        - **軸6 過去の供給途絶** — 既vault `3. RSS/化学工業日報`等のRSSアーカイブからLLM抽出（FM発令・事故・停止）
        - **軸7 価格変動性** — 同RSSの「市況欄」から数値時系列抽出 + METI基準ナフサ価格

        各軸のデータが揃い次第、このタブから分岐させていく。
        """
    )
