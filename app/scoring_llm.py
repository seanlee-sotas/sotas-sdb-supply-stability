"""LLM-augmented narrative generator (Gemini 2.5 Flash, free tier 1500 RPD).

Drop-in replacement for scoring.narrative() that takes the same inputs but produces
a context-aware multi-paragraph review using the chemical's full PubChem metadata,
all 7 axis scores, and industry weights.

Falls back to rule-based scoring.narrative() if Gemini is unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chemicals_loader as cl
import gemini_client as gc
import scoring

MODEL = "gemini-2.5-flash-lite"  # 250 RPD free tier vs 20 RPD on plain flash

PROMPT_TEMPLATE = """\
あなたは化学品の調達戦略アナリストです。以下の物質の供給安定性7軸スコアを読み、
購買・R&D 担当者向けに **日本語で簡潔な総評** を書いてください。

## 物質
- 名称: {name}
- CAS: {cas}
- カテゴリ: {category}
- 分子式: {formula}
- 用途仮説: {pinned_note}

## 業界重み ({industry_name})
{weights_text}

## 7軸スコア (0=高リスク, 100=安定)
{scores_text}

## 総合スコア
{composite_text}

## 出力フォーマット (Markdown, 300字以内)

1行目: ヘッドライン（評価レベル + 主因の1行）
空行
**🚨 リスク要因:** リスト2件以内 (最も低スコアの軸を理由付きで)
**✅ 強み:** リスト2件以内 (最も高スコアの軸)
**💡 推奨アクション:** 具体的な調達戦略の示唆 (1-3項目)

注意:
- 評価データ不足 (4軸未満) の場合は、headline で明示し推奨アクションは「データ補強優先」
- 推奨アクションは抽象論ではなく、本物質の固有事情に即した内容にすること
- 業界重みの高い軸 (top 2) のスコアを優先的に評価軸に含めること
"""


def llm_narrative(chem: dict, sub_scores: dict[str, dict], comp: dict) -> str:
    """Generate narrative via Gemini. Falls back to rule-based on any error."""
    if not gc.is_available():
        return scoring.narrative(chem, sub_scores, comp)

    name = chem.get("display_name") or chem["cas"]
    industries = cl.industries()
    ind_meta = industries.get(comp["industry"]) or industries.get("default") or {}
    ind_name = ind_meta.get("name_ja", comp["industry"])
    weights = comp.get("weights") or {}
    weights_text = "\n".join(
        f"- {scoring.AXIS_LABELS_JA[k]}: {w*100:.0f}%"
        for k, w in sorted(weights.items(), key=lambda x: -x[1])
    )
    scores_text = "\n".join(
        f"- {scoring.AXIS_LABELS_JA[k]}: "
        + (f"{info['score']:.0f}点 ({info['value']})" if info["score"] is not None else "— (データなし)")
        + f"  // {info['note']}"
        for k, info in sub_scores.items()
    )
    if comp["composite"] is not None:
        composite_text = (
            f"{comp['composite']:.0f}/100 ({comp['grade']})、{comp['scored_axes']}/7軸で評価、"
            f"信頼度: {comp['confidence']}"
        )
    else:
        composite_text = f"評価データ不足 ({comp['scored_axes']}/7軸のみ、最低{scoring.MIN_SCORED_AXES}軸必要)"

    prompt = PROMPT_TEMPLATE.format(
        name=name,
        cas=chem["cas"],
        category=chem.get("category_norm") or "—",
        formula=chem.get("molecular_formula") or "—",
        pinned_note=chem.get("pinned_note") or "—",
        industry_name=ind_name,
        weights_text=weights_text,
        scores_text=scores_text,
        composite_text=composite_text,
    )
    try:
        text = gc.chat(prompt, model=MODEL, max_output_tokens=1500, temperature=0.4)
        return text.strip()
    except RuntimeError as e:
        return scoring.narrative(chem, sub_scores, comp) + f"\n\n_(Gemini LLM失敗、ルールベースに fallback: {e})_"
