"""Axis 6 — unified LLM classifier for JP/KR/TW disruption signals.

Takes the metadata parquets produced by:
- ingest/edinet_extraordinary.py    (JP 臨時報告書, doc_description=empty → uses report_nm)
- ingest/dart_major_matters.py      (KR 주요사항보고서, report_nm has the event title)
- ingest/tdnet_disclosure.py        (JP 適時開示, title has the event description)
- ingest/twse_material_info.py      (TW 重大訊息, subject has the event description)

For sources where the report title alone tells us the event type (DART/TDnet/TWSE),
we classify directly from title. For EDINET 臨時報告書 where doc_description is just
"臨時報告書" literal, we need the PDF body — but for speed today we'll classify
based on company + filing pattern + recent context (header info only).

Output: data/axis6_classified/<source>_classified_<stamp>.parquet with schema:
    source_id, source, event_type, summary_ja, supply_relevance, key_facility,
    key_product, classified_at

Resume-safe: skips IDs already classified in the latest file per source.
Batches 10 items per Gemini call to stay within 250 RPD.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import gemini_client as gemini  # noqa: E402

OUT_DIR = ROOT / "data" / "axis6_classified"
MODEL = "gemini-2.5-flash-lite"
# Pool sizes (Gemini free tier as of 2026-05):
#   gemini-2.5-flash-lite  → 250 RPD
#   gemini-2.5-pro         → 100 RPD (separate pool, useful as fallback)
#   gemini-2.5-flash       →  20 RPD (too small for batches)

# Source registry: (source_name, input_parquet_glob, id_col, text_cols_for_prompt)
SOURCES = [
    {
        "name": "edinet_extraordinary",
        "glob": str(ROOT / "data" / "edinet" / "extraordinary_reports_*.parquet"),
        "id_col": "doc_id",
        "ctx_cols": ["company", "submit_date", "doc_description", "doc_type_code"],
    },
    {
        "name": "dart_major_matters",
        "glob": str(ROOT / "data" / "dart" / "dart_major_matters_*.parquet"),
        "id_col": "rcept_no",
        "ctx_cols": ["corp_name", "rcept_dt", "report_nm", "industry"],
    },
    {
        "name": "tdnet_disclosure",
        "glob": str(ROOT / "data" / "tdnet" / "tdnet_disclosure_*.parquet"),
        "id_col": "pdf_url",
        "ctx_cols": ["company", "date", "title", "industry"],
    },
    {
        "name": "twse_material_info",
        "glob": str(ROOT / "data" / "twse" / "twse_material_info_*.parquet"),
        "id_col": "subject",  # composite-ish, but TWSE has no doc_id
        "ctx_cols": ["company_name", "filing_date", "subject", "market"],
    },
]

EVENT_TYPES = [
    "PLANT_INCIDENT",  # 火災・事故・爆発
    "PRODUCTION_HALT",  # 操業停止・生産中断
    "FORCE_MAJEURE",
    "FACILITY_DAMAGE",  # 災害による損害
    "RECALL",
    "STRATEGIC_DIVEST",  # 事業譲渡・撤退
    "M_AND_A",
    "LITIGATION",
    "REGULATORY",
    "FINANCING",  # 増資・社債・自己株式
    "GOVERNANCE",  # 役員異動・組織変更
    "GUIDANCE",
    "OTHER",
]

PROMPT_TEMPLATE = """あなたは化学品の供給安定性ダッシュボード用に企業開示を分類するアナリストです。

以下の {n} 件の開示文書について、各々に対して JSON 配列で分類結果を返してください。
リスト順序は入力と同じにすること。

各エントリのスキーマ:
{{
  "source_id": "<入力 source_id をそのまま>",
  "event_type": "{event_types}",
  "summary_ja": "<1文の日本語要約, 80字以内>",
  "supply_relevance": "HIGH" | "MED" | "LOW",
  "key_facility": "<施設・工場名 or null>",
  "key_product": "<製品名 or null>"
}}

supply_relevance 基準:
- HIGH: 工場火災/操業停止/FM発令/能力削減/災害損害/リコール
- MED:  事業譲渡・売却決定・大型訴訟・規制違反
- LOW:  増資・配当・役員異動・自己株式・通常M&A・業績修正

入力文書リスト:
{rows}

JSON配列のみ返却。前置き不要。
"""

SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "source_id": {"type": "string"},
            "event_type": {"type": "string"},
            "summary_ja": {"type": "string"},
            "supply_relevance": {"type": "string"},
            "key_facility": {"type": "string"},  # empty string when N/A — Gemini schema lacks null union
            "key_product": {"type": "string"},
        },
        "required": ["source_id", "event_type", "summary_ja", "supply_relevance"],
    },
}

BATCH = 12


def latest_input(source: dict) -> Path | None:
    from glob import glob
    paths = sorted(glob(source["glob"]))
    return Path(paths[-1]) if paths else None


def latest_output(source_name: str) -> Path | None:
    paths = sorted(OUT_DIR.glob(f"{source_name}_classified_*.parquet"))
    return paths[-1] if paths else None


def build_rows_text(batch: pd.DataFrame, source: dict) -> str:
    lines = []
    for _, r in batch.iterrows():
        sid = str(r[source["id_col"]])[:80]
        ctx_parts = [f"{c}={r.get(c, '') or ''}" for c in source["ctx_cols"]]
        lines.append(f"- source_id={sid} | {' | '.join(ctx_parts)}")
    return "\n".join(lines)


def classify_source(source: dict, max_items: int | None = None, model: str = MODEL) -> int:
    in_path = latest_input(source)
    if not in_path:
        print(f"[{source['name']}] no input parquet, skip")
        return 0
    df = pd.read_parquet(in_path)
    if df.empty:
        print(f"[{source['name']}] empty input, skip")
        return 0

    seen: set = set()
    out_path = latest_output(source["name"])
    if out_path:
        prev = pd.read_parquet(out_path)
        seen = set(prev["source_id"].astype(str))
        print(f"[{source['name']}] {len(seen)} already classified")

    todo = df[~df[source["id_col"]].astype(str).isin(seen)].copy()
    if max_items:
        todo = todo.head(max_items)
    print(f"[{source['name']}] classifying {len(todo)} new items (input {len(df)} total)")
    if todo.empty:
        return 0

    results: list[dict] = []
    n_batches = (len(todo) + BATCH - 1) // BATCH
    for bi in range(n_batches):
        batch = todo.iloc[bi * BATCH:(bi + 1) * BATCH]
        rows_text = build_rows_text(batch, source)
        prompt = PROMPT_TEMPLATE.format(
            n=len(batch),
            event_types=" | ".join(EVENT_TYPES),
            rows=rows_text,
        )
        print(f"  [{bi+1}/{n_batches}] batch of {len(batch)}", flush=True)
        try:
            parsed = gemini.chat(prompt, model=model, json_schema=SCHEMA, max_output_tokens=8000)
        except RuntimeError as e:
            print(f"    FAILED: {e}")
            time.sleep(5)
            continue
        if not isinstance(parsed, list):
            print(f"    unexpected response type {type(parsed)}, skip")
            continue
        for item in parsed:
            results.append({
                "source_id": str(item.get("source_id", "")),
                "source": source["name"],
                "event_type": item.get("event_type", "OTHER"),
                "summary_ja": (item.get("summary_ja") or "")[:200],
                "supply_relevance": (item.get("supply_relevance") or "LOW").upper(),
                "key_facility": item.get("key_facility"),
                "key_product": item.get("key_product"),
                "_classified_at": datetime.now(timezone.utc).isoformat(),
            })
        time.sleep(4)  # Flash-Lite 250 RPD → ~15 RPM ceiling

    if not results:
        return 0

    new_df = pd.DataFrame(results)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    out = OUT_DIR / f"{source['name']}_classified_{stamp}.parquet"
    if out.exists():
        prev = pd.read_parquet(out)
        new_df = pd.concat([prev, new_df], ignore_index=True).drop_duplicates(
            subset=["source_id"], keep="last",
        )
    new_df.to_parquet(out, index=False)
    print(f"[{source['name']}] wrote {len(new_df)} total → {out} (+{len(results)} new)")
    return len(results)


def main(only: str | None = None, max_items: int | None = None, model: str = MODEL):
    if not gemini.is_available():
        print("ERROR: Gemini API key not set. Configure ~/.config/gemini/keys.json")
        sys.exit(1)
    sources = [s for s in SOURCES if only is None or s["name"] == only]
    total = 0
    for s in sources:
        n = classify_source(s, max_items=max_items, model=model)
        total += n
        print()
    print(f"\nDONE — classified {total} new items across {len(sources)} sources (model={model})")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run for a single source name")
    ap.add_argument("--max", type=int, default=None, help="cap per source")
    ap.add_argument("--model", default=MODEL, help="Gemini model (default flash-lite, use gemini-2.5-pro to spend separate quota)")
    args = ap.parse_args()
    main(only=args.only, max_items=args.max, model=args.model)
