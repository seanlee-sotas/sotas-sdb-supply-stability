"""SDB Supply Stability dashboard — Comtrade trade concentration view."""
import json
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "comtrade"

st.set_page_config(page_title="SDB Supply Stability", layout="wide")
st.title("SDB Supply Stability — Comtrade Snapshot")
st.caption("UN Comtrade annual trade by HS6 code. Concentration metrics: HHI, Top-N share, single-country dependency.")


@st.cache_data
def load_reporters() -> dict[int, str]:
    path = DATA_DIR / "ref_reporters.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text())
    return {r["reporterCode"]: r["reporterDesc"] for r in rows}


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
    st.error("No trade_*.parquet found in data/comtrade/. Run `uv run python ingest/comtrade.py --quick` first.")
    st.stop()

reporters = load_reporters()
st.caption(f"Data file: `{latest.name}` ({con.execute('SELECT COUNT(*) FROM trade').fetchone()[0]:,} rows)")

with st.sidebar:
    st.header("Filters")
    hs_codes = [r[0] for r in con.execute("SELECT DISTINCT cmdCode FROM trade ORDER BY cmdCode").fetchall()]
    selected_hs = st.selectbox("HS6 code", hs_codes)

    flows = [r[0] for r in con.execute("SELECT DISTINCT flowCode FROM trade").fetchall()]
    flow_labels = {"X": "Exports (by origin country)", "M": "Imports (by destination country)"}
    selected_flow = st.selectbox("Flow", flows, format_func=lambda x: flow_labels.get(x, x))

    periods = [r[0] for r in con.execute("SELECT DISTINCT period FROM trade ORDER BY period DESC").fetchall()]
    selected_period = st.selectbox("Period", periods)

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
    st.warning("No data for this combination.")
    st.stop()

df["reporter"] = df["reporterCode"].map(lambda c: reporters.get(c, f"M49 {c}"))
total = df["primaryValue"].sum()
df["share_pct"] = df["primaryValue"] / total * 100

hhi = (df["share_pct"] ** 2).sum()
top1_share = df.iloc[0]["share_pct"]
top3_share = df.head(3)["share_pct"].sum()
top5_share = df.head(5)["share_pct"].sum()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total trade", f"${total / 1e9:,.2f}B")
c2.metric("Reporters", len(df))
c3.metric("HHI (0–10000)", f"{hhi:,.0f}", help="<1500 unconcentrated · 1500–2500 moderate · >2500 highly concentrated (DOJ/FTC bands)")
c4.metric("Top-1 share", f"{top1_share:.1f}%")
c5.metric("Top-3 share", f"{top3_share:.1f}%")

st.subheader(f"Top 20 reporters — HS {selected_hs} · {flow_labels.get(selected_flow, selected_flow)} · {selected_period}")
top20 = df.head(20).set_index("reporter")[["primaryValue"]]
st.bar_chart(top20, height=400)

with st.expander("Full ranking table"):
    display = df.assign(
        primaryValue=df["primaryValue"].map(lambda v: f"${v / 1e6:,.1f}M"),
        share_pct=df["share_pct"].map(lambda v: f"{v:.2f}%"),
    )[["reporter", "primaryValue", "share_pct", "qty", "netWgt"]]
    display.columns = ["Reporter", "Value (USD)", "Share", "Qty", "Net Weight (kg)"]
    st.dataframe(display, use_container_width=True, hide_index=True)

st.subheader("Cross-period HHI trend (this HS code, this flow)")
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
    st.info("Single period in dataset — run ingest without --quick to get multi-year trend.")
