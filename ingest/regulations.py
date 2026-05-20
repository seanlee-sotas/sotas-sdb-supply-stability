"""Other regulation lists for axis 5:
- METI 特定重要物資 (Economic Security Promotion Act, designated items)
- Stockholm Convention POPs (Annex A/B/C)

These are small and stable lists; hardcoded with source URLs for traceability.
Larger dynamic regulation feeds (US TSCA active risk evaluation, EU PFAS Restriction)
require periodic scraping and will be added in separate ingest scripts.
"""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "regulations"

# METI 特定重要物資 (Critical Materials under 経済安全保障推進法)
# Source: https://www.meti.go.jp/policy/economy/economic_security/
# Initial 11 items designated 2022-12-26 cabinet decision, additional items added since.
# This list reflects 2026-04 status.
METI_CRITICAL = [
    {"id": "JP-CRIT-01", "name_ja": "半導体", "name_en": "Semiconductors", "designated_date": "2022-12-26", "category": "electronics"},
    {"id": "JP-CRIT-02", "name_ja": "クラウドプログラム", "name_en": "Cloud programs", "designated_date": "2022-12-26", "category": "software"},
    {"id": "JP-CRIT-03", "name_ja": "永久磁石", "name_en": "Permanent magnets", "designated_date": "2022-12-26", "category": "materials"},
    {"id": "JP-CRIT-04", "name_ja": "工作機械・産業用ロボット", "name_en": "Machine tools / Industrial robots", "designated_date": "2022-12-26", "category": "equipment"},
    {"id": "JP-CRIT-05", "name_ja": "重要鉱物", "name_en": "Critical minerals", "designated_date": "2022-12-26", "category": "raw_materials"},
    {"id": "JP-CRIT-06", "name_ja": "蓄電池", "name_en": "Batteries", "designated_date": "2022-12-26", "category": "energy"},
    {"id": "JP-CRIT-07", "name_ja": "抗菌性物質製剤", "name_en": "Antibacterial pharmaceutical preparations", "designated_date": "2022-12-26", "category": "pharma"},
    {"id": "JP-CRIT-08", "name_ja": "肥料", "name_en": "Fertilizers", "designated_date": "2022-12-26", "category": "chemicals"},
    {"id": "JP-CRIT-09", "name_ja": "天然ガス", "name_en": "Natural gas", "designated_date": "2022-12-26", "category": "energy"},
    {"id": "JP-CRIT-10", "name_ja": "船舶の部品", "name_en": "Ship components", "designated_date": "2022-12-26", "category": "transportation"},
    {"id": "JP-CRIT-11", "name_ja": "航空機の部品", "name_en": "Aircraft components", "designated_date": "2022-12-26", "category": "transportation"},
    {"id": "JP-CRIT-12", "name_ja": "先端電子部品", "name_en": "Advanced electronic components", "designated_date": "2023-12-22", "category": "electronics"},
]

# Stockholm Convention POPs (Persistent Organic Pollutants)
# Source: https://chm.pops.int/TheConvention/ThePOPs/ListingofPOPs/tabid/2509/Default.aspx
# Annex A = Elimination, Annex B = Restriction, Annex C = Unintentional production
# Snapshot as of 2026 (most recent COP). Update on each COP (every 2 years).
POPS = [
    # Annex A — Elimination
    {"id": "POPS-A-01", "name_en": "Aldrin", "annex": "A", "cas": "309-00-2", "type": "pesticide"},
    {"id": "POPS-A-02", "name_en": "Chlordane", "annex": "A", "cas": "57-74-9", "type": "pesticide"},
    {"id": "POPS-A-03", "name_en": "Dieldrin", "annex": "A", "cas": "60-57-1", "type": "pesticide"},
    {"id": "POPS-A-04", "name_en": "Endrin", "annex": "A", "cas": "72-20-8", "type": "pesticide"},
    {"id": "POPS-A-05", "name_en": "Heptachlor", "annex": "A", "cas": "76-44-8", "type": "pesticide"},
    {"id": "POPS-A-06", "name_en": "Hexachlorobenzene (HCB)", "annex": "A,C", "cas": "118-74-1", "type": "industrial"},
    {"id": "POPS-A-07", "name_en": "Mirex", "annex": "A", "cas": "2385-85-5", "type": "pesticide"},
    {"id": "POPS-A-08", "name_en": "Toxaphene", "annex": "A", "cas": "8001-35-2", "type": "pesticide"},
    {"id": "POPS-A-09", "name_en": "Polychlorinated biphenyls (PCB)", "annex": "A,C", "cas": "1336-36-3", "type": "industrial"},
    {"id": "POPS-A-10", "name_en": "Chlordecone", "annex": "A", "cas": "143-50-0", "type": "pesticide"},
    {"id": "POPS-A-11", "name_en": "Hexabromobiphenyl", "annex": "A", "cas": "36355-01-8", "type": "industrial"},
    {"id": "POPS-A-12", "name_en": "Hexabromodiphenyl ether and Heptabromodiphenyl ether", "annex": "A", "cas": "68631-49-2", "type": "industrial"},
    {"id": "POPS-A-13", "name_en": "Tetrabromodiphenyl ether and Pentabromodiphenyl ether", "annex": "A", "cas": "5436-43-1", "type": "industrial"},
    {"id": "POPS-A-14", "name_en": "alpha-Hexachlorocyclohexane", "annex": "A", "cas": "319-84-6", "type": "pesticide_byproduct"},
    {"id": "POPS-A-15", "name_en": "beta-Hexachlorocyclohexane", "annex": "A", "cas": "319-85-7", "type": "pesticide_byproduct"},
    {"id": "POPS-A-16", "name_en": "Lindane (gamma-HCH)", "annex": "A", "cas": "58-89-9", "type": "pesticide"},
    {"id": "POPS-A-17", "name_en": "Pentachlorobenzene", "annex": "A,C", "cas": "608-93-5", "type": "industrial"},
    {"id": "POPS-A-18", "name_en": "Endosulfan and isomers", "annex": "A", "cas": "115-29-7", "type": "pesticide"},
    {"id": "POPS-A-19", "name_en": "Hexabromocyclododecane (HBCD)", "annex": "A", "cas": "25637-99-4", "type": "industrial"},
    {"id": "POPS-A-20", "name_en": "Hexachlorobutadiene", "annex": "A,C", "cas": "87-68-3", "type": "industrial"},
    {"id": "POPS-A-21", "name_en": "Polychlorinated naphthalenes", "annex": "A,C", "cas": "70776-03-3", "type": "industrial"},
    {"id": "POPS-A-22", "name_en": "Pentachlorophenol and its salts", "annex": "A", "cas": "87-86-5", "type": "industrial"},
    {"id": "POPS-A-23", "name_en": "Decabromodiphenyl ether (decaBDE)", "annex": "A", "cas": "1163-19-5", "type": "industrial"},
    {"id": "POPS-A-24", "name_en": "Short-chain chlorinated paraffins (SCCPs)", "annex": "A", "cas": "85535-84-8", "type": "industrial"},
    {"id": "POPS-A-25", "name_en": "Dicofol", "annex": "A", "cas": "115-32-2", "type": "pesticide"},
    {"id": "POPS-A-26", "name_en": "Perfluorooctanoic acid (PFOA), its salts and PFOA-related compounds", "annex": "A", "cas": "335-67-1", "type": "industrial"},
    {"id": "POPS-A-27", "name_en": "Perfluorohexane sulfonic acid (PFHxS), its salts and PFHxS-related compounds", "annex": "A", "cas": "355-46-4", "type": "industrial"},
    {"id": "POPS-A-28", "name_en": "Dechlorane Plus, its syn- and anti-isomers", "annex": "A", "cas": "13560-89-9", "type": "industrial"},
    {"id": "POPS-A-29", "name_en": "Methoxychlor", "annex": "A", "cas": "72-43-5", "type": "pesticide"},
    {"id": "POPS-A-30", "name_en": "UV-328", "annex": "A", "cas": "25973-55-1", "type": "industrial"},
    {"id": "POPS-A-31", "name_en": "Long-chain perfluorocarboxylic acids (LC-PFCAs)", "annex": "A", "cas": "335-76-2", "type": "industrial"},
    {"id": "POPS-A-32", "name_en": "Chlorpyrifos", "annex": "A", "cas": "2921-88-2", "type": "pesticide"},
    {"id": "POPS-A-33", "name_en": "Medium-chain chlorinated paraffins (MCCPs)", "annex": "A", "cas": "85535-85-9", "type": "industrial"},
    # Annex B — Restriction
    {"id": "POPS-B-01", "name_en": "DDT", "annex": "B", "cas": "50-29-3", "type": "pesticide"},
    {"id": "POPS-B-02", "name_en": "Perfluorooctane sulfonic acid (PFOS), its salts and PFOSF", "annex": "B", "cas": "1763-23-1", "type": "industrial"},
    # Annex C — Unintentional production only
    {"id": "POPS-C-01", "name_en": "Polychlorinated dibenzo-p-dioxins (PCDD)", "annex": "C", "cas": "1746-01-6", "type": "byproduct"},
    {"id": "POPS-C-02", "name_en": "Polychlorinated dibenzofurans (PCDF)", "annex": "C", "cas": "5120-73-0", "type": "byproduct"},
]


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()

    meti = pd.DataFrame(METI_CRITICAL)
    meti["_source"] = "METI 特定重要物資 (経済安全保障推進法)"
    meti["_source_url"] = "https://www.meti.go.jp/policy/economy/economic_security/"
    meti["_fetched_at"] = fetched_at
    stamp = datetime.now().strftime("%Y%m%d")
    meti_path = DATA_DIR / f"meti_critical_{stamp}.parquet"
    meti.to_parquet(meti_path, index=False)
    print(f"Wrote {len(meti)} METI critical items to {meti_path}")

    pops = pd.DataFrame(POPS)
    pops["_source"] = "Stockholm Convention POPs (Annex A/B/C)"
    pops["_source_url"] = "https://chm.pops.int/TheConvention/ThePOPs/ListingofPOPs/"
    pops["_fetched_at"] = fetched_at
    pops_path = DATA_DIR / f"pops_{stamp}.parquet"
    pops.to_parquet(pops_path, index=False)
    print(f"Wrote {len(pops)} POPs entries to {pops_path}")
    print("\nPOPs by annex:")
    print(pops.groupby("annex").size())


if __name__ == "__main__":
    main()
