"""64物質 × 7軸のカバレッジ監査.

Output:
  data/sumitomo/coverage_audit.parquet — 物質×軸の評価可能/不可マトリクス
  stdout — 軸別カバレッジ要約 + 評価不能原因の分類

評価不能の階層 (上が根本原因):
  1. NO_CAS          — そもそも CAS 未確定 (配合系・業界常識ベース)
  2. NO_CHEMICALS    — CAS あるが chemicals.parquet 未登録 (PubChem retry 必要)
  3. AXIS_SPECIFIC   — chemicals 登録済みだが該当軸データ無し:
                        - 軸2/4 NO_HS6
                        - 軸3 NO_JP_SUPPLIER
                        - 軸7 NO_WB_COMMODITY
                        - 軸1 NO_EDINET_HIT
                        - 軸5 軸5 は規制リスト hit すれば「リスクあり」、未hit は「リスクなし」(=評価可能, score=high)
                        - 軸6 NO_EVENT_HIT 同様 (未hit は score=high)
"""

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))

import scoring  # noqa: E402
import chemicals_loader as cl  # noqa: E402
import sumitomo_loader as sl  # noqa: E402


AXES = [
    "axis1_capacity",
    "axis2_supply_demand",
    "axis3_jp_concentration",
    "axis4_global_hhi",
    "axis5_regulation",
    "axis6_events",
    "axis7_price",
]


def main():
    mats = pd.read_parquet(REPO / "data" / "sumitomo" / "materials.parquet")
    print(f"=== Sumitomo Coverage Audit: {len(mats)} materials × {len(AXES)} axes ===\n")

    rows = []
    for _, m in mats.iterrows():
        rec = {
            "id": m["id"],
            "name_ja": m["name_ja"],
            "cas": m["cas"],
            "primary_segment": m["primary_segment"],
            "status": m["status"],
            "evidence_layer": m["evidence_layer"],
            "in_chemicals_parquet": bool(m["pubchem_cid"] and not pd.isna(m["pubchem_cid"])),
            "has_hs6": bool(m["hs6"] and not pd.isna(m["hs6"])),
            "has_jp_supplier_data": bool(m["has_jp_supplier_data"]),
        }

        # Use pseudo CAS for substance-only entries (sumitomo_build emits it in `cas` column already)
        target_cas = m["cas"] if not pd.isna(m["cas"]) else None
        if not target_cas:
            rec["root_cause"] = "NO_CAS"
            for a in AXES:
                rec[f"{a}_score"] = None
                rec[f"{a}_status"] = "NO_CAS"
            rec["scored_count"] = 0
            rows.append(rec)
            continue

        sub = scoring.compute_all(target_cas)
        if not sub:
            rec["root_cause"] = "NO_CHEMICALS_ENTRY"
            for a in AXES:
                rec[f"{a}_score"] = None
                rec[f"{a}_status"] = "NO_CHEMICALS"
            rec["scored_count"] = 0
            rows.append(rec)
            continue

        rec["root_cause"] = "PARTIAL"
        scored = 0
        for a in AXES:
            s = sub.get(a, {})
            sc = s.get("score")
            rec[f"{a}_score"] = sc
            if sc is None:
                # detail/rationale から missing 原因を推定
                detail = (s.get("detail") or s.get("rationale") or s.get("reason") or "").lower()
                if "hs" in detail:
                    rec[f"{a}_status"] = "NO_HS6"
                elif "supplier" in detail or "company" in detail or "jp" in detail:
                    rec[f"{a}_status"] = "NO_JP_SUPPLIER"
                elif "wb" in detail or "world bank" in detail or "commodity" in detail or "price" in detail:
                    rec[f"{a}_status"] = "NO_WB_COMMODITY"
                elif "edinet" in detail or "capacity" in detail:
                    rec[f"{a}_status"] = "NO_EDINET_HIT"
                elif "event" in detail or "sec" in detail:
                    rec[f"{a}_status"] = "NO_EVENT_HIT"
                else:
                    rec[f"{a}_status"] = "MISSING_DATA"
            else:
                rec[f"{a}_status"] = "OK"
                scored += 1
        rec["scored_count"] = scored
        if scored == 0:
            rec["root_cause"] = "NO_CHEMICALS_DATA"
        elif scored >= 6:
            rec["root_cause"] = "HIGH_COVERAGE"
        elif scored >= 4:
            rec["root_cause"] = "MEDIUM_COVERAGE"
        else:
            rec["root_cause"] = "LOW_COVERAGE"
        rows.append(rec)

    df = pd.DataFrame(rows)

    out = REPO / "data" / "sumitomo" / "coverage_audit.parquet"
    df.to_parquet(out, index=False)
    print(f"Saved: {out}\n")

    # ---- 集計 ----
    print("=== 物質単位の根本原因分布 ===")
    print(df["root_cause"].value_counts().to_string())
    print()

    print("=== 軸別 OK / NaN カバレッジ ===")
    for a in AXES:
        statuses = df[f"{a}_status"].value_counts()
        ok = statuses.get("OK", 0)
        print(f"  {a:30s}: OK={ok:>2d} / {len(df):d}  ({ok/len(df)*100:.0f}%)  | {dict(statuses)}")
    print()

    print("=== scored_count 分布（CAS あり物質のみ）===")
    sub_df = df[df["cas"].notna()]
    print(sub_df["scored_count"].value_counts().sort_index().to_string())
    print()

    print("=== 評価不能 (scored=0) の物質 ===")
    no_score = df[df["scored_count"] == 0][["id", "name_ja", "cas", "root_cause", "primary_segment", "status"]]
    print(no_score.to_string(index=False))
    print()

    print("=== LOW_COVERAGE (1-3軸のみ) の物質 ===")
    low = df[(df["scored_count"] >= 1) & (df["scored_count"] <= 3)][["id", "name_ja", "cas", "scored_count", "primary_segment"]]
    print(low.to_string(index=False))


if __name__ == "__main__":
    main()
