"""出典・methodology — 物質抽出手法・3層信頼度・公開資料一覧・軸スコアロジック."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sumitomo_loader as sl  # noqa: E402

st.set_page_config(
    page_title="出典・methodology | SDB Mock",
    page_icon="📚",
    layout="wide",
)

meta = sl.load_metadata()
layers = sl.load_layers()
segments = sl.load_segments()
materials = sl.load_materials()
citations = sl.load_citations()

st.title("📚 出典 & Methodology")

st.markdown(
    """
このMockがどの公開資料から何を抽出し、どう評価しているかを **透明に説明** するページです。
社内discussionで「この物質、本当に住友ゴムが使ってるの？」「軸5のスコアの根拠は？」と聞かれた時に、
ここを見せれば全て答えられる状態を目指しています。
"""
)

st.divider()

# -----------------------------------------------------------------------------
# 1. 公開資料一覧
# -----------------------------------------------------------------------------

st.subheader("1. 物質抽出に使った公開資料")

st.markdown(f"""
**対象企業**: {meta['source_company']} (EDINET コード: `{meta['edinet_code']}` / 証券コード: `{meta['ticker']}`)
**会計期間**: {meta['fiscal_year']}

| 資料 | ファイル | 主に拾った内容 |
|---|---|---|
| 有価証券報告書 | `{meta['source_files'][0]}` | 3事業セグメント / 関連会社（NRシンガポール拠点・住友電工スチールコード）/ 業績の概要（原材料リスク）/ 研究開発活動（アクティブトレッド・センシングコア・TOWANOWA・Viaduct）/ 設備投資計画 |
| 統合報告書 | `{meta['source_files'][1]}` | R.I.S.E. 2035 / 中期計画 / マテリアリティ（EUDR・サステナブル原材料）/ イノベーション系譜 / 制振ダンパー・医療ゴム・防舷材詳細 / 新規事業候補（リチウム硫黄・がん検査・3Dプリンタ） |

これらは Vault 側で OCR + 構造化済み。原本へのリンクは [[1. Anchors/_industry_research/_chemicals/jp/住友ゴム工業/]] にあります。
""")

st.divider()

# -----------------------------------------------------------------------------
# 2. 3層信頼度
# -----------------------------------------------------------------------------

st.subheader("2. 3層信頼度（出典 layer）の定義")

st.markdown(
    "物質を Mock に登録した根拠の強さを 3段階で明示しています。MTGで「これは本当に住友ゴムが使っているのか？」と聞かれた時、layer A は引用テキストで即答できます。"
)

layer_stats = materials["evidence_layer"].value_counts().to_dict()

for lk in ["A", "B", "C"]:
    lv = layers[lk]
    cnt = layer_stats.get(lk, 0)
    with st.container(border=True):
        col1, col2 = st.columns([1, 4])
        with col1:
            st.markdown(
                f"<div style='background:{lv['color']};color:white;padding:1em;border-radius:0.5em;"
                f"text-align:center;font-weight:600;font-size:1.5em;'>Layer {lk}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(f"<div style='text-align:center;font-size:0.9em;color:#666;'>{cnt}物質</div>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"### {lv['label']}")
            st.markdown(lv["description"])
            if lk == "A":
                st.caption("例: 天然ゴム → 有報2025 行232「SUMITOMO RUBBER SINGAPORE PTE. LTD.／天然ゴムの仕入」")
            elif lk == "B":
                st.caption("例: 1,3-ブタジエン → 業界常識として SBR/BR の原料モノマー。社名明示は無し")
            elif lk == "C":
                st.caption("例: 6PPD代替老化防止剤 → 住友ゴム個別記載なし、米WA州を中心とした 6PPD-quinone 水質規制議論から推定")

st.divider()

# -----------------------------------------------------------------------------
# 3. 物質マスタの統計
# -----------------------------------------------------------------------------

st.subheader("3. 物質マスタ全体像")

col1, col2, col3, col4 = st.columns(4)
col1.metric("総物質数", len(materials))
col2.metric("⭐ pinned (いま使ってる)", (materials["status"] == "pinned").sum())
col3.metric("👀 watch (これから使いたい)", (materials["status"] == "watch").sum())
col4.metric("引用件数", len(citations))

st.markdown("**事業セグメント別**")
seg_breakdown = materials.groupby(["primary_segment", "status"]).size().unstack(fill_value=0)
seg_breakdown.index = [f"{segments[k]['icon']} {segments[k]['label']}" for k in seg_breakdown.index]
st.dataframe(seg_breakdown, use_container_width=True)

st.markdown("**CAS / HS6 / PubChem CID カバレッジ**")
col1, col2, col3, col4 = st.columns(4)
col1.metric("CAS確定", f"{materials['cas'].notna().sum()} / {len(materials)}")
col2.metric("HS6マッピング", f"{materials['hs6'].notna().sum()} / {len(materials)}")
col3.metric("PubChem CID", f"{materials['pubchem_cid'].notna().sum()} / {len(materials)}")
col4.metric("JP supplier データあり", f"{materials['has_jp_supplier_data'].sum()} / {len(materials)}")

st.caption(
    "CAS未確定物質（配合系・業界常識ベース）は CAS駆動の軸スコア（軸2/4/5/6/7）は算出できませんが、"
    "出典 layer + リスクタグでウォッチ対象として登録されています。"
)

st.divider()

# -----------------------------------------------------------------------------
# 4. 7軸スコアロジック
# -----------------------------------------------------------------------------

st.subheader("4. 7軸スコア算出ロジック")

st.markdown("""
各軸は **0-100 の正規化スコア** で、**高いほど安定 (リスク低)** を意味します。
軸2〜7は構造評価 (年単位)、軸1は短期要因 (直近90日) で構造評価を時系列補正する役割です。

| 軸 | 何を見ているか | 入力データ | スコアの読み方 |
|---|---|---|---|
| ⏱ **軸1 短期要因** | 直近90日に「現に何か起きているか」 | JPCAエチレン稼働率 + 原油Brent価格 + 化学業界ニュース密度 + 関連メーカー90日イベント + 物質名マッチ記事 | 平時=80〜100、業界全体ショック=50〜70、物質固有の重大事案=20〜40 |
| ⚖️ **軸2 需給バランス** | 国産で需要を賄えているか・輸入依存か | 国際貿易統計 (HS6粒度、日本の輸出と輸入) | 国内生産が需要を満たす=高スコア、輸入頼みだと海外ショックで揺れるので低スコア |
| 🤝 **軸3 国内集中度** | 国内で誰から買えるか・代替が利くか | 国内上場化学442社の有報・IR で物質名が出てくる企業数 | 取扱企業が多い=安心 (高スコア)、1〜2社のみ=代替確保が困難 (低スコア) |
| 🌐 **軸4 地政学リスク** | 世界供給がどの国に偏っているか | 国際貿易統計 (世界輸出シェア) を HHI 集中度指数化 | 原産国が分散=高スコア、特定国に寡占=輸出規制・地政学イベントで詰む可能性 (低スコア) |
| 📋 **軸5 規制リスク** | 製造・取扱を制約する公的規制があるか | EU の高懸念物質 (ECHA SVHC) / 国連 POPs 条約 / 経産省 特定重要物資 | 規制なし=高スコア、複数リスト該当=中長期で使用制限・代替検討の対象 (低スコア) |
| 💥 **軸6 供給途絶イベント** | 関連メーカーで実際に過去365日何が起きたか | SEC 8-K 米国 / EDINET 臨時報告書 日本 / DART 韓国 / TDnet 日本 / TWSE 台湾 / NITE 事故公表 を LLM 分類 | 火災・停止・FM等の発生なし=高スコア、HIGH事案多発=サプライ網不安定 (低スコア) |
| 💹 **軸7 価格変動性** | コスト読みの立てやすさ | World Bank Pink Sheet (原油/天然ガス/ゴム等15品目) の月次価格、年間ボラティリティ | 値動き安定=高スコア、月次15%超変動=見積り見直し頻発 (低スコア) |

#### 軸1 の合成式

軸1は他軸と違い、複数シグナルを合成します:

```
score = 100 - 50 × (0.6 × マクロ圧力 + 0.4 × 個別圧力)
```

- **マクロ圧力 (業界全体)** = JPCA エチレン稼働率の直近3M下振れ ／ Brent 3ヶ月変化率 ／ 業界ニュース密度 の平均
- **個別圧力 (物質固有)** = 軸6 直近90日の関連メーカーHIGH×2+MED×1 ／ 物質名マッチ記事件数 ／ 物質固有 WB 商品3M変化率 の平均

各シグナルは 0〜1 に正規化 (例: 稼働率 10pt 下振れで 1.0、ニュース密度 15件/日で 1.0)。

#### 総合スコア

業界別重みプロファイル (タイヤ/半導体/医薬中間体/汎用樹脂/default) を `materials_scope.yml` で定義し、
`composite()` で重み付け平均 → 総合スコア (0-100) + A〜F 評価。

#### 信頼度ガード
- 6軸以上スコア算出 → **high**
- 4-5軸 → **medium**
- 3軸以下 → **low** (総合スコアは suppress)
""")

st.divider()

# -----------------------------------------------------------------------------
# 5. Mock の限界
# -----------------------------------------------------------------------------

st.subheader("5. Mockの限界・残課題")

st.markdown("""
- **実調達リストは未反映**：サプライヤー名・購入金額は住友ゴム機密のため公開情報のみ。MTGでヒアリング内容を貰い次第追記可能な設計です。
- **CAS未確定の26物質**：ENR / DPNR / 加硫促進剤類 / 高減衰ゴム配合 等は配合系のため、PubChem CID が取れず軸スコアが limited です。出典 + リスクタグでウォッチ対象として表示。
- **アクティブトレッド第3スイッチ**：構造未公表のため、SDB上では「Watch」フラグのみ。CAS/構造は空欄。これが SDB の説明責任ラインです。
- **軸2/4の集計粒度**：HS6 単位のため、「スペシャリティケミカル」（HS6『その他』バスケットに埋もれる物質）は集計値が薄まります。ユーザー投稿で補完予定。
- **軸6 LLM分類精度**：LLM 分類で「HIGH supply-relevance」のみ抽出していますが、FP/FN は残ります。原文 [accession_url] へのリンクを必ず併記。
""")

st.divider()

# -----------------------------------------------------------------------------
# 6. 関連 Vault docs
# -----------------------------------------------------------------------------

st.subheader("6. 関連ドキュメント (Vault)")

st.markdown("""
- `Projects/202605_sdb-supply-stability/analysis_住友ゴム_物質絞り込み.md` — 事業×物質の絞り込み + ピン留めセット案
- `Projects/202605_sdb-supply-stability/analysis_住友ゴム_物質出典一覧.md` — 物質別の出典付き根拠（このMockのソース）
- `Projects/202605_sdb-supply-stability/analysis_sdb_integration_design.md` — SDB本体への組み込みUX設計（3案比較・業界別重み・データ連携アーキテクチャ）
- `Projects/202605_sdb-supply-stability/analysis_供給安定性ソース棚卸.md` — 7軸 × 公開ソースの全量棚卸
""")

st.caption(
    "本Mockは Sotas社内 discussion purpose 専用です。"
    " 本番SDBへの組み込みは別途設計書 (analysis_sdb_integration_design) 参照。"
)
