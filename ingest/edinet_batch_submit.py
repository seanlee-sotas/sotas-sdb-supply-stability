"""Submit all EDINET capacity snippets to Anthropic Batch API for structured extraction.

Each snippet → Claude extracts structured rows: {product, facility, capacity_ton_yr,
direction (new/expand/reduce/maintain), year, confidence}.

Batch API benefits:
- 50% cheaper than realtime
- Returns within 24h (typically faster)
- Up to 100k requests per batch

After batch completes, run edinet_batch_collect.py to download + parse results.

Cost estimate: ~6,650 snippets × $0.004 = ~$25 (batched).
"""
import json
import os
from datetime import datetime
from pathlib import Path

import duckdb
from anthropic import Anthropic
from anthropic.types.messages.batch_create_params import Request
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming

ROOT = Path(__file__).resolve().parent.parent
EDINET_DIR = ROOT / "data" / "edinet"
BATCH_DIR = ROOT / "data" / "edinet" / "batches"

MODEL = "claude-sonnet-4-6"

SYSTEM = """日本の化学メーカーの有報・統合報告書・中期経営計画から「生産能力・新増設」に関するテキストスニペットが渡されます。
構造化抽出を行い、STRICT JSON で出力してください。前置きや説明は一切不要。

スキーマ:
{
  "extracted": [
    {
      "product": "<製品名 (例: エチレン, ポリエチレン, 触媒)>",
      "facility": "<工場/拠点名 or null (例: 千葉工場, 鹿島)>",
      "capacity_value": <数値 or null>,
      "capacity_unit": "<単位 (千t/年, t/年, m3/年, kL/年など) or null>",
      "direction": "new" | "expand" | "reduce" | "maintain" | "unknown",
      "target_year": <西暦 or null>,
      "confidence": "high" | "medium" | "low"
    }
  ]
}

スニペットに具体的な数値・工場名・年次が含まれない場合、extracted は空配列 [] でOK。
confidence は「明確に書かれている=high」「言及はあるが曖昧=medium」「推測=low」"""

USER_TEMPLATE = """企業: {company}
文書種別: {doctype}
期間: {period}

スニペット:
{snippet}"""


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set"); return
    client = Anthropic()

    snippets_p = max(EDINET_DIR.glob("capacity_snippets_*.parquet"))
    con = duckdb.connect()
    con.execute(f"CREATE VIEW snip AS SELECT * FROM '{snippets_p}'")
    df = con.execute("SELECT row_number() OVER () AS rn, * FROM snip").df()
    print(f"Submitting {len(df)} snippets from {snippets_p}")

    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    requests = []
    for _, row in df.iterrows():
        requests.append(Request(
            custom_id=f"snippet_{int(row['rn'])}",
            params=MessageCreateParamsNonStreaming(
                model=MODEL,
                max_tokens=800,
                system=SYSTEM,
                messages=[{"role": "user", "content": USER_TEMPLATE.format(
                    company=row["company"], doctype=row["doctype"],
                    period=row["period"], snippet=row["snippet"],
                )}],
            ),
        ))

    print(f"Built {len(requests)} batch requests. Submitting...")
    batch = client.messages.batches.create(requests=requests)
    print(f"Batch created: {batch.id}")
    print(f"  Status: {batch.processing_status}")
    print(f"  Submitted: {batch.created_at}")

    # Save batch metadata
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    meta = {
        "batch_id": batch.id,
        "submitted_at": batch.created_at.isoformat() if hasattr(batch.created_at, "isoformat") else str(batch.created_at),
        "snippet_count": len(requests),
        "source_parquet": str(snippets_p.relative_to(ROOT)),
        "model": MODEL,
    }
    meta_path = BATCH_DIR / f"batch_{stamp}.json"
    meta_path.write_text(json.dumps(meta, indent=2, default=str))
    print(f"\nMetadata saved: {meta_path}")
    print(f"\nNext step: wait for completion (usually <24h), then run edinet_batch_collect.py")
    print(f"Check status: client.messages.batches.retrieve('{batch.id}')")


if __name__ == "__main__":
    main()
