"""ECHA REACH Restriction (Annex XVII) + Authorization List — 規制段階が進んだ物質.

SVHC (候補) の一段上、「使用制限決定済み (Restriction)」「認可必要 (Authorization)」の物質。
住友ゴム関連物質に PFAS / DEHP / 6PPD-quinone 等が引っかかる可能性を先取り。

Source:
  Restriction (Annex XVII): https://echa.europa.eu/substances-restricted-under-reach
  Authorization (Annex XIV): https://echa.europa.eu/authorisation-list

出力: data/echa/reach_regulation_YYYYMMDD.parquet
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "echa"


# ECHA REACH Annex XVII Restriction / Annex XIV Authorization 物質 (主要、住友ゴム関連)
# 出典: ECHA 公式リスト (2024年版)
RESTRICTION_DATA = [
    # ===== PFAS関連 (Annex XVII 68項) =====
    {"cas": "335-67-1", "name": "Perfluorooctanoic acid (PFOA)",
     "list_type": "Restriction", "annex": "Annex XVII, Entry 68",
     "entry_date": "2020-07-04", "restriction_summary": "輸入・製造禁止 (50ppb以下例外あり)",
     "sumitomo_relevance": "PFAS規制の象徴的物質。住友ゴム関連 PTFE / ETFE フィルム代替検討対象"},
    {"cas": "1763-23-1", "name": "Perfluorooctane sulfonic acid (PFOS)",
     "list_type": "Restriction", "annex": "POPs Reg., Annex I",
     "entry_date": "2010-08-27", "restriction_summary": "Stockholm POPs 経由で EU 全廃",
     "sumitomo_relevance": "PFAS シリーズ前駆体"},
    {"cas": None, "name": "All PFAS (Universal PFAS Restriction proposal)",
     "list_type": "Proposal", "annex": "Annex XVII, Proposed",
     "entry_date": "2023-02-07", "restriction_summary": "ECHA 5カ国共同提案: 10,000以上のPFAS全廃案",
     "sumitomo_relevance": "メディカルラバー PTFE 被覆フィルム、シリコーン剥離剤 全面影響"},
    # ===== 6PPD-quinone (Restriction 議論段階) =====
    {"cas": "793-24-8", "name": "6PPD (rubber antioxidant)",
     "list_type": "Watch", "annex": "Not yet listed",
     "entry_date": None, "restriction_summary": "ECHA 監視リスト入り (2024)、Restriction 提案準備中",
     "sumitomo_relevance": "★ タイヤ全社で使用、代替探索フェーズ"},
    # ===== フタル酸エステル =====
    {"cas": "117-81-7", "name": "Bis(2-ethylhexyl) phthalate (DEHP)",
     "list_type": "Authorization", "annex": "Annex XIV",
     "entry_date": "2015-02-21", "restriction_summary": "認可必要 (sunset date)",
     "sumitomo_relevance": "可塑剤、住友ゴム配合系で代替済み多い"},
    {"cas": "84-74-2", "name": "Dibutyl phthalate (DBP)",
     "list_type": "Authorization", "annex": "Annex XIV",
     "entry_date": "2015-02-21", "restriction_summary": "認可必要",
     "sumitomo_relevance": "ゴム可塑剤、低リスク (Sumitomo は不使用想定)"},
    # ===== タングステン化合物関連は規制無し =====
    # ===== 鉛・カドミウム =====
    {"cas": "7439-92-1", "name": "Lead (Pb)",
     "list_type": "Restriction", "annex": "Annex XVII, Entry 63",
     "entry_date": "2018-04-12", "restriction_summary": "おもちゃ・宝飾品 0.05% wt 制限",
     "sumitomo_relevance": "ゴルフボール一部歴史的に使用、現在は不使用"},
    # ===== ベンゾチアゾール系 =====
    {"cas": "149-30-4", "name": "2-Mercaptobenzothiazole (MBT)",
     "list_type": "Watch", "annex": "ECHA Substance Evaluation",
     "entry_date": "2021-03-15", "restriction_summary": "発がん性懸念、評価中",
     "sumitomo_relevance": "加硫促進剤 MBT 由来、CBS/TBBSも前駆体共通"},
    # ===== カーボンブラック =====
    {"cas": "1333-86-4", "name": "Carbon Black",
     "list_type": "Watch", "annex": "ECHA Substance Evaluation (suspected carcinogen)",
     "entry_date": "2010-01-01", "restriction_summary": "IARC Group 2B 発がん性ありの可能性、職業曝露監視",
     "sumitomo_relevance": "★ タイヤ重量20-30%、規制リスク低だが監視継続"},
    # ===== 短鎖塩素化パラフィン (SCCPs) — 関係薄 =====
    # ===== Bisphenol A =====
    {"cas": "80-05-7", "name": "Bisphenol A (BPA)",
     "list_type": "SVHC + Restriction", "annex": "Annex XVII, Entry 66/74",
     "entry_date": "2017-12-12", "restriction_summary": "感熱紙・玩具に制限、SVHC候補",
     "sumitomo_relevance": "ゴルフボールエポキシ系・接着剤に存在可能、要チェック"},
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    df = pd.DataFrame(RESTRICTION_DATA)
    df["source"] = "ECHA Annex XVII / XIV (curated)"
    df["source_url"] = "https://echa.europa.eu/substances-restricted-under-reach"
    df["_fetched_at"] = ts

    out = OUT_DIR / f"reach_regulation_{datetime.now().strftime('%Y%m%d')}.parquet"
    df.to_parquet(out, index=False)
    print(f"saved: {out} ({len(df)} entries, list_types: {df['list_type'].value_counts().to_dict()})")


if __name__ == "__main__":
    main()
