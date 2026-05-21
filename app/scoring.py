"""Composite supply-stability scoring for a single chemical (CAS-keyed).

For each of the 7 axes, compute a normalised 0-100 sub-score (high = stable).
Apply industry-specific weights from materials_scope.yml → final composite (0-100, A-F).

All scorers return:
    {"score": float | None, "value": str, "note": str}
  - `score`: None when there is not enough underlying data
  - `value`: raw indicator displayed verbatim
  - `note`: one-line reason for the score
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

import chemicals_loader as cl

ROOT = Path(__file__).resolve().parent.parent
COMTRADE_DIR = ROOT / "data" / "comtrade"
ECHA_DIR = ROOT / "data" / "echa"
REG_DIR = ROOT / "data" / "regulations"
SEC_DIR = ROOT / "data" / "sec"
EDINET_DIR = ROOT / "data" / "edinet"
WB_DIR = ROOT / "data" / "worldbank"
SUPPLIER_DIR = ROOT / "data" / "supplier"

AXIS_KEYS = [
    "axis1_capacity",
    "axis2_supply_demand",
    "axis3_jp_concentration",
    "axis4_global_hhi",
    "axis5_regulation",
    "axis6_events",
    "axis7_price",
]
AXIS_LABELS_JA = {
    "axis1_capacity": "軸1 生産能力",
    "axis2_supply_demand": "軸2 需給バランス",
    "axis3_jp_concentration": "軸3 サプライヤー集中度",
    "axis4_global_hhi": "軸4 地政学(HHI)",
    "axis5_regulation": "軸5 規制リスク",
    "axis6_events": "軸6 供給途絶イベント",
    "axis7_price": "軸7 価格変動性",
}


def _latest(directory: Path, prefix: str) -> Path | None:
    files = sorted(directory.glob(f"{prefix}_*.parquet"))
    non_quick = [p for p in files if "_quick" not in p.stem]
    if non_quick:
        return max(non_quick)
    return max(files) if files else None


@lru_cache(maxsize=1)
def _con():
    return duckdb.connect(":memory:")


def _grade(score: float | None) -> str:
    if score is None:
        return "—"
    bp = cl._scope_yaml().get("scoring", {}).get("grade_breakpoints", {})
    if score >= bp.get("A", 85): return "A"
    if score >= bp.get("B", 70): return "B"
    if score >= bp.get("C", 55): return "C"
    if score >= bp.get("D", 40): return "D"
    if score >= bp.get("E", 25): return "E"
    return "F"


# ---------------------------------------------------------------------------
# Per-axis scorers
# ---------------------------------------------------------------------------

def score_axis1(chem: dict) -> dict:
    """軸1は現状 chemical-agnostic な keyword 抽出に依存しており、個別物質の評価には使えない。
    JA alias 拡充 + capacity_structured.product 紐付け (Phase B) まで全件 None 返却。
    複合スコアからは MIN_SCORED_AXES ロジックで自動除外される。"""
    return {
        "score": None,
        "value": "—",
        "note": "個別物質スコアは Phase B (JA alias生成 + product紐付け) まで保留。企業活動proxyとしては「軸1」タブで閲覧可能。",
    }


def score_axis2(chem: dict) -> dict:
    """需給バランス: Japan net-export ratio for this material's HS6 (最新年)。+1 → 100, -1 → 0."""
    hs_list = chem.get("hs6_exact") or []
    if not hs_list:
        return {"score": None, "value": "—", "note": "HS6 未確定"}
    p = _latest(COMTRADE_DIR, "trade")
    if p is None:
        return {"score": None, "value": "未取得", "note": "Comtrade データなし"}
    con = _con()
    placeholders = ",".join(["?"] * len(hs_list))
    df = con.execute(
        f"""SELECT cmdCode, period,
              SUM(CASE WHEN flowCode='X' THEN primaryValue ELSE 0 END) AS x,
              SUM(CASE WHEN flowCode='M' THEN primaryValue ELSE 0 END) AS m
            FROM '{p}'
            WHERE reporterCode = 392 AND partner2Code = 0
              AND primaryValue > 0 AND cmdCode IN ({placeholders})
            GROUP BY cmdCode, period
            HAVING SUM(primaryValue) > 0""",
        hs_list,
    ).df()
    if df.empty:
        return {"score": None, "value": "—", "note": "日本側貿易データなし"}
    latest = df.sort_values("period").groupby("cmdCode").tail(1)
    latest["ratio"] = (latest["x"] - latest["m"]) / (latest["x"] + latest["m"])
    # Take the worst (most import-dependent) HS6 for safety bias
    worst = latest.loc[latest["ratio"].idxmin()]
    ratio = float(worst["ratio"])
    score = (ratio + 1) * 50  # -1→0, 0→50, +1→100
    sign = "輸入超過" if ratio < -0.1 else "均衡" if ratio < 0.1 else "輸出超過"
    return {
        "score": score,
        "value": f"{ratio:+.2f} ({sign})",
        "note": f"HS {worst['cmdCode']} {worst['period']}年 純輸出比率",
    }


def score_axis3(chem: dict) -> dict:
    """JP上場サプライヤー数: 11+→100, 4-10→60, 1-3→25, 0→0."""
    p = _latest(SUPPLIER_DIR, "jp_supplier_count")
    if p is None:
        return {"score": None, "value": "未取得", "note": "supplier_count データなし"}
    con = _con()
    # Match by CAS (legacy parquet may key by material id; fall back to name)
    df = con.execute(f"SELECT * FROM '{p}'").df()
    if "cas" in df.columns:
        hit = df[df["cas"] == chem["cas"]]
    else:
        # fall back to name match
        name_options = [chem.get("display_name"), chem.get("name_en"), chem.get("name_ja_legacy")]
        name_options = [n for n in name_options if n]
        hit = df[df["name_ja"].isin(name_options) | df["name_en"].isin(name_options)] if name_options else df.iloc[0:0]
    if hit.empty:
        return {"score": None, "value": "—", "note": "未集計 (ピン留め17素材外)"}
    n = int(hit.iloc[0]["jp_supplier_count"])
    if n >= 11:
        score, band = 100.0, "低集中"
    elif n >= 4:
        score, band = 60.0, "中集中"
    elif n >= 1:
        score, band = 25.0, "高集中"
    else:
        score, band = 0.0, "サプライヤーなし"
    return {"score": score, "value": f"{n}社 ({band})", "note": "JP上場化学442社中の言及数"}


def score_axis4(chem: dict) -> dict:
    """世界輸出HHI: 1500未満→100、5000以上→0、線形補間。複数HS6は最悪値採用."""
    hs_list = chem.get("hs6_exact") or []
    if not hs_list:
        return {"score": None, "value": "—", "note": "HS6 未確定"}
    p = _latest(COMTRADE_DIR, "trade")
    if p is None:
        return {"score": None, "value": "未取得", "note": "Comtrade データなし"}
    con = _con()
    placeholders = ",".join(["?"] * len(hs_list))
    df = con.execute(
        f"""WITH latest AS (
              SELECT cmdCode, MAX(period) AS p FROM '{p}'
              WHERE cmdCode IN ({placeholders}) GROUP BY cmdCode
            ),
            per_reporter AS (
              SELECT t.cmdCode, t.reporterCode, SUM(t.primaryValue) AS v
              FROM '{p}' t JOIN latest l ON t.cmdCode=l.cmdCode AND t.period=l.p
              WHERE t.flowCode='X' AND t.partner2Code=0 AND t.primaryValue>0
              GROUP BY t.cmdCode, t.reporterCode
            ),
            totals AS (SELECT cmdCode, SUM(v) AS tv FROM per_reporter GROUP BY cmdCode)
            SELECT pr.cmdCode, SUM(POW(pr.v / t.tv * 100, 2)) AS hhi
            FROM per_reporter pr JOIN totals t USING (cmdCode)
            GROUP BY pr.cmdCode""",
        hs_list,
    ).df()
    if df.empty:
        return {"score": None, "value": "—", "note": "輸出データなし"}
    worst = df["hhi"].max()
    hhi = float(worst)
    # 1500 → 100, 5000 → 0 (linear)
    if hhi <= 1500:
        score = 100.0
    elif hhi >= 5000:
        score = 0.0
    else:
        score = (5000 - hhi) / (5000 - 1500) * 100
    if hhi < 1500:
        band = "低集中"
    elif hhi < 2500:
        band = "中集中"
    else:
        band = "高集中"
    return {"score": score, "value": f"{hhi:,.0f} ({band})", "note": "HS6最悪値、世界輸出ベース"}


def score_axis5(chem: dict) -> dict:
    """規制リスト該当: 0件→100、SVHC 1→60、SVHC 2+ or POP→30."""
    cas = chem["cas"]
    svhc_p = _latest(ECHA_DIR, "svhc")
    pops_p = _latest(REG_DIR, "pops")
    svhc_hits = 0
    pops_hits = 0
    notes = []
    if svhc_p:
        con = _con()
        n = con.execute(f"SELECT COUNT(*) FROM '{svhc_p}' WHERE cas_number = ?", [cas]).fetchone()[0]
        svhc_hits = int(n)
        if n:
            notes.append(f"SVHC {n}件")
    if pops_p:
        pops = pd.read_parquet(pops_p)
        pops_hits = int((pops["cas"] == cas).sum())
        if pops_hits:
            notes.append(f"POPs {pops_hits}件")
    if svhc_hits == 0 and pops_hits == 0:
        return {"score": 100.0, "value": "規制該当なし", "note": "ECHA SVHC / Stockholm POPs"}
    if pops_hits > 0:
        return {"score": 20.0, "value": " / ".join(notes), "note": "POPs該当=高リスク"}
    if svhc_hits >= 2:
        return {"score": 30.0, "value": " / ".join(notes), "note": "SVHC複数該当"}
    return {"score": 55.0, "value": " / ".join(notes), "note": "SVHC 1件該当"}


def score_axis6(chem: dict) -> dict:
    """過去の供給途絶: SEC 8-K HIGH supply_relevance イベント数 (3年)."""
    tickers = chem.get("sec_tickers") or []
    if not tickers:
        return {"score": None, "value": "—", "note": "SEC ticker 未マッピング"}
    p = _latest(SEC_DIR, "item801_classified")
    if p is None:
        return {"score": None, "value": "未取得", "note": "LLM分類済データなし"}
    con = _con()
    placeholders = ",".join(["?"] * len(tickers))
    df = con.execute(
        f"""SELECT supply_relevance, COUNT(*) c FROM '{p}'
            WHERE ticker IN ({placeholders}) GROUP BY supply_relevance""",
        tickers,
    ).df()
    if df.empty:
        return {"score": 100.0, "value": "0件", "note": "関連企業の供給途絶開示なし"}
    counts = {r["supply_relevance"]: int(r["c"]) for _, r in df.iterrows()}
    high = counts.get("HIGH", 0)
    med = counts.get("MED", 0)
    # Score: heavily penalise HIGH, lightly penalise MED
    raw = high * 25 + med * 5
    score = max(0, 100 - raw)
    return {
        "score": float(score),
        "value": f"HIGH {high} / MED {med}",
        "note": f"関連米企業 {len(tickers)}社の供給リスクイベント",
    }


def score_axis7(chem: dict) -> dict:
    """価格変動性: 12ヶ月年率ボラティリティ (直近5年)。15%未満→100、60%以上→0."""
    wb = chem.get("wb_commodity")
    if not wb:
        return {"score": None, "value": "—", "note": "WB商品コード 未マッピング"}
    p = _latest(WB_DIR, "prices_monthly")
    if p is None:
        return {"score": None, "value": "未取得", "note": "WBデータなし"}
    con = _con()
    df = con.execute(
        f"""SELECT date, price FROM '{p}'
            WHERE commodity = ? AND date >= ?
            ORDER BY date""",
        [wb, pd.Timestamp.now() - pd.DateOffset(years=5)],
    ).df()
    if len(df) < 24:
        return {"score": None, "value": "—", "note": "価格履歴 < 24ヶ月"}
    monthly_ret = df["price"].pct_change()
    vol_annual = float(monthly_ret.std() * (12 ** 0.5) * 100)
    if vol_annual <= 15:
        score = 100.0
    elif vol_annual >= 60:
        score = 0.0
    else:
        score = (60 - vol_annual) / (60 - 15) * 100
    return {
        "score": score,
        "value": f"{vol_annual:.1f}%",
        "note": "12ヶ月rolling、年率化",
    }


SCORERS = {
    "axis1_capacity": score_axis1,
    "axis2_supply_demand": score_axis2,
    "axis3_jp_concentration": score_axis3,
    "axis4_global_hhi": score_axis4,
    "axis5_regulation": score_axis5,
    "axis6_events": score_axis6,
    "axis7_price": score_axis7,
}


def compute_all(cas: str) -> dict[str, dict]:
    chem = cl.get_chemical(cas)
    if not chem:
        return {}
    return {axis: SCORERS[axis](chem) for axis in AXIS_KEYS}


MIN_SCORED_AXES = 4  # Below this, composite is reported as "low-confidence"


def composite(sub_scores: dict[str, dict], industry: str = "default") -> dict:
    """Weighted composite using industries[<industry>].weights, renormalised over scored axes.

    Confidence:
    - "high"  : ≥6 axes scored
    - "medium": 4-5 axes scored
    - "low"   : ≤3 axes scored — composite suppressed (None)
    """
    industries = cl.industries()
    weights = (industries.get(industry) or industries.get("default") or {}).get("weights") or {}

    scored = {k: v for k, v in sub_scores.items() if v.get("score") is not None}
    n_scored = len(scored)

    if n_scored >= 6:
        confidence = "high"
    elif n_scored >= MIN_SCORED_AXES:
        confidence = "medium"
    else:
        confidence = "low"

    if n_scored == 0:
        return {
            "composite": None, "grade": "—", "confidence": "low",
            "scored_axes": 0, "total_axes": len(sub_scores),
            "industry": industry, "weights": weights,
        }

    total_w = sum(weights.get(k, 0) for k in scored)
    if total_w == 0:
        return {
            "composite": None, "grade": "—", "confidence": confidence,
            "scored_axes": n_scored, "total_axes": len(sub_scores),
            "industry": industry, "weights": weights,
        }
    composite_val = sum(scored[k]["score"] * weights.get(k, 0) for k in scored) / total_w

    return {
        # Suppress composite when only 1-3 axes were scored
        "composite": composite_val if confidence != "low" else None,
        "composite_raw": composite_val,  # always available for charts
        "grade": _grade(composite_val) if confidence != "low" else "—",
        "confidence": confidence,
        "scored_axes": n_scored,
        "total_axes": len(sub_scores),
        "industry": industry,
        "weights": weights,
    }


# ---------------------------------------------------------------------------
# 総評 (rule-based narrative; replace with LLM later)
# ---------------------------------------------------------------------------

def narrative(chem: dict, sub_scores: dict[str, dict], comp: dict) -> str:
    """Generate a multi-paragraph narrative review based on the sub-scores."""
    name = chem.get("display_name") or chem["cas"]
    parts: list[str] = []
    industries = cl.industries()
    ind = comp.get("industry") or "default"
    ind_meta = industries.get(ind) or industries.get("default") or {}
    ind_name = ind_meta.get("name_ja", ind)

    # Headline
    if comp["composite"] is None:
        if comp["scored_axes"] == 0:
            parts.append(
                f"**{name}** は全7軸で評価データ未整備。CAS番号 {chem['cas']} は化合物マスタには登録済み "
                f"だが、各軸のソースとの突合データなし。"
            )
        else:
            scored_names = [
                AXIS_LABELS_JA[k] for k, v in sub_scores.items() if v.get("score") is not None
            ]
            parts.append(
                f"**{name}** の供給安定性は **評価データ不足** ({comp['scored_axes']}/7 軸のみデータあり: "
                f"{', '.join(scored_names)})。総合スコアは {MIN_SCORED_AXES} 軸以上のデータが揃った時点で算出。"
                f"参考: 部分集計では {comp['composite_raw']:.0f}/100 だが、サンプル軸偏りで実態を反映しない可能性が高い。"
            )
    else:
        comp_v = comp["composite"]
        grade = comp["grade"]
        conf_label = {"high": "高", "medium": "中", "low": "低"}[comp["confidence"]]
        if grade in ("A", "B"):
            risk_word = "**比較的安定**"
        elif grade == "C":
            risk_word = "**やや注意**"
        elif grade in ("D", "E"):
            risk_word = "**要注意**"
        else:
            risk_word = "**🚨 高リスク**"
        parts.append(
            f"**{name}** の{ind_name}向け供給安定性は {risk_word} (総合 **{comp_v:.0f}/100 ({grade})**、"
            f"{comp['scored_axes']}/7 軸で評価、データ信頼度: {conf_label})。"
        )

    # Worst axes
    scored = [(k, v) for k, v in sub_scores.items() if v.get("score") is not None]
    if scored:
        worst = sorted(scored, key=lambda kv: kv[1]["score"])[:2]
        risk_lines = []
        for axis, info in worst:
            if info["score"] < 60:
                risk_lines.append(
                    f"- **{AXIS_LABELS_JA[axis]}** {info['score']:.0f}点: "
                    f"{info['value']} — {info['note']}"
                )
        if risk_lines:
            parts.append("\n**🚨 リスク要因:**\n" + "\n".join(risk_lines))

    # Best axes
    if scored:
        best = sorted(scored, key=lambda kv: -kv[1]["score"])[:2]
        strength_lines = []
        for axis, info in best:
            if info["score"] >= 70:
                strength_lines.append(
                    f"- **{AXIS_LABELS_JA[axis]}** {info['score']:.0f}点: "
                    f"{info['value']} — {info['note']}"
                )
        if strength_lines:
            parts.append("\n**✅ 強み:**\n" + "\n".join(strength_lines))

    # Missing data
    missing = [k for k, v in sub_scores.items() if v.get("score") is None]
    if missing:
        parts.append(
            "\n**📊 評価不可:** " + " / ".join(AXIS_LABELS_JA[k] for k in missing)
            + " — 該当軸のデータソース未整備またはマッピング未完了"
        )

    # Actionable conclusion
    if comp["composite"] is not None:
        cs = comp["composite"]
        if cs < 40:
            parts.append(
                "\n**💡 推奨アクション:** (1) 国内代替サプライヤー開拓 (2) "
                "規制動向ウォッチ強化 (3) 在庫水準の見直し (4) 業界団体ヒアリングで定性情報補完"
            )
        elif cs < 60:
            parts.append(
                "\n**💡 推奨アクション:** (1) 主要サプライヤーとの中長期契約見直し "
                "(2) 価格ヘッジ戦略の検討 (3) 過去の供給途絶イベントの精査"
            )
        else:
            parts.append(
                "\n**💡 現状判断:** 直近の供給リスクシグナルは限定的。"
                "四半期毎の軸再評価で変化を捕捉。"
            )

    return "\n".join(parts)
