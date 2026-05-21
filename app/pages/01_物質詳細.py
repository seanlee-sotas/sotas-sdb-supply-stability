"""物質詳細 — 選択した物質の出典・7軸スコア・懸念要因を集約表示."""

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sumitomo_loader as sl  # noqa: E402
import scoring  # noqa: E402

# CAS / id → USGS 鉱物データ element key (data/usgs/mineral_concentration*.parquet 参照用)
CAS_TO_USGS_ELEMENT = {
    "7440-33-7":   "W",
    "1314-13-2":   "Zn",
    "12136-58-2":  "Li",
    "7782-42-5":   "C_graphite",
    "7704-34-9":   "S",
    "7631-86-9":   "Si_metal",
}
ID_TO_USGS_ELEMENT = {
    "titanium_alloy":  "Ti",
    "steel_cord":      "Cu",  # 真鍮メッキ
}

# 戦略物資フラグ参照用 token
CAS_TO_STRATEGIC_TOKEN = {
    "7440-33-7":  "W",
    "1314-13-2":  "Zn",
    "12136-58-2": "Li",
    "7782-42-5":  "C_graphite",
    "7704-34-9":  "S",
    "7631-86-9":  "Si_metal",
    "9006-04-6":  "natural_rubber",
}
ID_TO_STRATEGIC_TOKEN = {
    "titanium_alloy": "Ti",
    "steel_cord": "Cu",
    "automotive_semiconductor": "semiconductor",
    "li_s_battery_sulfur": "battery",
    "li_compounds": "Li",
    "graphene": "C_graphite",
}

# 天然ゴム系物質 (FAOSTAT 国別生産表示対象)
NR_CASES = {"9006-04-6"}
NR_IDS = {
    "eudr_compliant_nr", "enr_epoxidized_nr", "dpnr_high_purity",
    "ldp_natural_rubber_latex", "high_damping_rubber",
    "new_marine_fender",
}


@st.cache_data(show_spinner=False)
def _load_usgs_concentration() -> pd.DataFrame:
    base = Path(__file__).resolve().parents[2] / "data" / "usgs"
    files = sorted(base.glob("mineral_concentration_2*.parquet"))
    files = [f for f in files if "summary" not in f.stem]
    if not files:
        return pd.DataFrame()
    return pd.read_parquet(files[-1])


@st.cache_data(show_spinner=False)
def _load_strategic_flags() -> pd.DataFrame:
    base = Path(__file__).resolve().parents[2] / "data" / "regulations"
    files = sorted(base.glob("strategic_materials_*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.read_parquet(files[-1])


@st.cache_data(show_spinner=False)
def _load_faostat_nr() -> pd.DataFrame:
    base = Path(__file__).resolve().parents[2] / "data" / "faostat"
    files = sorted(base.glob("natural_rubber_production_*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.read_parquet(files[-1])


def _val(v):
    """Return None when v is None or NaN; else return v unchanged."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    return v

st.set_page_config(
    page_title="物質詳細 | SDB Mock",
    page_icon="🔬",
    layout="wide",
)

materials = sl.load_materials()
segments = sl.load_segments()
layers = sl.load_layers()

# -----------------------------------------------------------------------------
# Material 選択
# -----------------------------------------------------------------------------

st.title("🔬 物質詳細")

selected_id = st.session_state.get("selected_material_id")

# サイドバーで物質を切替可能に
with st.sidebar:
    st.markdown("### 物質選択")
    seg_filter = st.selectbox(
        "事業セグメント",
        options=["all"] + list(segments.keys()),
        format_func=lambda x: "全て" if x == "all" else f"{segments[x]['icon']} {segments[x]['label']}",
        index=0,
    )
    status_filter = st.selectbox(
        "区分",
        options=["all", "pinned", "watch"],
        format_func=lambda x: {"all": "全て", "pinned": "⭐ いま使ってる", "watch": "👀 これから使いたい"}[x],
        index=0,
    )

    view = materials
    if seg_filter != "all":
        view = view[view["primary_segment"] == seg_filter]
    if status_filter != "all":
        view = view[view["status"] == status_filter]
    view = view.reset_index(drop=True)

    options = view["id"].tolist()
    if not options:
        st.info("条件に合う物質がありません")
        st.stop()

    default_idx = options.index(selected_id) if selected_id in options else 0
    selected_id = st.selectbox(
        "物質",
        options=options,
        format_func=lambda x: view[view["id"] == x]["name_ja"].iloc[0],
        index=default_idx,
    )
    st.session_state["selected_material_id"] = selected_id

m = sl.get_material(selected_id)
if m is None:
    st.error("物質が見つかりません")
    st.stop()

# -----------------------------------------------------------------------------
# ヘッダ: 物質基本情報
# -----------------------------------------------------------------------------

# pandas DataFrame → dict は None を NaN に変換するため、表示前にクリーンアップ
for k in ("cas", "pubchem_cid", "iupac_name", "molecular_formula", "molecular_weight",
          "inchikey", "smiles", "category_norm", "hs6", "hs_label", "usage_note",
          "name_en", "risk_tags", "is_pseudo_cas"):
    m[k] = _val(m.get(k))

# pseudo CAS の物質も scoring 可能。UI 表示では「未確定」扱いだが scoring には渡す
m["display_cas"] = m["cas"] if not m.get("is_pseudo_cas") else None
m["scoring_cas"] = m["cas"]  # always pass to scoring (pseudo CAS は chemicals.parquet にエントリ済み)

layer = layers[m["evidence_layer"]]
seg = segments[m["primary_segment"]]
mat_segments = json.loads(m["segments"])

col_left, col_right = st.columns([3, 2])
with col_left:
    st.markdown(
        f"<div style='border-left:8px solid {layer['color']};padding-left:0.8em;'>"
        f"<div style='font-size:0.85em;color:{layer['color']};font-weight:600;'>"
        f"Layer {m['evidence_layer']} · {layer['label']}</div>"
        f"<h2 style='margin:0.1em 0 0.2em 0;'>{m['name_ja']}</h2>"
        f"<div style='color:#666;'>{m['name_en'] or ''}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # 事業ラベル（複数事業に展開）
    badge_html = ""
    for seg_key in mat_segments:
        s = segments.get(seg_key)
        if not s:
            continue
        is_primary = seg_key == m["primary_segment"]
        weight = "600" if is_primary else "400"
        opacity = "1" if is_primary else "0.65"
        badge_html += (
            f"<span style='background:#F1F5F9;padding:0.25em 0.7em;border-radius:0.5em;"
            f"margin-right:0.4em;font-weight:{weight};opacity:{opacity};'>"
            f"{s['icon']} {s['label']}{' (主)' if is_primary else ''}</span>"
        )
    st.markdown(badge_html, unsafe_allow_html=True)

    st.markdown(f"**用途:** {m['usage_note'] or '—'}")

with col_right:
    status_emoji = "⭐ いま使っている (pinned)" if m["status"] == "pinned" else "👀 これから使いたい (watch)"
    st.markdown(f"### {status_emoji}")
    if m.get("is_pseudo_cas"):
        st.metric("CAS", "未確定", f"pseudo: {m['cas']}")
    else:
        st.metric("CAS", m["cas"] if m["cas"] else "未確定")
    if m["pubchem_cid"]:
        st.metric("PubChem CID", f"{int(m['pubchem_cid'])}")
    if m["hs6"]:
        st.metric("HS6", m["hs6"])

# 化学情報の細部
if m["cas"]:
    with st.expander("🧪 化学情報"):
        info_cols = st.columns(3)
        info_cols[0].markdown(f"**IUPAC**:  \n{m['iupac_name'] or '—'}")
        info_cols[1].markdown(f"**分子式**: {m['molecular_formula'] or '—'}")
        info_cols[2].markdown(f"**分子量**: {m['molecular_weight'] or '—'}")
        info_cols[0].markdown(f"**InChIKey**: `{m['inchikey'] or '—'}`")
        info_cols[1].markdown(f"**SMILES**: `{m['smiles'] or '—'}`")
        info_cols[2].markdown(f"**カテゴリ**: {m['category_norm'] or '—'}")
        if m["pubchem_cid"]:
            st.markdown(f"[🔗 PubChem で開く](https://pubchem.ncbi.nlm.nih.gov/compound/{int(m['pubchem_cid'])})")

# リスクタグ
tags = json.loads(m["risk_tags"]) if m["risk_tags"] else []
if tags:
    st.markdown("**リスクタグ:** " + " ".join(
        f"<span style='background:#FEE2E2;color:#991B1B;padding:0.15em 0.55em;"
        f"border-radius:0.4em;font-size:0.85em;margin-right:0.25em;'>{t}</span>"
        for t in tags
    ), unsafe_allow_html=True)

st.divider()

# -----------------------------------------------------------------------------
# 出典カード
# -----------------------------------------------------------------------------

st.subheader("📜 出典・根拠")
st.caption(
    f"このMockでは、各物質を **{layer['label']}** の根拠で住友ゴム関連と判定しています。"
)

citations = sl.get_citations(selected_id)
if not len(citations):
    st.info("出典登録なし")
else:
    for _, c in citations.iterrows():
        line_str = f" 行{int(c['line'])}" if c['line'] is not None and str(c['line']) != 'nan' else ""
        try:
            line_val = c['line']
            line_str = f" 行{int(line_val)}" if line_val and not (isinstance(line_val, float) and (line_val != line_val)) else ""
        except Exception:
            line_str = ""
        with st.container(border=True):
            st.markdown(
                f"<span style='background:{layer['color']};color:white;padding:0.1em 0.6em;"
                f"border-radius:0.3em;font-size:0.8em;font-weight:600;'>{c['source']}{line_str}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(f"> {c['text']}")

st.divider()

# -----------------------------------------------------------------------------
# 7軸スコア & 懸念要因
# -----------------------------------------------------------------------------

st.subheader("📊 供給リスク評価（7軸）")

if not m["cas"]:
    st.warning(
        "⚠️ この物質は **CAS未確定** (配合系・業界常識ベース) のため、CASキー駆動の軸スコア（軸2/4/5/6/7）は算出できません。"
        "出典に基づくウォッチ対象として登録されています。"
    )
    st.info("CAS未確定物質も含めて評価する手法は **[📚 出典・methodology]** ページの「未確定物質の扱い」セクション参照")
else:
    if m.get("is_pseudo_cas"):
        st.info(
            f"ℹ️ この物質は配合系・業界常識ベースのため CAS未確定です。**pseudo CAS** `{m['cas']}` を発行して "
            f"HS6 推定・規制リスト・SECイベント等のスコアを計算しています（出典 layer B/C）。"
        )
    industry = st.selectbox(
        "業界別重みプロファイル",
        options=["default", "rubber_tire", "semiconductor", "pharma_intermediate", "commodity_plastic"],
        index=1 if m["primary_segment"] == "tire" else 0,
        help="industries[].weights で軸スコアを重み付け平均し、総合スコアを算出します",
    )

    with st.spinner("7軸スコアを計算中..."):
        sub = scoring.compute_all(m["cas"])
        comp = scoring.composite(sub, industry=industry) if sub else None

    if not sub:
        st.warning("既存 chemicals.parquet に物質が登録されていないためスコア計算できません")
    else:
        col_score, col_radar = st.columns([1, 2])

        with col_score:
            if comp and comp.get("composite") is not None:
                grade = comp["grade"]
                color_map = {"A": "#0F766E", "B": "#65A30D", "C": "#CA8A04", "D": "#EA580C", "F": "#DC2626", "—": "#6B7280"}
                gc = color_map.get(grade, "#6B7280")
                st.markdown(
                    f"<div style='text-align:center;padding:1em 0.5em;border:2px solid {gc};"
                    f"border-radius:1em;'>"
                    f"<div style='font-size:0.85em;color:#666;'>総合スコア</div>"
                    f"<div style='font-size:3em;font-weight:700;color:{gc};line-height:1;'>{int(comp['composite'])}</div>"
                    f"<div style='font-size:2em;font-weight:700;color:{gc};'>{grade}</div>"
                    f"<div style='font-size:0.75em;color:#999;margin-top:0.3em;'>"
                    f"信頼度: {comp['confidence']} · {comp['scored_axes']}/{comp['total_axes']}軸</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.info(f"評価可能軸: {comp['scored_axes'] if comp else 0}/7 — 総合スコア suppressed")

        with col_radar:
            axis_labels = {
                "axis1_capacity": "🏭 軸1\n生産能力",
                "axis2_supply_demand": "⚖️ 軸2\n需給",
                "axis3_jp_concentration": "🤝 軸3\n国内集中",
                "axis4_global_hhi": "🌐 軸4\n地政学",
                "axis5_regulation": "📋 軸5\n規制",
                "axis6_events": "💥 軸6\n供給途絶",
                "axis7_price": "💹 軸7\n価格変動",
            }
            r_vals, theta_labels = [], []
            for k, label in axis_labels.items():
                s = sub.get(k, {})
                r = s.get("score")
                r_vals.append(r if r is not None else 0)
                theta_labels.append(label)
            r_vals.append(r_vals[0])
            theta_labels.append(theta_labels[0])

            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(
                r=[60] * len(theta_labels),
                theta=theta_labels,
                line=dict(color="#FDE68A", dash="dot"),
                fill=None, name="注意ライン",
            ))
            fig.add_trace(go.Scatterpolar(
                r=[30] * len(theta_labels),
                theta=theta_labels,
                line=dict(color="#FCA5A5", dash="dot"),
                fill=None, name="危険ライン",
            ))
            fig.add_trace(go.Scatterpolar(
                r=r_vals,
                theta=theta_labels,
                fill="toself",
                line=dict(color="#0F766E", width=2),
                fillcolor="rgba(15,118,110,0.25)",
                name=m["name_ja"],
            ))
            fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=False,
                height=380,
                margin=dict(l=40, r=40, t=20, b=20),
                template="simple_white",
            )
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("### 軸別 懸念要因の詳細")

        for axis_key, axis_label in [
            ("axis1_capacity", "🏭 軸1 生産能力・新増設"),
            ("axis2_supply_demand", "⚖️ 軸2 需給バランス"),
            ("axis3_jp_concentration", "🤝 軸3 国内供給集中度"),
            ("axis4_global_hhi", "🌐 軸4 地政学・原産地集中"),
            ("axis5_regulation", "📋 軸5 規制・政策"),
            ("axis6_events", "💥 軸6 過去の供給途絶イベント"),
            ("axis7_price", "💹 軸7 価格変動性"),
        ]:
            s = sub.get(axis_key, {})
            score = s.get("score")
            with st.container(border=True):
                cols = st.columns([2, 1, 3])
                cols[0].markdown(f"**{axis_label}**")
                if score is None:
                    cols[1].markdown("⚪ 評価不可")
                else:
                    if score >= 70:
                        emoji = "🟢"
                    elif score >= 40:
                        emoji = "🟡"
                    else:
                        emoji = "🔴"
                    cols[1].markdown(f"{emoji} スコア **{int(score)}** / 100")

                detail = s.get("detail") or s.get("rationale") or s.get("reason") or "—"
                cols[2].caption(str(detail)[:300])

        # ---------------------------------------------------------------
        # 地政学・生産地集中 拡張データ (軸4 補強)
        # ---------------------------------------------------------------
        st.markdown("### 🌐 地政学・生産地集中 — 拡張データ")
        st.caption(
            "軸4 (Comtrade HS6 HHI) では拾えない **生産段階の集中度・政策認定リスク** を3ソースで補強します。"
        )

        usgs_element = CAS_TO_USGS_ELEMENT.get(m.get("cas")) or ID_TO_USGS_ELEMENT.get(m["id"])
        strategic_token = CAS_TO_STRATEGIC_TOKEN.get(m.get("cas")) or ID_TO_STRATEGIC_TOKEN.get(m["id"])
        is_nr = (m.get("cas") in NR_CASES) or (m["id"] in NR_IDS)

        if not any([usgs_element, strategic_token, is_nr]):
            st.info(
                "この物質は USGS 鉱物・戦略物資・FAOSTAT NR の3拡張データには対応していません "
                "(配合系・複合素材・有機ポリマー等)。軸4 は Comtrade HS6 のみで評価しています。"
            )
        else:
            geo_tabs = []
            if usgs_element:
                geo_tabs.append("⛏ USGS 国別生産シェア")
            if strategic_token:
                geo_tabs.append("🏛 戦略物資 3国認定フラグ")
            if is_nr:
                geo_tabs.append("🌱 FAOSTAT 天然ゴム国別生産")

            tabs_geo = st.tabs(geo_tabs)
            i = 0

            if usgs_element:
                with tabs_geo[i]:
                    usgs_df = _load_usgs_concentration()
                    sub = usgs_df[usgs_df["element"] == usgs_element].copy()
                    if len(sub):
                        sub = sub.sort_values("share_pct", ascending=False)
                        elem_name = sub.iloc[0]["name"]
                        st.markdown(
                            f"**鉱物**: {elem_name} (元素: `{usgs_element}`)  "
                            f"  ·  **データ年**: {sub.iloc[0]['source_year']}  "
                            f"  ·  **出典**: USGS Mineral Commodity Summaries 2025"
                        )
                        # 棒グラフ
                        fig = px.bar(
                            sub, x="country", y="share_pct",
                            text="share_pct",
                            color="share_pct",
                            color_continuous_scale="Reds",
                            title=f"{elem_name} — 国別生産シェア (世界, {sub.iloc[0]['source_year']})",
                        )
                        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                        fig.update_layout(
                            height=380, template="simple_white",
                            showlegend=False, coloraxis_showscale=False,
                            yaxis_title="世界生産シェア (%)",
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        # HHI 計算
                        hhi = float(((sub[sub["country"] != "Others"]["share_pct"]) ** 2).sum())
                        band = "🔴 高集中" if hhi >= 2500 else ("🟡 中集中" if hhi >= 1500 else "🟢 低集中")
                        top = sub[sub["country"] != "Others"].iloc[0]
                        c1, c2, c3 = st.columns(3)
                        c1.metric("HHI", f"{hhi:.0f}", band)
                        c2.metric("Top 国", top["country"], f"{top['share_pct']:.1f}%")
                        c3.metric("対象元素", usgs_element)
                    else:
                        st.info(f"USGS データに `{usgs_element}` のエントリなし")
                i += 1

            if strategic_token:
                with tabs_geo[i]:
                    flags_df = _load_strategic_flags()
                    hit = flags_df[flags_df["token"] == strategic_token]
                    if len(hit):
                        h = hit.iloc[0]
                        sc = int(h["strategic_count"])
                        # 大判表示
                        color = ["#10B981", "#F59E0B", "#EF4444", "#7C3AED"][min(sc, 3)]
                        st.markdown(
                            f"<div style='background:{color};color:white;padding:0.8em 1em;"
                            f"border-radius:0.5em;text-align:center;'>"
                            f"<span style='font-size:0.85em;'>3地域中 戦略認定</span><br>"
                            f"<span style='font-size:2.5em;font-weight:700;'>{sc} / 3</span><br>"
                            f"<span style='font-size:0.9em;'>{h['name']}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                        st.markdown("")
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            st.markdown("**🇪🇺 EU CRMA 2024**")
                            if bool(h["eu_strategic"]):
                                st.success("✅ Strategic Raw Material (Annex I)")
                            elif bool(h["eu_critical"]):
                                st.warning("⚠️ Critical Raw Material (Annex II)")
                            else:
                                st.caption("— 未認定")
                            st.caption(h["eu_source"])
                        with c2:
                            st.markdown("**🇺🇸 US Critical 2022**")
                            if bool(h["us_critical_2022"]):
                                st.success("✅ 50 Critical Minerals list")
                            else:
                                st.caption("— 未認定")
                            st.caption(h["us_source"])
                        with c3:
                            st.markdown("**🇯🇵 METI 特定重要物資**")
                            if bool(h["meti_critical"]):
                                st.success(f"✅ {h['meti_category']}")
                            else:
                                st.caption("— 未認定")
                            st.caption(h["jp_source"])
                    else:
                        st.info(f"戦略物資データに `{strategic_token}` のエントリなし")
                i += 1

            if is_nr:
                with tabs_geo[i]:
                    fao_df = _load_faostat_nr()
                    if len(fao_df):
                        latest_year = int(fao_df["year"].max())
                        latest = fao_df[fao_df["year"] == latest_year].copy()
                        total = float(latest["value"].sum())
                        latest["share_pct"] = latest["value"] / total * 100
                        latest = latest.sort_values("share_pct", ascending=False)

                        st.markdown(
                            f"**国別 天然ゴム生産量** ({latest_year}年, {latest['unit'].iloc[0]})  "
                            f"  ·  **総生産**: {total:,.0f} kt  "
                            f"  ·  **出典**: {latest.iloc[0]['source']}"
                        )
                        fig = px.bar(
                            latest.head(15), x="area", y="share_pct", text="share_pct",
                            color="share_pct", color_continuous_scale="Greens",
                            title=f"天然ゴム 国別生産シェア ({latest_year}年)",
                        )
                        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                        fig.update_layout(
                            height=380, template="simple_white",
                            showlegend=False, coloraxis_showscale=False,
                            yaxis_title="世界生産シェア (%)",
                            xaxis_title="",
                        )
                        st.plotly_chart(fig, use_container_width=True)

                        hhi_nr = float((latest["share_pct"] ** 2).sum())
                        band = "🔴 高集中" if hhi_nr >= 2500 else ("🟡 中集中" if hhi_nr >= 1500 else "🟢 低集中")
                        c1, c2, c3 = st.columns(3)
                        c1.metric("HHI", f"{hhi_nr:.0f}", band)
                        c2.metric("Top 国", latest.iloc[0]["area"], f"{latest.iloc[0]['share_pct']:.1f}%")
                        c3.metric("ASEAN 5国合計",
                                  f"{latest[latest['area'].isin(['Thailand','Indonesia','Vietnam','Malaysia','Cambodia'])]['share_pct'].sum():.1f}%",
                                  "EUDR 主要対象地域")
                    else:
                        st.info("FAOSTAT NR データ未取得")
                i += 1

        st.markdown("### 総評")
        if comp and sub:
            try:
                import chemicals_loader as cl
                chem = cl.get_chemical(m["cas"])
                if chem:
                    narr = scoring.narrative(chem, sub, comp)
                    st.markdown(narr)
            except Exception as e:
                st.caption(f"総評生成失敗: {e}")

st.divider()
st.caption(
    "🔗 **軸の生データ** を見るには [📊 軸データブラウザ] ページへ  ·  "
    "🔗 **抽出手法** は [📚 出典・methodology] ページへ"
)
