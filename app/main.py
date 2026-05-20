"""SDB 供給安定性 — Comtrade スナップショット (軸4: 地政学・原産地)."""
import json
from pathlib import Path

import duckdb
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "comtrade"

AXES = [
    ("軸1", "生産能力・新増設", "EDINET XBRLから有報「生産能力」表抽出", False),
    ("軸2", "需給バランス", "石化協月次稼働率 / METI生産動態統計", False),
    ("軸3", "サプライヤー集中度", "EDINET主要販売先 + 業界団体加盟社能力", False),
    ("軸4", "地政学・原産地", "UN Comtrade年次貿易統計（本ビュー）", True),
    ("軸5", "政策・規制リスク", "ECHA SVHC + 化審法 + EU PFAS", False),
    ("軸6", "過去の供給途絶", "化工日報RSSのLLMイベント抽出", False),
    ("軸7", "価格変動性", "化工日報市況欄RSSの数値抽出", False),
]

st.set_page_config(page_title="SDB 供給安定性", layout="wide")
st.title("SDB 供給安定性 — Comtrade スナップショット")
st.info(
    "**軸4「地政学・原産地」のプロキシビュー**　|　"
    "UN Comtrade年次貿易統計から、HS6コードごとの世界輸出/輸入の国別集中度を計算。"
    "HHI・Top-Nシェア・単一国依存度の3指標で素材ごとの供給リスクの粗いシグナルを得る。"
)


@st.cache_data
def load_reporters() -> dict[int, str]:
    path = DATA_DIR / "ref_reporters.json"
    if not path.exists():
        return {}
    return {r["reporterCode"]: r["reporterDesc"] for r in json.loads(path.read_text())}


@st.cache_data
def load_hs_desc() -> dict[str, str]:
    path = DATA_DIR / "ref_hs.json"
    if not path.exists():
        return {}
    out = {}
    for r in json.loads(path.read_text()):
        code = r.get("id", "")
        text = r.get("text", "")
        if " - " in text:
            out[code] = text.split(" - ", 1)[1]
        else:
            out[code] = text
    return out


@st.cache_resource
def get_con():
    parquets = sorted(DATA_DIR.glob("trade_*.parquet"))
    if not parquets:
        return None, None
    latest = parquets[-1]
    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW trade AS SELECT * FROM '{latest}'")
    return con, latest


con, latest = get_con()
if con is None:
    st.error("`data/comtrade/trade_*.parquet` がありません。`uv run python ingest/comtrade.py --quick` を先に実行してください。")
    st.stop()

reporters = load_reporters()
hs_desc = load_hs_desc()
total_rows = con.execute("SELECT COUNT(*) FROM trade").fetchone()[0]
st.caption(f"データファイル: `{latest.name}` ({total_rows:,} rows)")

with st.sidebar:
    st.header("フィルタ")
    hs_codes = [r[0] for r in con.execute("SELECT DISTINCT cmdCode FROM trade ORDER BY cmdCode").fetchall()]
    selected_hs = st.selectbox(
        "HS6コード",
        hs_codes,
        format_func=lambda c: f"{c} — {hs_desc.get(c, '（説明なし）')}",
    )

    flows = [r[0] for r in con.execute("SELECT DISTINCT flowCode FROM trade").fetchall()]
    flow_labels = {"X": "輸出 (輸出国別シェア)", "M": "輸入 (輸入国別シェア)"}
    selected_flow = st.selectbox("フロー", flows, format_func=lambda x: flow_labels.get(x, x))

    periods = [r[0] for r in con.execute("SELECT DISTINCT period FROM trade ORDER BY period DESC").fetchall()]
    selected_period = st.selectbox("期間", periods)

    st.divider()
    st.subheader("プロジェクト7軸ロードマップ")
    for code, name, source, active in AXES:
        icon = "✅" if active else "🚧"
        suffix = " ← 本ビュー" if active else ""
        st.markdown(f"{icon} **{code}** {name}{suffix}  \n　<small>{source}</small>", unsafe_allow_html=True)
    st.caption("詳細: `Projects/202605_sdb-supply-stability/` (Vault)")

df = con.execute(
    """
    SELECT reporterCode, primaryValue, qty, netWgt
    FROM trade
    WHERE cmdCode = ? AND flowCode = ? AND period = ?
      AND partner2Code = 0
      AND primaryValue > 0
    ORDER BY primaryValue DESC
    """,
    [selected_hs, selected_flow, str(selected_period)],
).df()

if df.empty:
    st.warning("この組み合わせのデータはありません。")
    st.stop()

df["reporter"] = df["reporterCode"].map(lambda c: reporters.get(c, f"M49 {c}"))
total = df["primaryValue"].sum()
df["share_pct"] = df["primaryValue"] / total * 100

hhi = (df["share_pct"] ** 2).sum()
top1_share = df.iloc[0]["share_pct"]
top3_share = df.head(3)["share_pct"].sum()

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
c4.metric("Top-1 シェア", f"{top1_share:.1f}%", help=f"{df.iloc[0]['reporter']}")
c5.metric("Top-3 シェア", f"{top3_share:.1f}%")

st.subheader("国別シェア Top 20")
top20 = df.head(20).set_index("reporter")[["primaryValue"]]
st.bar_chart(top20, height=400)

with st.expander("全ランキング"):
    display = df.assign(
        primaryValue=df["primaryValue"].map(lambda v: f"${v / 1e6:,.1f}M"),
        share_pct=df["share_pct"].map(lambda v: f"{v:.2f}%"),
    )[["reporter", "primaryValue", "share_pct", "qty", "netWgt"]]
    display.columns = ["国", "貿易額", "シェア", "数量", "正味重量 (kg)"]
    st.dataframe(display, use_container_width=True, hide_index=True)

st.subheader("HHI 年次推移（このHSコード・フロー）")
trend = con.execute(
    """
    WITH per_reporter AS (
      SELECT period, reporterCode, SUM(primaryValue) AS v
      FROM trade
      WHERE cmdCode = ? AND flowCode = ?
        AND partner2Code = 0
        AND primaryValue > 0
      GROUP BY period, reporterCode
    ),
    period_total AS (
      SELECT period, SUM(v) AS total FROM per_reporter GROUP BY period
    )
    SELECT pr.period, SUM(POW(pr.v / pt.total * 100, 2)) AS hhi
    FROM per_reporter pr JOIN period_total pt USING (period)
    GROUP BY pr.period ORDER BY pr.period
    """,
    [selected_hs, selected_flow],
).df()

if len(trend) > 1:
    st.line_chart(trend.set_index("period")["hhi"], height=300)
else:
    st.info("現データは1期のみ。多年次推移を見るには `uv run python ingest/comtrade.py`（--quickなし）で5年分ingest。")
