"""Reusable raw-source inspector for each axis page.

Renders an expander with: parquet metadata, source URL, column dictionary,
filterable preview, and a CSV download button.

Column definitions live in COLUMN_DEFS keyed by `dataset_id`. Add new datasets
by extending COLUMN_DEFS + calling render_source(dataset_id, parquet_path) from
the axis page.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import streamlit as st

# Per-dataset metadata: title, source URL, license, refresh cadence, column dict.
# `columns` maps column_name → human-readable Japanese description.
DATASETS: dict[str, dict] = {
    "comtrade_trade": {
        "title": "UN Comtrade — 年次貿易統計",
        "source_url": "https://comtradeplus.un.org/",
        "license": "UN Comtrade Open Data",
        "cadence": "年次（HS6粒度・指定HSコードのみ）",
        "ingest_script": "ingest/comtrade.py",
        "axes": ["軸2 需給バランス", "軸4 地政学・原産地"],
        "columns": {
            "typeCode": "C=Commodities(物品)固定",
            "freqCode": "A=年次, M=月次",
            "refPeriodId": "参照期間ID (YYYYMM)",
            "refYear": "参照年",
            "refMonth": "参照月 (年次は52固定)",
            "period": "期間ラベル",
            "reporterCode": "報告国コード (M49)",
            "reporterISO": "報告国 ISO-3",
            "reporterDesc": "報告国名",
            "flowCode": "M=輸入, X=輸出, RX/RM=再輸出/再輸入",
            "flowDesc": "フロー記述",
            "partnerCode": "相手国コード (M49)",
            "partnerISO": "相手国 ISO-3",
            "partnerDesc": "相手国名",
            "partner2Code": "第2相手国 (中継貿易用)",
            "partner2ISO": "第2相手国 ISO-3",
            "partner2Desc": "第2相手国名",
            "classificationCode": "HS22 / H6 等の分類体系",
            "classificationSearchCode": "検索用分類コード",
            "isOriginalClassification": "元分類で報告されたか",
            "cmdCode": "HS6コード (例 290121)",
            "cmdDesc": "HS6名称",
            "aggrLevel": "集計レベル (6=HS6)",
            "isLeaf": "末端分類か",
            "customsCode": "税関手続コード",
            "customsDesc": "税関手続記述",
            "mosCode": "輸送モード",
            "motCode": "輸送手段コード",
            "motDesc": "輸送手段記述",
            "qtyUnitCode": "数量単位コード",
            "qtyUnitAbbr": "数量単位略称 (kg, l 等)",
            "qty": "数量",
            "isQtyEstimated": "数量推計フラグ",
            "altQtyUnitCode": "代替単位コード",
            "altQtyUnitAbbr": "代替単位略称",
            "altQty": "代替単位数量",
            "isAltQtyEstimated": "代替数量推計フラグ",
            "netWgt": "正味重量 (kg)",
            "isNetWgtEstimated": "正味重量推計フラグ",
            "grossWgt": "総重量 (kg)",
            "isGrossWgtEstimated": "総重量推計フラグ",
            "cifvalue": "CIF金額 USD (輸入)",
            "fobvalue": "FOB金額 USD (輸出)",
            "primaryValue": "主要金額 USD (輸出はFOB, 輸入はCIF)",
            "legacyEstimationFlag": "旧推計フラグ",
            "isReported": "実報告データか",
            "isAggregate": "集計値か",
            "_fetched_at": "取得日時 (UTC)",
        },
    },
    "wb_prices": {
        "title": "World Bank Pink Sheet — 商品月次価格",
        "source_url": "https://www.worldbank.org/en/research/commodity-markets",
        "license": "World Bank Open Data (CC BY 4.0)",
        "cadence": "月次（前月末日締め）",
        "ingest_script": "ingest/worldbank.py",
        "axes": ["軸7 価格変動性"],
        "columns": {
            "period": "期間ラベル (YYYY-MM)",
            "date": "月末日付",
            "commodity": "商品コード (CRUDE_BRENT, NGAS_EUR 等)",
            "price": "価格 (単位は unit 列参照)",
            "unit": "通貨・物理単位 (USD/bbl, USD/mt 等)",
            "name": "商品名 (英語)",
            "_fetched_at": "取得日時 (UTC)",
        },
    },
    "echa_svhc": {
        "title": "ECHA SVHC — REACH高懸念物質候補リスト",
        "source_url": "https://echa.europa.eu/candidate-list-table",
        "license": "ECHA (公的データ、再利用可)",
        "cadence": "年2回（6月・12月）追加",
        "ingest_script": "ingest/echa.py",
        "axes": ["軸5 政策・規制リスク"],
        "columns": {
            "substance_name": "物質名 (英語)",
            "ec_number": "EC番号 (EC Inventory)",
            "cas_number": "CAS番号",
            "date_of_inclusion": "SVHC追加日",
            "reason": "SVHC指定理由 (発がん性, PBT, 内分泌攪乱 等)",
            "decision_id": "ECHA決定ID",
            "_fetched_at": "取得日時 (UTC)",
            "_source": "取得元 (ECHA公式CSV)",
        },
    },
    "sec_8k": {
        "title": "SEC EDGAR — 8-K 臨時開示",
        "source_url": "https://www.sec.gov/edgar/searchedgar/companysearch",
        "license": "SEC Public Domain",
        "cadence": "日次（米化学メジャー15社）",
        "ingest_script": "ingest/sec_8k.py",
        "axes": ["軸6 過去の供給途絶"],
        "columns": {
            "ticker": "ティッカー (DOW, LYB, 等)",
            "cik": "SEC CIK番号 (10桁0埋め)",
            "company_name": "企業名",
            "form": "様式 (8-K)",
            "filing_date": "提出日 (YYYY-MM-DD)",
            "accession": "Accession番号",
            "items": "Item番号カンマ区切り (1.01, 2.05, 8.01 等)",
            "primary_doc": "主要文書ファイル名",
            "primary_desc": "主要文書記述",
            "_fetched_at": "取得日時 (UTC)",
            "accession_url": "EDGAR詳細ページURL",
        },
    },
    "sec_item801": {
        "title": "SEC 8-K Item 8.01 — LLM分類済イベント",
        "source_url": "https://www.sec.gov/edgar/searchedgar/companysearch",
        "license": "SEC Public Domain + LLM分類",
        "cadence": "8-K取得時に Item 8.01 を直近30件分類",
        "ingest_script": "ingest/sec_8k_classify.py",
        "axes": ["軸6 過去の供給途絶"],
        "columns": {
            "filing_date": "提出日",
            "ticker": "ティッカー",
            "company_name": "企業名",
            "items": "Item番号",
            "primary_desc": "原文タイトル (英語)",
            "accession_url": "EDGAR詳細URL",
            "accession": "Accession番号",
            "event_type": "LLM分類イベント種別",
            "summary_ja": "LLM要約 (日本語)",
            "supply_relevance": "供給関連度 (high/medium/low)",
            "key_facility": "言及施設名",
            "key_product": "言及製品名",
            "_classified_at": "分類実行日時 (UTC)",
        },
    },
    "edinet_snippets": {
        "title": "EDINET — 有価証券報告書 生産能力 snippet",
        "source_url": "https://disclosure2.edinet-fsa.go.jp/",
        "license": "金融庁 EDINET (再利用可)",
        "cadence": "四半期 (有報・四半期報告書)",
        "ingest_script": "ingest/edinet.py",
        "axes": ["軸1 生産能力・新増設"],
        "columns": {
            "company": "提出会社名 (報告書ヘッダから抽出)",
            "doctype": "書類種別 (有価証券報告書, 四半期報告書 等)",
            "period": "対象期 (YYYY-MM)",
            "file_path": "原本 XBRL/PDF パス",
            "snippet": "生産能力・新増設キーワード周辺テキスト (前後200字)",
            "_fetched_at": "取得日時 (UTC)",
        },
    },
    "edinet_structured": {
        "title": "EDINET — LLM構造化済生産能力データ",
        "source_url": "https://disclosure2.edinet-fsa.go.jp/",
        "license": "金融庁 EDINET + LLM抽出",
        "cadence": "snippet ingest 後にバッチ構造化",
        "ingest_script": "ingest/edinet_structure.py",
        "axes": ["軸1 生産能力・新増設"],
        "columns": {
            "company": "提出会社名",
            "doctype": "書類種別",
            "period": "対象期",
            "file_path": "原本パス",
            "snippet_id": "対応 snippet 行ID",
            "product": "LLM抽出: 製品名",
            "facility": "LLM抽出: 設備・拠点名",
            "capacity_value": "LLM抽出: 能力数値",
            "capacity_unit": "LLM抽出: 単位 (t/年, kt/年 等)",
            "direction": "LLM分類: 新設/増強/縮小/閉鎖",
            "target_year": "LLM抽出: 完了予定年",
            "confidence": "LLM分類信頼度 (high/medium/low)",
            "_processed_at": "LLM処理日時 (UTC)",
        },
    },
    "jp_supplier": {
        "title": "国内サプライヤー集計 (proxy)",
        "source_url": "ingest/jp_supplier.py 内ロジック (EDINET snippet + 手動マッピング)",
        "license": "派生指標 (内部加工)",
        "cadence": "EDINET ingest 後に再計算",
        "ingest_script": "ingest/jp_supplier.py",
        "axes": ["軸3 サプライヤー集中度"],
        "columns": {
            "material_id": "素材ID (materials.yml キー)",
            "name_ja": "素材名 (日本語)",
            "name_en": "素材名 (英語)",
            "category": "素材カテゴリ",
            "jp_supplier_count": "言及された国内サプライヤー社数",
            "snippet_total": "ヒット snippet 総数",
            "concentration_band": "集中度バンド (low/medium/high)",
            "top_companies": "言及上位企業 (カンマ区切り)",
            "_fetched_at": "集計日時 (UTC)",
        },
    },
    "pops": {
        "title": "Stockholm Convention POPs — 残留性有機汚染物質",
        "source_url": "https://www.pops.int/TheConvention/ThePOPs/ListingofPOPs/tabid/2509/Default.aspx",
        "license": "UNEP 公的データ",
        "cadence": "条約改正時のみ (年1回未満)",
        "ingest_script": "ingest/regulations.py",
        "axes": ["軸5 政策・規制リスク"],
        "columns": {
            "id": "POPs内部ID",
            "name_en": "物質名 (英語)",
            "annex": "Annex区分 (A=禁止, B=制限, C=非意図的)",
            "cas": "CAS番号",
            "type": "種別 (pesticide/industrial/byproduct)",
            "_source": "取得元",
            "_source_url": "原典URL",
            "_fetched_at": "取得日時 (UTC)",
        },
    },
    "meti_critical": {
        "title": "METI 特定重要物資",
        "source_url": "https://www.meti.go.jp/policy/economy/economic_security/",
        "license": "経済産業省 (公的データ)",
        "cadence": "閣議決定時 (年1-2回程度)",
        "ingest_script": "ingest/regulations.py",
        "axes": ["軸5 政策・規制リスク"],
        "columns": {
            "id": "METI内部ID",
            "name_ja": "物資名 (日本語)",
            "name_en": "物資名 (英語)",
            "designated_date": "指定日",
            "category": "区分 (素材/医薬/エネルギー 等)",
            "_source": "取得元",
            "_source_url": "原典URL",
            "_fetched_at": "取得日時 (UTC)",
        },
    },
    "chemicals_master": {
        "title": "化学品マスタ (PubChem 駆動)",
        "source_url": "https://pubchem.ncbi.nlm.nih.gov/",
        "license": "PubChem (パブリックドメイン)",
        "cadence": "シード追加時に手動再 ingest",
        "ingest_script": "ingest/chemicals/pubchem.py + pubchem_retry.py",
        "axes": ["全軸の CAS 解決基盤"],
        "columns": {
            "cas": "CAS Registry番号 (主キー)",
            "pubchem_cid": "PubChem Compound ID",
            "name_en": "PubChem 推奨英名",
            "iupac_name": "IUPAC名",
            "molecular_formula": "分子式",
            "molecular_weight": "分子量 (g/mol)",
            "inchikey": "InChIKey",
            "smiles": "SMILES (ConnectivitySMILES)",
            "synonyms_count": "同義語数",
            "top_synonym": "上位同義語",
            "category_seed": "シード時のカテゴリ",
            "category_norm": "正規化カテゴリ (materials_scope.yml と対応)",
            "source_tags": "シード元タグ (materials_yml/edinet/...)",
            "pubchem_fetch_status": "取得結果 (full/substance/none)",
        },
    },
    "chemicals_hs_map": {
        "title": "化学品 → HS6 マッピング",
        "source_url": "materials_scope.yml + Gemini 2.5 Flash-Lite 推論",
        "license": "派生 (LLM 補完)",
        "cadence": "化学品マスタ更新時に再生成",
        "ingest_script": "ingest/chemicals/hs_map_llm.py",
        "axes": ["軸2 需給バランス", "軸4 地政学", "軸7 価格変動性"],
        "columns": {
            "cas": "CAS Registry番号",
            "hs6": "HS6コード",
            "hs_chapter": "HS Chapter (2桁)",
            "hs_label": "Chapter名 (日本語)",
            "confidence": "信頼度 (0-1)",
            "source": "出典 (materials_yml/llm_gemini/category_default)",
            "rationale": "LLM 判定根拠 (該当時)",
            "created_at": "作成日時 (UTC)",
        },
    },
}


@st.cache_data(show_spinner=False)
def _file_meta(path_str: str, mtime: float) -> tuple[str, int, str]:
    """Return (size_human, row_count, mtime_iso). Cached on (path, mtime)."""
    path = Path(path_str)
    size = path.stat().st_size
    if size < 1024:
        size_h = f"{size} B"
    elif size < 1024 ** 2:
        size_h = f"{size / 1024:.1f} KB"
    else:
        size_h = f"{size / 1024**2:.1f} MB"
    con = duckdb.connect()
    rows = con.execute(f"SELECT COUNT(*) FROM '{path}'").fetchone()[0]
    mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    return size_h, rows, mtime_str


@st.cache_data(show_spinner=False)
def _preview_df(path_str: str, mtime: float, limit: int):
    """Cached preview head. mtime is the cache key, not used in logic."""
    con = duckdb.connect()
    return con.execute(f"SELECT * FROM '{path_str}' LIMIT {limit}").df()


@st.cache_data(show_spinner=False)
def _sample_csv_bytes(path_str: str, mtime: float, cap: int) -> bytes:
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM '{path_str}' LIMIT {cap}").df()
    return df.to_csv(index=False).encode("utf-8-sig")


def render_source(
    dataset_id: str,
    parquet_path: Path | None,
    *,
    preview_limit: int = 50,
    expanded: bool = False,
) -> None:
    """Render a self-contained raw-source inspection expander.

    Safe to call multiple times per page — each call uses dataset_id as part of
    the widget key namespace.
    """
    meta = DATASETS.get(dataset_id)
    if meta is None:
        st.warning(f"未登録の dataset_id: `{dataset_id}` — source_inspector.DATASETS に追加してください。")
        return

    if parquet_path is None or not Path(parquet_path).exists():
        with st.expander(f"📂 ソース生データ — {meta['title']}", expanded=False):
            st.info("対応 parquet がまだ生成されていません。")
            _render_column_dict(meta)
        return

    parquet_path = Path(parquet_path)
    path_str = str(parquet_path)
    try:
        mtime = parquet_path.stat().st_mtime
    except OSError:
        mtime = 0.0

    with st.expander(f"📂 ソース生データ — {meta['title']}", expanded=expanded):
        # --- source attribution (cheap markdown only) ---
        st.markdown(
            f"**出典:** [{meta['source_url']}]({meta['source_url']})  \n"
            f"**ライセンス:** {meta['license']}  \n"
            f"**更新頻度:** {meta['cadence']}  \n"
            f"**Ingestスクリプト:** `{meta['ingest_script']}`  \n"
            f"**利用軸:** {', '.join(meta['axes'])}"
        )

        # --- gated heavy work: column dict + file meta + preview + CSV ---
        # Streamlit renders expander contents eagerly, so multiple dataframes
        # in render_cross() / axis tabs slow first paint. Gate behind button.
        load_key = f"load_{dataset_id}_{parquet_path.name}"
        if not st.session_state.get(load_key + "_loaded"):
            if st.button(
                "📋 カラム定義 + プレビューを表示",
                key=load_key,
                help="クリックでカラム定義表・先頭50行・CSVダウンロードを読み込みます",
            ):
                st.session_state[load_key + "_loaded"] = True
                st.rerun()
            return

        # --- column dictionary (only after click) ---
        _render_column_dict(meta)

        try:
            size_h, rows, mtime_str = _file_meta(path_str, mtime)
            try:
                rel = parquet_path.relative_to(parquet_path.parents[2])
            except (ValueError, IndexError):
                rel = parquet_path.name
            st.caption(f"`{rel}` · {rows:,} rows · {size_h} · 更新 {mtime_str}")
        except Exception as e:
            st.caption(f"`{parquet_path.name}` (メタ取得失敗: {e})")

        st.markdown(f"**プレビュー (先頭 {preview_limit} 行)**")
        try:
            preview_df = _preview_df(path_str, mtime, preview_limit)
            st.dataframe(preview_df, use_container_width=True, height=320)
        except Exception as e:
            st.error(f"プレビュー失敗: {e}")
            return

        sample_cap = 5000
        try:
            csv_bytes = _sample_csv_bytes(path_str, mtime, sample_cap)
            st.download_button(
                label=f"⬇️ CSV ダウンロード (最大 {sample_cap:,} 行)",
                data=csv_bytes,
                file_name=f"{parquet_path.stem}_sample.csv",
                mime="text/csv",
                key=f"dl_{dataset_id}_{parquet_path.name}",
            )
        except Exception as e:
            st.warning(f"CSV書き出し失敗: {e}")


def _render_column_dict(meta: dict) -> None:
    import pandas as pd
    cols = meta.get("columns") or {}
    if not cols:
        return
    df = pd.DataFrame(
        [{"カラム": k, "説明": v} for k, v in cols.items()],
    )
    st.markdown("**カラム定義**")
    st.dataframe(df, use_container_width=True, height=min(35 * (len(df) + 1) + 10, 320), hide_index=True)
