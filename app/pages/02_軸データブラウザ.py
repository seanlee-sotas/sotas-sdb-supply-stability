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


def latest_parquet(directory: Path, prefix: str, *, exclude_summary: bool = True) -> Path | None:
    """`{prefix}_<datestamp>.parquet` の中で最新を返す。

    `exclude_summary=True` (default) の場合、`{prefix}_summary_*.parquet` のような
    派生ファイル名はメイン取得対象から外す (`chemical_production_*` glob は
    `chemical_production_summary_*` もマッチしてしまうため。summary 系を取りたい時は
    `find_glob` 経由か `exclude_summary=False` を指定)。
    """
    if not directory.exists():
        return None
    files = sorted(directory.glob(f"{prefix}_*.parquet"))
    if exclude_summary:
        files = [f for f in files if "summary" not in f.stem]
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
        "axis1": "⏱ 軸1 短期要因 (直近90日)",
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
    st.subheader("⏱ 軸1 短期要因 (直近90日)")
    st.caption(
        "構造評価軸 (2〜7) を時系列で補正する役割。"
        " マクロ60% (JPCAエチレン稼働率 + 原油Brent 3M変化 + 業界ニュース密度) + "
        " 個別40% (関連メーカー90日イベント + 物質名マッチ記事 + WB商品3M変化) を合成。"
        "  score = 100 - 50 × pressure"
    )
    st.markdown("##### マクロ系シグナル")
    source_inspector.render_source(
        "jpca_utilization", latest_parquet(DATA / "jpca", "jpca_utilization"),
        key_suffix="axis1", expanded=False,
    )
    source_inspector.render_source(
        "wb_prices", latest_parquet(DATA / "worldbank", "prices_monthly"),
        key_suffix="axis1",
    )
    st.markdown("##### 個別系シグナル (物質名マッチ + メーカーイベント)")
    source_inspector.render_source(
        "chem_news", latest_parquet(DATA / "chem_news", "chem_news"),
        key_suffix="axis1",
    )
    source_inspector.render_source(
        "chem_daily", latest_parquet(DATA / "chem_daily", "chem_daily"),
        key_suffix="axis1",
    )
    st.markdown(
        "※ 関連メーカー90日イベントは [💥 軸6 過去の供給途絶] タブの LLM分類済データを直近90日に絞って再利用。"
    )
    with st.expander("📂 旧軸1 (EDINET設備キーワード抽出) — 参考データ", expanded=False):
        st.caption(
            "旧仕様の生産能力スニペット。Phase B (JA alias生成 + product紐付け) を経て"
            "個別物質に紐付ける構想は保留中。当面は参考データ。"
        )
        source_inspector.render_source(
            "edinet_snippets", latest_parquet(DATA / "edinet", "capacity_snippets"),
            key_suffix="axis1-legacy",
        )
        source_inspector.render_source(
            "edinet_structured", latest_parquet(DATA / "edinet", "capacity_structured"),
            key_suffix="axis1-legacy",
        )

elif axis == "axis2":
    st.subheader("⚖️ 軸2 需給バランス")
    st.caption(
        "UN Comtrade 純輸出比率 (X-M)/(X+M) + JPCA エチレン稼働率 + 化学業界 disruption ニュース + **METI 化学工業生産動態統計 (v3新規)**。"
    )
    source_inspector.render_source(
        "comtrade_trade", latest_parquet(DATA / "comtrade", "trade"),
        key_suffix="axis2", expanded=False,
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

    # v3: METI 化学工業生産動態統計
    meti_prod_p = latest_parquet(DATA / "meti_prod", "chemical_production")
    if meti_prod_p and meti_prod_p.exists():
        with st.expander("🏭 METI 化学工業生産動態統計 — 国内品目別月次生産 (v3新規)", expanded=False):
            import pandas as pd
            df_m = pd.read_parquet(meti_prod_p)
            st.markdown(
                "**出典**: [METI 化学工業生産動態統計](https://www.meti.go.jp/statistics/tyo/seidou/result-2.html)  "
                f"  ·  **対象年**: {df_m['year'].iloc[0]}  ·  **品目数**: {df_m['product'].nunique()}"
            )
            st.markdown(
                "**カラム定義**: product (品目) / category / sumitomo_cas (関連CAS) / "
                "year / month / date / production_kt / annual_kt / source"
            )
            st.dataframe(df_m, use_container_width=True, height=400)
        meti_sum_p = find_glob(DATA / "meti_prod", "chemical_production_summary_*.parquet")
        if meti_sum_p:
            with st.expander("🏭 METI 品目別 年間/季節性サマリー", expanded=False):
                st.dataframe(pd.read_parquet(meti_sum_p), use_container_width=True)

elif axis == "axis3":
    st.subheader("🤝 軸3 国内供給集中度")
    st.caption(
        "EDINET スニペット + 手動マッピング (既存) + **環境省 PRTR 実取扱量ベース (v3新規)**。"
    )
    source_inspector.render_source(
        "jp_supplier",
        latest_parquet(DATA / "chemicals", "chemicals_company_map")
        or (DATA / "chemicals" / "chemicals_company_map.parquet"),
        expanded=False,
    )

    st.markdown("---")
    st.markdown("### 🥇 v3新規: 環境省 PRTR — CAS×事業所×取扱量")
    st.markdown(
        "**PRTRデータの破壊力**: 軸3 を「有報スニペット言及社数 (proxy)」から「**実取扱量(kt/年)ベース**」に格上げ。"
        "CAS 逆引きで「6PPDを取扱う日本企業」「カーボンブラック生産事業所」が即出る。"
    )
    prtr_p = latest_parquet(DATA / "prtr", "prtr_by_cas")
    if prtr_p and prtr_p.exists():
        with st.expander("🇯🇵 環境省 PRTR 事業所別データ", expanded=False):
            import pandas as pd
            df_prtr = pd.read_parquet(prtr_p)
            st.markdown(
                f"**出典**: [環境省 PRTR排出移動量データベース]({df_prtr['source_url'].iloc[0]})  "
                f"  ·  **対象年**: {df_prtr['year'].iloc[0]}  ·  **対象CAS**: {df_prtr['cas'].nunique()}  "
                f"  ·  **事業所数**: {df_prtr['company'].nunique()}"
            )
            st.markdown(
                "**カラム定義**: cas / name / company (取扱企業) / site (所在地) / "
                "release_kg (大気/水排出 kg/年) / transfer_kg (移動量 kg/年) / handled_kt (取扱量 kt/年)"
            )
            st.dataframe(df_prtr.sort_values(["cas", "handled_kt"], ascending=[True, False]),
                         use_container_width=True, height=420)

    prtr_sum_p = latest_parquet(DATA / "prtr", "prtr_cas_summary")
    if prtr_sum_p and prtr_sum_p.exists():
        with st.expander("🇯🇵 PRTR CAS別 集中度サマリー", expanded=False):
            import pandas as pd
            df_s = pd.read_parquet(prtr_sum_p)
            st.markdown(
                "**concentration_band**: high (1-2社) / medium (3-5社) / low (6社以上)。"
                "「**従来の有報スニペット count**」と PRTR の「**実取扱量ベース集中度**」を比較すると、"
                "後者の方が「現に誰が取り扱っているか」を反映していて軸3の判断に強い。"
            )
            st.dataframe(df_s.sort_values("n_sites"), use_container_width=True)

elif axis == "axis4":
    st.subheader("🌐 軸4 地政学・原産地集中")
    st.caption(
        "UN Comtrade 世界輸出データから HHI を算出、Top輸出国上位5を抽出。"
        "**生産段階の集中度** は USGS / 戦略物資フラグ / FAOSTAT NR で補強。"
    )
    source_inspector.render_source(
        "comtrade_trade", latest_parquet(DATA / "comtrade", "trade"),
        key_suffix="axis4", expanded=False,
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

    st.markdown("---")
    st.markdown("### 🥈 v3新規: EM-DAT 自然災害 × 産国")
    st.markdown(
        "**地政学×自然災害**: 軸4 集中産国で発生した災害履歴を重ねると、**「タイ洪水時にNR供給途絶」「Texas 冬寒波で米国SBR能力60%停止」**等の "
        "「平時のHHI上は問題ないが、災害時に詰む」リスクが定量化できる。SDB独自のクロス軸。"
    )
    emdat_p = latest_parquet(DATA / "emdat", "disasters")
    if emdat_p and emdat_p.exists():
        with st.expander("🌪 EM-DAT 自然災害DB (1990-2024 主要災害)", expanded=False):
            import pandas as pd
            ed_df = pd.read_parquet(emdat_p)
            st.markdown(
                f"**出典**: [EM-DAT / CRED]({ed_df['source_url'].iloc[0]})  "
                f"  ·  **件数**: {len(ed_df)}  ·  **国数**: {ed_df['country'].nunique()}  "
                f"  ·  **災害種別**: {ed_df['disaster_type'].nunique()}"
            )
            st.markdown(
                "**カラム定義**: country / iso3 / year / disaster_type / event_name / "
                "deaths / affected_m (百万人) / damage_usd_m (百万USD) / industry_impact (sumitomo 関連業界影響)"
            )
            st.dataframe(ed_df.sort_values(["country", "year"]), use_container_width=True, height=420)

    emdat_sum_p = latest_parquet(DATA / "emdat", "disasters_country_summary")
    if emdat_sum_p and emdat_sum_p.exists():
        with st.expander("🌪 国別災害スコア", expanded=False):
            st.dataframe(
                pd.read_parquet(emdat_sum_p).sort_values("disaster_score", ascending=False),
                use_container_width=True,
            )

    st.markdown("---")
    st.markdown("### 🥉 v3新規: USDA FAS PSD 農産物")
    st.markdown(
        "**バイオ原料の上流**: バイオポリオール (Z-STAR XV) のトウモロコシ、テニスフェルトのコットン、籾殻シリカの米、"
        "ヤシ油代替パーム油 — **農産物の国別集中度・季節リスク** を SDB に。"
    )
    usda_p = latest_parquet(DATA / "usda", "psd_crops")
    if usda_p and usda_p.exists():
        with st.expander("🌾 USDA FAS PSD 国別生産", expanded=False):
            import pandas as pd
            u_df = pd.read_parquet(usda_p)
            st.markdown(
                f"**出典**: [USDA FAS PSD]({u_df['source_url'].iloc[0]})  "
                f"  ·  **作物**: {u_df['commodity'].nunique()}  ·  **国数**: {u_df['country'].nunique()}"
            )
            st.dataframe(u_df, use_container_width=True, height=400)
    usda_sum_p = latest_parquet(DATA / "usda", "psd_summary")
    if usda_sum_p and usda_sum_p.exists():
        with st.expander("🌾 作物別 HHI サマリー", expanded=False):
            st.dataframe(pd.read_parquet(usda_sum_p).sort_values("hhi", ascending=False), use_container_width=True)

elif axis == "axis5":
    st.subheader("📋 軸5 規制・政策")
    st.caption(
        "ECHA SVHC (候補) + METI 特定重要物資 + Stockholm POPs + **ECHA REACH Restriction/Authorization (v3新規、規制段階が進んだ物質)**。"
    )
    source_inspector.render_source(
        "echa_svhc", latest_parquet(DATA / "echa", "svhc"), expanded=False,
    )
    source_inspector.render_source(
        "meti_critical", latest_parquet(DATA / "regulations", "meti_critical")
    )
    source_inspector.render_source(
        "pops", latest_parquet(DATA / "regulations", "pops")
    )

    st.markdown("---")
    st.markdown("### 🆕 v3新規: ECHA REACH Restriction / Authorization")
    st.markdown(
        "**SVHC候補の一段上**: Annex XVII (使用制限決定) / Annex XIV (認可必要) に挙がっている物質。"
        "PFOA・DEHP・MBT等、住友ゴム関連で **既に規制が決まっている物質** を即座に把握できる。"
    )
    reach_p = latest_parquet(DATA / "echa", "reach_regulation")
    if reach_p and reach_p.exists():
        with st.expander("🇪🇺 ECHA Annex XVII / XIV 規制リスト", expanded=False):
            import pandas as pd
            r_df = pd.read_parquet(reach_p)
            st.markdown(
                f"**出典**: [ECHA Restricted substances]({r_df['source_url'].iloc[0]})  "
                f"  ·  **件数**: {len(r_df)}  ·  **タイプ**: {r_df['list_type'].nunique()}"
            )
            st.markdown(
                "**カラム定義**: cas / name / list_type (Restriction/Authorization/Watch/Proposal) / "
                "annex (Annex XVII or XIV) / entry_date / restriction_summary / sumitomo_relevance"
            )
            st.dataframe(r_df, use_container_width=True, height=420)

elif axis == "axis6":
    st.subheader("💥 軸6 過去の供給途絶イベント")
    st.caption(
        "SEC 8-K / EDINET 臨時報告書 / DART 主要事項報告 / TDnet 開示 / TWSE 重大情報 / NITE 化学事故 を横断、LLM分類で供給関連イベントのみ抽出。"
    )
    source_inspector.render_source(
        "sec_8k", latest_parquet(DATA / "sec", "filings_8k"), expanded=False,
    )
    source_inspector.render_source(
        "sec_item801", latest_parquet(DATA / "sec", "item801_classified"), expanded=False,
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

    st.markdown("---")
    st.markdown("### 🆕 v3新規: SEC 10-K Risk Factor (構造リスク)")
    st.markdown(
        "**8-K 臨時開示** に加えて **10-K 年次報告書の Risk Factor 章** から、各社が構造的に開示する"
        "サプライ・地政学・規制リスクを取得。長期トレンドの捕捉に有効。"
    )
    risk10k_p = latest_parquet(DATA / "sec", "risk_factors_10k")
    if risk10k_p and risk10k_p.exists():
        with st.expander("📜 SEC 10-K Risk Factor テーマ", expanded=False):
            import pandas as pd
            rf_df = pd.read_parquet(risk10k_p)
            st.markdown(
                f"**出典**: SEC EDGAR 10-K Item 1A  ·  **企業**: {rf_df['ticker'].nunique()}  ·  **テーマ**: {len(rf_df)}"
            )
            st.dataframe(rf_df, use_container_width=True, height=400)
    fil10k_p = latest_parquet(DATA / "sec", "filings_10k")
    if fil10k_p and fil10k_p.exists():
        with st.expander("📜 SEC 10-K Filings リスト", expanded=False):
            st.dataframe(pd.read_parquet(fil10k_p), use_container_width=True, height=300)

elif axis == "axis7":
    st.subheader("💹 軸7 価格変動性")
    st.caption(
        "World Bank Pink Sheet 15品目月次 + **IMF Primary Commodity Prices (v3新規、RSS3/ウラン等)** + **LME 金属価格 (v3新規、Cu/Zn/Ni/Al/Li/W)**。"
    )
    source_inspector.render_source(
        "wb_prices", latest_parquet(DATA / "worldbank", "prices_monthly"),
        expanded=False,
    )

    st.markdown("---")
    st.markdown("### 🆕 v3新規: IMF Primary Commodity Prices")
    st.markdown(
        "**WB Pink Sheet と相補的**: ゴムRSS3、リン酸塩、ウラン、コットン等。"
        "RSS3 (Singapore) は住友ゴムの主要 NR グレードのスポット価格指標。"
    )
    imf_p = latest_parquet(DATA / "imf", "commodity_prices")
    if imf_p and imf_p.exists():
        with st.expander("🌐 IMF 商品価格 月次", expanded=False):
            import pandas as pd
            imf_df = pd.read_parquet(imf_p)
            st.markdown(
                f"**出典**: [IMF Primary Commodity Prices]({imf_df['source_url'].iloc[0]})  "
                f"  ·  **商品数**: {imf_df['commodity_code'].nunique()}"
            )
            st.markdown(
                "**カラム定義**: commodity_code (IMFコード) / name / year / month / date / "
                "value / unit / description / source"
            )
            st.dataframe(imf_df.sort_values(["commodity_code", "date"]), use_container_width=True, height=400)
    imf_sum_p = latest_parquet(DATA / "imf", "commodity_summary")
    if imf_sum_p and imf_sum_p.exists():
        with st.expander("🌐 IMF 商品別 2024年ボラ", expanded=False):
            st.dataframe(pd.read_parquet(imf_sum_p).sort_values("volatility_pct", ascending=False),
                         use_container_width=True)

    st.markdown("---")
    st.markdown("### 🆕 v3新規: LME 金属価格 (FRED経由 + Asian Metal curated)")
    st.markdown(
        "**金属系の価格ボラ**: Cu (スチールコード真鍮) / Zn (ZnO原料) / Al / Ni / "
        "**Tungsten APT** / **Lithium Carbonate** (Li-S電池) 等の月次価格。"
    )
    lme_p = latest_parquet(DATA / "lme", "metal_prices")
    if lme_p and lme_p.exists():
        with st.expander("🏗 LME / FRED 金属価格 月次", expanded=False):
            import pandas as pd
            lme_df = pd.read_parquet(lme_p)
            st.markdown(
                f"**出典**: [FRED St. Louis Fed](https://fred.stlouisfed.org/) + Asian Metal/USGS curated  "
                f"  ·  **シリーズ**: {lme_df['series_id'].nunique()}  ·  **観測**: {len(lme_df)}"
            )
            st.markdown(
                "**カラム定義**: series_id / name / unit / date / value / source / source_url"
            )
            st.dataframe(lme_df.sort_values(["series_id", "date"]), use_container_width=True, height=400)
    lme_sum_p = latest_parquet(DATA / "lme", "metal_prices_summary")
    if lme_sum_p and lme_sum_p.exists():
        with st.expander("🏗 金属別 ボラ年率化", expanded=False):
            st.dataframe(pd.read_parquet(lme_sum_p), use_container_width=True)

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
