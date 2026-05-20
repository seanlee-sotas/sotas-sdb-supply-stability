"""Axis 3 (サプライヤー集中度) ingest — proxy via JP-listed competitor count.

Real HHI calculation needs per-company production capacity which isn't
structured in EDINET XBRL today. As a usable proxy, we count how many
JP-listed chemical companies (out of 443) mention each material in their
capacity snippets (axis 1 source) — this gives:

- # of JP competitors (lower = more concentrated supply within Japan)
- A rough concentration band (3-tier: high / medium / low concentration)

This is JP-side only. Global concentration is axis 4 (Comtrade trade flow).
Combining both gives a "domestic supplier diversity × global trade concentration"
view.
"""
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "supplier"
SNIPPETS_PATH = ROOT / "data" / "edinet" / "capacity_snippets_20260520.parquet"
MATERIALS_PATH = ROOT / "app" / "materials.yml"


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SNIPPETS_PATH.exists():
        print(f"Need {SNIPPETS_PATH} first (run ingest/edinet_capacity.py)")
        return
    if not MATERIALS_PATH.exists():
        print(f"Need {MATERIALS_PATH}")
        return

    materials = yaml.safe_load(MATERIALS_PATH.read_text())["materials"]
    fetched_at = datetime.now(timezone.utc).isoformat()

    con = duckdb.connect()
    con.execute(f"CREATE VIEW snip AS SELECT * FROM '{SNIPPETS_PATH}'")
    total_cos = con.execute("SELECT COUNT(DISTINCT company) FROM snip").fetchone()[0]
    print(f"Universe: {total_cos} JP-listed chemical-adjacent companies (snippet-containing subset)")

    rows = []
    for m in materials:
        keywords = m.get("capacity_keywords", [])
        if not keywords:
            continue
        like = " OR ".join(["snippet LIKE ?"] * len(keywords))
        params = [f"%{k}%" for k in keywords]
        cos = con.execute(
            f"SELECT DISTINCT company FROM snip WHERE {like}", params
        ).df()["company"].tolist()
        n = len(cos)
        snip_total = con.execute(
            f"SELECT COUNT(*) FROM snip WHERE {like}", params
        ).fetchone()[0]
        # 3-tier concentration band (rough heuristic for chemicals universe ~440 companies)
        if n == 0:
            band = "no_data"
        elif n <= 3:
            band = "high_concentration"  # few suppliers → high concentration risk
        elif n <= 10:
            band = "moderate_concentration"
        else:
            band = "low_concentration"  # many alt suppliers
        rows.append({
            "material_id": m["id"],
            "name_ja": m["name_ja"],
            "name_en": m["name_en"],
            "category": m["category"],
            "jp_supplier_count": n,
            "snippet_total": snip_total,
            "concentration_band": band,
            "top_companies": ", ".join(cos[:5]),
            "_fetched_at": fetched_at,
        })

    df = pd.DataFrame(rows)
    stamp = datetime.now().strftime("%Y%m%d")
    out = DATA_DIR / f"jp_supplier_count_{stamp}.parquet"
    df.to_parquet(out, index=False)
    print(f"\nWrote {len(df)} materials to {out}")
    print("\nBy concentration band:")
    print(df["concentration_band"].value_counts())
    print("\nMaterials with high domestic concentration risk (<=3 JP suppliers):")
    print(df[df["concentration_band"] == "high_concentration"][["name_ja", "jp_supplier_count", "top_companies"]].to_string(index=False))


if __name__ == "__main__":
    main()
