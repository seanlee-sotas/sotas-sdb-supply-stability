"""TWSE 重大訊息のルールベース分類 (Gemini quota 枯渇時の fallback).

中文 subject から event_type と supply_relevance をキーワードマッチで判定。
LLM 分類と同じスキーマで data/axis6_classified/twse_material_info_classified_*.parquet を出力。
明日 LLM RPD リセット後に disruption_classify.py で上書き再分類可能。
"""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_DIR = ROOT / "data" / "twse"
OUT_DIR = ROOT / "data" / "axis6_classified"

# 中文キーワード → (event_type, supply_relevance) の単純マッピング。
# 上から順に評価、最初にヒットしたものを採用。
# Order matters: earlier rules win. Place high-precision LOW patterns (revenue
# announcements, financials) BEFORE broader MED matchers (合併 ≠ M&A when in
# 自結合併營收公告 / 合併財務報表 etc).
RULES = [
    # Pre-filter: 自結 / 財報 / 合併財務報表 → GUIDANCE LOW
    # These contain "合併" but refer to consolidated financials, not M&A activity.
    (["自結", "財務報表", "合併財務報表", "自結合併營收", "自結營收", "營收公告", "營收"], "GUIDANCE", "LOW"),
    (["每月營業額", "月營收", "獲利", "業績預估", "EPS", "毛利率"], "GUIDANCE", "LOW"),
    # 物理的供給途絶 (HIGH)
    (["火災", "火警", "爆炸", "工安事故", "工安"], "PLANT_INCIDENT", "HIGH"),
    (["停產", "停工", "歲修", "復工", "暫停生產", "停止生產"], "PRODUCTION_HALT", "HIGH"),
    (["天災", "颱風", "地震", "水災", "災害"], "FACILITY_DAMAGE", "HIGH"),
    (["回收", "召回"], "RECALL", "HIGH"),
    # 戦略 (MED) — 合併 stays here for actual M&A announcements
    (["公開收購", "股權交易", "併購", "收購"], "M_AND_A", "MED"),
    (["合併決議", "合併基準日", "合併消滅"], "M_AND_A", "MED"),
    (["處分子公司", "出售", "出讓", "讓渡", "讓售"], "STRATEGIC_DIVEST", "MED"),
    (["訴訟", "判決", "和解", "仲裁"], "LITIGATION", "MED"),
    (["主管機關", "裁罰", "違規", "限令", "監理"], "REGULATORY", "MED"),
    (["停止交易", "暫停交易", "終止上市"], "REGULATORY", "MED"),
    # 財務・人事 (LOW)
    (["現金股利", "股利", "股息", "減資", "增資", "私募", "可轉換公司債", "公司債", "庫藏股"], "FINANCING", "LOW"),
    (["董事會", "股東會", "董事", "監察人", "經理人", "代理人", "解任", "改選", "重大資訊"], "GOVERNANCE", "LOW"),
]


def classify(subject: str) -> tuple[str, str]:
    """First-match-wins. Returns (event_type, supply_relevance)."""
    s = subject or ""
    for keywords, event_type, sup in RULES:
        if any(k in s for k in keywords):
            return event_type, sup
    return "OTHER", "LOW"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(IN_DIR.glob("twse_material_info_*.parquet"))
    if not files:
        print("No TWSE parquet to classify")
        return
    in_path = files[-1]
    df = pd.read_parquet(in_path)
    print(f"Classifying {len(df)} TWSE rows from {in_path.name}")

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for _, r in df.iterrows():
        event_type, sup = classify(r["subject"])
        rows.append({
            "source_id": str(r["subject"])[:80],
            "source": "twse_material_info",
            "event_type": event_type,
            "summary_ja": f"[{r['company_name']}] {str(r['subject'])[:80]} (ルールベース分類)",
            "supply_relevance": sup,
            "key_facility": "",
            "key_product": "",
            "_classified_at": now,
        })

    out_df = pd.DataFrame(rows)
    stamp = datetime.now().strftime("%Y%m%d")
    out_path = OUT_DIR / f"twse_material_info_classified_{stamp}.parquet"
    out_df.to_parquet(out_path, index=False)
    print(f"Wrote {len(out_df)} → {out_path}")
    print("\nsupply_relevance:")
    print(out_df["supply_relevance"].value_counts().to_string())
    print("\nevent_type:")
    print(out_df["event_type"].value_counts().to_string())
    hm = out_df[out_df["supply_relevance"].isin(["HIGH", "MED"])]
    if len(hm):
        print(f"\nHIGH/MED サンプル ({len(hm)}件):")
        for _, r in hm.head(10).iterrows():
            print(f"  [{r['supply_relevance']}|{r['event_type']}] {r['summary_ja'][:100]}")


if __name__ == "__main__":
    main()
