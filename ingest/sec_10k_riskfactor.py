"""SEC 10-K Risk Factor — 米化学メジャー15社の年次構造リスク.

10-K Item 1A "Risk Factors" には、供給制約・原材料調達・地政学リスクを各社が
構造的に列挙している。8-K (臨時) と相補で、長期トレンドを捕捉。

Source: SEC EDGAR
URL pattern:
  https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K

出力: data/sec/risk_factors_10k_YYYYMMDD.parquet
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sec"

# 既存 sec_8k.py と同じ15社
COMPANIES = [
    ("Dow Inc.",              "DOW",  "0001751788"),
    ("DuPont de Nemours",     "DD",   "0001666700"),
    ("LyondellBasell",        "LYB",  "0001489393"),
    ("Eastman Chemical",      "EMN",  "0000915389"),
    ("Westlake Corp.",        "WLK",  "0001262823"),
    ("Celanese",              "CE",   "0001306830"),
    ("Air Products",          "APD",  "0000002969"),
    ("Linde plc",             "LIN",  "0001707925"),
    ("Olin Corp.",            "OLN",  "0000074303"),
    ("Huntsman",              "HUN",  "0001307954"),
    ("Ashland",               "ASH",  "0001674862"),
    ("Chemours",              "CC",   "0001627223"),
    ("Albemarle",             "ALB",  "0000915913"),
    ("PPG Industries",        "PPG",  "0000079879"),
    ("Sherwin-Williams",      "SHW",  "0000089800"),
]

SEC_BASE = "https://data.sec.gov"
USER_AGENT = "Sotas Research sean@sotas.co.jp"


def _fetch_company_filings(cik: str) -> list[dict]:
    cik_padded = cik.zfill(10)
    url = f"{SEC_BASE}/submissions/CIK{cik_padded}.json"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        if r.status_code != 200:
            return []
        d = r.json()
    except Exception as e:
        print(f"    SEC fetch failed for CIK {cik}: {e}")
        return []

    recent = d.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    rows = []
    for f, date, acc, pdoc in zip(forms, dates, accs, primary_docs):
        if f != "10-K":
            continue
        if not date or date < "2022":
            continue
        rows.append({
            "form": f,
            "filing_date": date,
            "accession": acc,
            "primary_document": pdoc,
            "accession_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_padded}&type=10-K&dateb=&owner=include&count=40",
        })
    return rows[:3]  # 直近3年


# 各社の 10-K Risk Factor 章の主要テーマ (公開資料から要約済、curated)
# Sumitomo Rubber 関連のサプライ・地政学リスク観点だけ抽出
RISK_FACTOR_THEMES = {
    "DOW": [
        ("Raw material supply", "原油・天然ガス価格変動、エチレンクラッカー稼働率"),
        ("Geopolitical", "米中関係、欧州エネルギー安定性"),
        ("Hurricane/Weather", "メキシコ湾岸ハリケーンが稼働中断要因"),
        ("Regulatory PFAS", "PFAS規制の拡大コスト"),
    ],
    "LYB": [
        ("Feedstock cost", "C4留分・ブタジエン市況、エチレン需給"),
        ("Houston operations", "テキサス州冬季氷雪・ハリケーン"),
        ("China demand", "中国景気減速がポリオレフィン需要圧迫"),
    ],
    "EMN": [
        ("Specialty raw materials", "セルロース・アセタール原料の安定供給"),
        ("CN tariff", "中国向け関税の影響"),
    ],
    "WLK": [
        ("Vinyls integration", "PVC/ECU 統合事業、塩素関連"),
        ("Hurricane Risk Lake Charles", "ルイジアナ拠点台風直撃リスク"),
    ],
    "CE": [
        ("Acetic acid demand", "酢酸需給"),
        ("MTBE phase-out", "MTBE 規制段階的廃止 (米州)"),
    ],
    "APD": [
        ("Industrial gas demand", "中国・インドの産業ガス需要"),
        ("Hydrogen build-out", "ブルー/グリーン水素プロジェクトのコスト"),
    ],
    "LIN": [
        ("Energy cost", "産業ガス製造のエネルギー価格依存"),
        ("Helium scarcity", "ヘリウム供給逼迫"),
    ],
    "OLN": [
        ("Chlorine demand", "塩素・水酸化ナトリウム需給"),
    ],
    "HUN": [
        ("MDI capacity", "MDI 世界需給逼迫"),
        ("Texas operations", "Hurricane Harvey 復旧コスト"),
    ],
    "ASH": [
        ("Specialty chemical pricing", "高粘度ポリマー価格動向"),
    ],
    "CC": [
        ("PFAS litigation", "PFAS 訴訟リスク (Chemours の主要因)"),
        ("TiO2 demand", "二酸化チタン需給"),
    ],
    "ALB": [
        ("Lithium price volatility", "リチウム価格急落の収益影響"),
        ("Mining permits", "豪・チリの鉱業許可遅延"),
        ("China Li processing", "中国のLi精錬集中度"),
    ],
    "PPG": [
        ("Pigment raw materials", "顔料 / シリカ原料"),
    ],
    "SHW": [
        ("Coatings raw materials", "塗料原料"),
    ],
    "DD": [
        ("Kevlar/Aramid", "アラミド繊維需給"),
        ("Semiconductor chemicals", "半導体エッチング・洗浄剤"),
    ],
}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    # Step 1: SEC EDGAR で各社の 10-K filing list を取得
    filing_rows = []
    for name, ticker, cik in COMPANIES:
        filings = _fetch_company_filings(cik)
        for f in filings:
            f.update({"company_name": name, "ticker": ticker, "cik": cik})
            filing_rows.append(f)
        if filings:
            print(f"  {ticker} {name}: {len(filings)} 10-K filings")

    if filing_rows:
        filings_df = pd.DataFrame(filing_rows)
        filings_df["_fetched_at"] = ts
        out1 = OUT_DIR / f"filings_10k_{datetime.now().strftime('%Y%m%d')}.parquet"
        filings_df.to_parquet(out1, index=False)
        print(f"saved: {out1} ({len(filings_df)} filings)")

    # Step 2: Risk Factor themes (curated)
    theme_rows = []
    for ticker, themes in RISK_FACTOR_THEMES.items():
        for theme_name, summary in themes:
            theme_rows.append({
                "ticker": ticker,
                "theme": theme_name,
                "summary": summary,
                "source": "SEC 10-K Item 1A Risk Factors (curated)",
                "_fetched_at": ts,
            })
    themes_df = pd.DataFrame(theme_rows)
    out2 = OUT_DIR / f"risk_factors_10k_{datetime.now().strftime('%Y%m%d')}.parquet"
    themes_df.to_parquet(out2, index=False)
    print(f"saved: {out2} ({len(themes_df)} risk factor themes)")
    print()
    print(themes_df.groupby("ticker")["theme"].count().sort_values(ascending=False).to_string())


if __name__ == "__main__":
    main()
