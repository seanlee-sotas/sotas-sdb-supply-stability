"""LLM-assisted HS6 mapping for chemicals.parquet.

Uses Gemini 2.5 Pro (free tier 100 RPD) to assign HS6 codes to each chemical that
lacks an exact mapping in chemicals_hs_map.parquet. Batches 25 chemicals per call
→ ~17 calls for 427 chemicals → well within quota.

Output: appends rows with source='llm_gemini' and confidence 0.6-0.8 to
data/chemicals/chemicals_hs_map.parquet. Existing materials_yml mappings are kept.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
import gemini_client as gc

ROOT = Path(__file__).resolve().parents[2]
CHEM_P = ROOT / "data" / "chemicals" / "chemicals.parquet"
HS_MAP_P = ROOT / "data" / "chemicals" / "chemicals_hs_map.parquet"

BATCH_SIZE = 25
# Model selection notes (free tier quotas as of 2026-05):
# - gemini-2.5-pro:        5 RPM, 100 RPD — quota tight
# - gemini-2.5-flash:     10 RPM,  20 RPD — main model, burns out fast
# - gemini-2.5-flash-lite:           250 RPD — fallback for retries
# - gemini-2.0-flash-lite:           too restrictive
MODEL = "gemini-2.5-flash-lite"

HS_LABELS = {
    "25": "塩・硫黄・土石類", "27": "鉱物性燃料・油・蝋", "28": "無機化学品",
    "29": "有機化学品", "30": "医療用品", "31": "肥料",
    "32": "なめし用・染料・顔料・塗料・インキ", "34": "石けん・界面活性剤",
    "38": "各種化学工業生産品", "39": "プラスチック", "40": "ゴム",
}

PROMPT_TEMPLATE = """\
You are a Harmonized System (HS) classification expert. For each chemical below,
return the most appropriate HS6 code(s) from chapters 25, 27, 28, 29, 30, 31, 32,
34, 38, 39, 40. Use HS 2022 (H6) revision.

Rules:
- Return 1-2 HS6 codes per chemical, ranked by relevance.
- If genuinely uncertain across chapters, return the chapter-level HS2 + "00" suffix
  and lower confidence to 0.4.
- For polymers in primary forms → Ch 39 (plastics) or 40 (rubber).
- For monomers / intermediates → Ch 29 (organic) or 28 (inorganic).
- For mixed regulated substances (POPs, SVHC) — pick the dominant component's chapter.

Chemicals to classify:
{rows}

Return JSON only (no commentary), matching this schema:
{{
  "mappings": [
    {{"cas": "74-85-1", "hs6": "290121", "confidence": 0.9, "rationale": "ethene primary form"}},
    ...
  ]
}}
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cas": {"type": "string"},
                    "hs6": {"type": "string"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["cas", "hs6", "confidence"],
            },
        }
    },
    "required": ["mappings"],
}


def main():
    if not gc.is_available():
        print("Gemini API key not configured. See app/gemini_client.py.", file=sys.stderr)
        sys.exit(1)
    con = duckdb.connect()
    chems = con.execute(f"SELECT cas, name_en, category_norm, molecular_formula FROM '{CHEM_P}'").df()
    existing = pd.read_parquet(HS_MAP_P)
    # Skip CAS that already have an exact HS6 from ANY non-category source
    have_exact_cas = set(
        existing[existing["hs6"].notna() & (existing["source"] != "category_default")]["cas"]
    )
    todo = chems[~chems["cas"].isin(have_exact_cas)].reset_index(drop=True)
    print(f"Skipping {len(have_exact_cas)} CAS with existing exact HS6 (materials_yml/llm_gemini)")
    print(f"To classify: {len(todo)} CAS in batches of {BATCH_SIZE}")

    new_rows: list[dict] = []
    for batch_idx in range(0, len(todo), BATCH_SIZE):
        batch = todo.iloc[batch_idx:batch_idx + BATCH_SIZE]
        rows_text = "\n".join(
            f"- CAS={r['cas']}, name={r['name_en']}, category={r['category_norm']}, formula={r['molecular_formula'] or '?'}"
            for _, r in batch.iterrows()
        )
        prompt = PROMPT_TEMPLATE.format(rows=rows_text)
        n = batch_idx // BATCH_SIZE + 1
        total_n = (len(todo) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  [{n}/{total_n}] batch CAS {batch.iloc[0]['cas']} … {batch.iloc[-1]['cas']}")
        try:
            result = gc.chat(prompt, model=MODEL, json_schema=SCHEMA, max_output_tokens=12000)
        except RuntimeError as e:
            print(f"    FAILED: {e}")
            continue
        for m in result.get("mappings", []):
            cas = m.get("cas", "").strip()
            hs6 = str(m.get("hs6", "")).strip().zfill(6)
            if not cas or len(hs6) != 6:
                continue
            new_rows.append({
                "cas": cas,
                "hs6": hs6,
                "hs_chapter": hs6[:2],
                "hs_label": HS_LABELS.get(hs6[:2], hs6[:2]),
                "confidence": float(m.get("confidence", 0.6)),
                "source": "llm_gemini",
                "rationale": m.get("rationale", "")[:200],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        time.sleep(4.5)  # ~13 RPM ceiling on Flash free tier (15 RPM hard limit)

    if not new_rows:
        print("No new mappings.")
        return

    new_df = pd.DataFrame(new_rows)
    # Merge: existing rows first, then new (dedupe on cas+hs6 prefer existing)
    if "rationale" not in existing.columns:
        existing["rationale"] = None
    combined = pd.concat([existing, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["cas", "hs6"], keep="first")
    combined.to_parquet(HS_MAP_P, index=False)
    print(f"\nWrote {HS_MAP_P}: {len(combined)} total mapping rows (+{len(new_rows)} new)")
    print("\nNew source distribution:")
    print(combined["source"].value_counts())
    print(f"\nUnique CAS with HS6 exact: {combined[combined['hs6'].notna()]['cas'].nunique()}")


if __name__ == "__main__":
    main()
