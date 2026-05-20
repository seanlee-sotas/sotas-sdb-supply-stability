"""Axis 1 (生産能力・新増設) scaffold.

The /research-company-jp skill already harvested 有価証券報告書/統合報告書/中期経営計画
for 443 chemical-adjacent companies into the Vault as Markdown. This script extracts
text snippets around "生産能力" mentions per company per year, giving us a structured
view of which company / year / report mentions capacity changes — ready for downstream
LLM table extraction.

This is an indexing step, not full structured extraction. LLM call to parse
"company X expanded plant Y by 30k t/yr in 2024" → table goes in a later iteration.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "edinet"

VAULT = Path("/Users/seanlee/My Drive (sean.lee@sotas.co.jp)/Vault")
SOURCE_DIR = VAULT / "1. Anchors" / "_industry_research" / "_chemicals" / "jp"

# Pattern to find 生産能力 mentions with surrounding context
CONTEXT_CHARS = 400  # chars before + after the match for snippet
KEYWORDS = ["生産能力", "プラント能力", "設備能力", "年産", "生産設備"]
KEY_RE = re.compile("|".join(re.escape(k) for k in KEYWORDS))

# Filename parser: <company>_<doctype>_<period>.md
FILENAME_RE = re.compile(
    r"^(?P<company>.+?)_(?P<doctype>有価証券報告書|有価証券報告書訂正|統合報告書|中期経営計画|サステナビリティレポート)_(?P<period>.+?)(?:_提出\d+)?$"
)


def parse_filename(p: Path) -> dict | None:
    m = FILENAME_RE.match(p.stem)
    if not m:
        return None
    return m.groupdict()


def extract_snippets(text: str, max_snippets: int = 5) -> list[str]:
    out = []
    positions = [m.start() for m in KEY_RE.finditer(text)]
    if not positions:
        return out
    # Merge nearby positions so we don't emit overlapping snippets
    merged = [positions[0]]
    for p in positions[1:]:
        if p - merged[-1] > CONTEXT_CHARS:
            merged.append(p)
    for pos in merged[:max_snippets]:
        start = max(0, pos - CONTEXT_CHARS)
        end = min(len(text), pos + CONTEXT_CHARS)
        snippet = text[start:end].strip()
        snippet = re.sub(r"\s+", " ", snippet)
        out.append(snippet)
    return out


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SOURCE_DIR.exists():
        print(f"SOURCE_DIR not found: {SOURCE_DIR}")
        return

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    company_dirs = sorted([d for d in SOURCE_DIR.iterdir() if d.is_dir()])
    print(f"Scanning {len(company_dirs)} company folders...")

    for ci, cdir in enumerate(company_dirs, 1):
        if ci % 50 == 0:
            print(f"  [{ci}/{len(company_dirs)}] {cdir.name}", flush=True)
        for md in cdir.glob("*.md"):
            meta = parse_filename(md)
            if not meta:
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            snippets = extract_snippets(text)
            if not snippets:
                continue
            for s in snippets:
                rows.append({
                    "company": meta["company"],
                    "doctype": meta["doctype"],
                    "period": meta["period"],
                    "file_path": str(md.relative_to(VAULT)),
                    "snippet": s,
                    "_fetched_at": fetched_at,
                })

    df = pd.DataFrame(rows)
    stamp = datetime.now().strftime("%Y%m%d")
    out_path = DATA_DIR / f"capacity_snippets_{stamp}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"\nWrote {len(df)} snippets from {df['company'].nunique()} companies to {out_path}")
    print(f"\nDoctype distribution:")
    print(df["doctype"].value_counts())
    print(f"\nTop 10 companies by snippet count (proxy: active capacity discussion):")
    print(df["company"].value_counts().head(10))


if __name__ == "__main__":
    main()
