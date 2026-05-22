"""SDB Mock for Sumitomo Rubber — エントリポイント.

Cloud では Main file path に `app/sumitomo_app.py` を指定。
st.navigation でサイドバーのラベルを明示的に上書きしている (デフォルトの
ファイル名→ラベル変換だと "sumitomo app" 等になってしまうため)。
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(
    page_title="SDB 供給リスク評価方法ブレスト用Mock",
    page_icon="🛞",
    layout="wide",
)


def _home():
    """ホーム (Main) — 事業マップ・物質グリッド."""
    import json as _json
    import sumitomo_loader as sl

    meta = sl.load_metadata()
    segments = sl.load_segments()
    layers = sl.load_layers()
    materials = sl.load_materials()
    citations = sl.load_citations()

    st.title("🛞 SDB 供給リスク評価方法ブレスト用Mock")
    st.caption(
        f"出典: {meta['source_company']} {meta['fiscal_year']} 有価証券報告書・統合報告書 "
        f"／ {len(materials)}物質（pinned {(materials['status']=='pinned').sum()}, "
        f"watch {(materials['status']=='watch').sum()}） "
        f"／ 引用 {len(citations)}件"
    )

    st.markdown(
        """
住友ゴム工業の公開資料から抽出した「**今使っている物質**」と「**これから使いたい（と思われる）物質**」を起点に、
**供給リスク評価の切り口を議論するための叩き台** です。

#### 使い方
1. **🛞 Main（このページ）** — 4事業セグメントから物質を探す
2. **🔬 物質詳細** — 物質単体の出典・7軸スコア・懸念要因
3. **📊 元データ閲覧** — 7軸の生データとカラム定義
4. **📚 出典・methodology** — 抽出手法・3層信頼度・公開資料一覧
"""
    )

    st.divider()

    st.subheader("住友ゴム工業 事業構成")

    seg_keys = ["tire", "sports", "industrial", "new_business"]
    cols = st.columns(len(seg_keys))
    for col, sk in zip(cols, seg_keys):
        seg = segments[sk]
        seg_mats = materials[materials["primary_segment"] == sk]
        pinned_n = (seg_mats["status"] == "pinned").sum()
        watch_n = (seg_mats["status"] == "watch").sum()

        with col:
            st.markdown(f"### {seg['icon']} {seg['label']}")
            if seg["revenue_share"] > 0:
                st.metric(
                    "売上収益",
                    f"{seg['revenue_jpy_m']/1000:.0f} 億円",
                    f"構成比 {seg['revenue_share']*100:.1f}%",
                )
            else:
                st.metric("売上収益", "—", "新規事業候補")
            st.caption(seg["description"])
            st.write(f"**{pinned_n}** 物質 (pinned) + **{watch_n}** 物質 (watch)")

    st.divider()

    with st.expander("📖 凡例：出典 layer の意味", expanded=False):
        for lk, lv in layers.items():
            st.markdown(
                f"<span style='display:inline-block;width:1.2em;height:1.2em;background:{lv['color']};"
                f"border-radius:0.2em;vertical-align:middle;margin-right:0.4em;'></span>"
                f"**Layer {lk}: {lv['label']}** — {lv['description']}",
                unsafe_allow_html=True,
            )

    st.subheader("🎯 物質グリッド（事業マップ）")

    tabs = st.tabs([f"{segments[k]['icon']} {segments[k]['label']}" for k in seg_keys])

    for tab, sk in zip(tabs, seg_keys):
        with tab:
            seg_mats = materials[materials["primary_segment"] == sk].reset_index(drop=True)
            if not len(seg_mats):
                st.info("該当物質なし")
                continue

            status_choice = st.radio(
                "区分",
                options=["all", "pinned", "watch"],
                format_func=lambda x: {
                    "all": f"📦 全部 ({len(seg_mats)})",
                    "pinned": f"⭐ いま使っている ({(seg_mats['status']=='pinned').sum()})",
                    "watch": f"👀 これから使いたい ({(seg_mats['status']=='watch').sum()})",
                }[x],
                horizontal=True,
                key=f"status_{sk}",
            )
            if status_choice != "all":
                view = seg_mats[seg_mats["status"] == status_choice].reset_index(drop=True)
            else:
                view = seg_mats

            st.caption(f"{len(view)} 物質表示中")

            N_COLS = 3
            for row_start in range(0, len(view), N_COLS):
                row = view.iloc[row_start : row_start + N_COLS]
                row_cols = st.columns(N_COLS)
                for col, (_, m) in zip(row_cols, row.iterrows()):
                    with col:
                        layer = layers[m["evidence_layer"]]
                        status_badge = "⭐ pinned" if m["status"] == "pinned" else "👀 watch"
                        cas_str = m["cas"] if m["cas"] else "CAS未確定"
                        hs6_str = m["hs6"] if m["hs6"] else "—"

                        with st.container(border=True):
                            st.markdown(
                                f"<div style='border-left:6px solid {layer['color']};"
                                f"padding-left:0.6em;margin-bottom:0.4em;'>"
                                f"<span style='font-size:0.78em;color:{layer['color']};font-weight:600;'>"
                                f"Layer {m['evidence_layer']} · {layer['label']}</span><br>"
                                f"<span style='font-weight:600;font-size:1.05em;'>{m['name_ja']}</span>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                            st.caption(
                                f"{status_badge}  ·  CAS: `{cas_str}`  ·  HS6: `{hs6_str}`"
                            )
                            if m["usage_note"]:
                                st.markdown(
                                    f"<small>{m['usage_note']}</small>",
                                    unsafe_allow_html=True,
                                )

                            tags = _json.loads(m["risk_tags"]) if m["risk_tags"] else []
                            if tags:
                                tag_html = " ".join(
                                    f"<span style='background:#F1F5F9;padding:0.1em 0.5em;"
                                    f"border-radius:0.4em;font-size:0.75em;margin-right:0.25em;'>{t}</span>"
                                    for t in tags
                                )
                                st.markdown(tag_html, unsafe_allow_html=True)

                            st.caption(f"出典: {m['citation_count']} 件")

                            if st.button(
                                "🔬 詳細を見る",
                                key=f"detail_{m['id']}",
                                use_container_width=True,
                            ):
                                st.session_state["selected_material_id"] = m["id"]
                                st.switch_page("pages/01_物質詳細.py")

    st.divider()
    st.caption(
        "© Sotas — このMockは discussion purpose。"
    )


pg = st.navigation([
    st.Page(_home, title="Main", default=True, icon="🛞"),
    st.Page("pages/01_物質詳細.py", title="物質詳細", icon="🔬"),
    st.Page("pages/02_軸データブラウザ.py", title="元データ閲覧", icon="📊"),
    st.Page("pages/03_出典methodology.py", title="出典methodology", icon="📚"),
])
pg.run()
