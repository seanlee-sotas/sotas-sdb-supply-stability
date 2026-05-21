"""Build chemicals_company_map.parquet from manufacturer_seed.py.

Resolves JP company names → edinet_code, KR company names → corp_code by
matching against companies.json files.
TW tickers and US tickers are passed through (no resolution needed).
"""
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def normalize(s: str) -> str:
    """NFKC normalize → strip → lowercase. Maps full-width ↔ half-width and
    common typographic chars to a canonical form for cross-encoding lookup."""
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip().lower()


# Explicit aliases for companies that have multiple common names or are subsidiaries
# of listed parents — maps alias → canonical name in companies.json
JP_ALIASES = {
    "旭硝子": "ＡＧＣ",
    "agc": "ＡＧＣ",
    "AGC": "ＡＧＣ",
    "eneos": "ＥＮＥＯＳホールディングス",
    "ENEOS": "ＥＮＥＯＳホールディングス",
    "dic": "ＤＩＣ",
    "DIC": "ＤＩＣ",
    "adeka": "ＡＤＥＫＡ",
    "ADEKA": "ＡＤＥＫＡ",
    "ube": "ＵＢＥ",
    "宇部": "ＵＢＥ",
    "UBE": "ＵＢＥ",
    "tokyo ohka": "東京応化工業",
    "JX金属": "JX金属",  # newly listed 2025; may not be in old companies.json
    # Subsidiaries → parents (loose mapping for event proxy)
    "丸善石油化学": "コスモエネルギーホールディングス",
    "プライムポリマー": "三井化学",
    "宇部丸善ポリエチレン": "ＵＢＥ",
    "日本ポリエチレン": "三菱ケミカルグループ",
    "日本ポリプロ": "三菱ケミカルグループ",
    "サンアロマー": "三井化学",
    "PSジャパン": "出光興産",
    "東洋スチレン": "出光興産",
    "新日本理化": "三菱商事ケミカル",
    "ポリプラスチックス": "ダイセル",
    "ベルポリエステルプロダクツ": "三菱ケミカルグループ",
    "ウィンテックポリマー": "三菱ケミカルグループ",
    "ダイセル・エボニック": "ダイセル",
    "三井・ケマーズフロロプロダクツ": "三井化学",
    "BASF INOAC ポリウレタン": "井上ゴム工業",
    "三井・デュポンポリケミカル": "三井化学",
    "新日鉄住金化学": "日本製鉄",
    "錦湖三井化学": "三井化学",
    "東ソー・シリカ": "東ソー",
    "新第一塩ビ": "東ソー",
    "大洋塩ビ": "東ソー",
    "テクノポリマー": "三井化学",
    "UMG ABS": "三井化学",
    "日本オキシラン": "出光興産",
    "AGC旭硝子": "ＡＧＣ",
    "昭和電工マテリアルズ": "レゾナック・ホールディングス",
    "レゾナック": "レゾナック・ホールディングス",
    "クラリアント": "クラリアントジャパン",
    "BASFジャパン": "ＢＡＳＦジャパン",
    "三菱ガス化学": "三菱瓦斯化学",
    "三菱マテリアル": "三菱マテリアル",
    "日本シリカ工業": "日本軽金属ホールディングス",
    "東邦化学工業": "東邦化学工業",
    "大阪ガスケミカル": "大阪ガス",
    "クラレ": "クラレ",
    "宇部マテリアルズ": "ＵＢＥ",
    "日本軽金属": "日本軽金属ホールディングス",
    "豊田通商": "豊田通商",
    "本荘ケミカル": "本荘ケミカル",
    "日本電工": "日本電工",
    "山陽色素": "山陽色素",
    "城北化学工業": "城北化学工業",
    "本州化学工業": "本州化学工業",
    "三井金属鉱業": "三井金属",
    "DOWAホールディングス": "ＤＯＷＡホールディングス",
    "ステラケミファ": "ステラケミファ",
    "森田化学工業": "森田化学工業",
    "セントラル硝子": "セントラル硝子",
    "三洋化成工業": "三洋化成工業",
    "第一工業製薬": "第一工業製薬",
    "東邦亜鉛": "東邦亜鉛",
    "ENEOSホールディングス": "ＥＮＥＯＳホールディングス",
    "ＥＮＥＯＳ": "ＥＮＥＯＳホールディングス",
    "出光興産": "出光興産",
    "ダイキン工業": "ダイキン工業",
    # Some are simply unlisted private — accept missing
}

KR_ALIASES = {
    "여천NCC": "여천엔씨씨",  # may not be in companies.json
    "한화토탈에너지스": "한화솔루션",
    "SK지오센트릭": "SK이노베이션",
    "錦湖P&B化学": "금호석유화학",
    "錦湖石油化学": "금호석유화학",
    "고려아연": "고려아연",
    "엘앤에프": "엘앤에프",
    "에코프로비엠": "에코프로비엠",
    "포스코퓨처엠": "포스코퓨처엠",
    "엔켐": "엔켐",
    "솔브레인": "솔브레인",
    "후성": "후성",
    "Foosung": "후성",
    "SK머티리얼즈": "에스케이머티리얼즈",
    "효성": "효성",
    "천보": "천보",
    "풍산": "풍산",
    "한국이네오스스타이롤루션": "한국이네오스스타이롤루션",
    "휴비스": "휴비스",
    "三養化成": "삼양사",
    "LG MMA": "LG화학",
    "錦湖三井化学": "금호석유화학",
    "錦湖P&B化学": "금호석유화학",
    "錦湖石油化学": "금호석유화학",
    "한화솔루션": "한화솔루션",
    "효성첨단소재": "효성첨단소재",
    "코오롱인더스트리": "코오롱인더스트리",
    "한화토탈에너지스": "한화솔루션",
    "한라테크그룹": "한라홀딩스",
    "SK이노베이션": "SK이노베이션",
    "SKC": "SKC",
    "KEP": "코오롱플라스틱",
    "SK케미칼": "SK케미칼",
    "KCC": "KCC",
    "애경케미칼": "애경케미칼",
    "OCI": "OCI",
}

ROOT = Path(__file__).resolve().parents[2]
VAULT = Path("/Users/seanlee/My Drive (sean.lee@sotas.co.jp)/Vault")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manufacturer_seed import MANUFACTURERS  # noqa: E402

OUT_PATH = ROOT / "data" / "chemicals" / "chemicals_company_map.parquet"
UNRESOLVED_PATH = ROOT / "data" / "chemicals" / "chemicals_company_map_unresolved.txt"


def load_jp_lookup() -> dict[str, str]:
    """normalize(name) → edinet_code."""
    p = VAULT / "_scripts" / "research-company" / "jp" / "companies.json"
    if not p.exists():
        return {}
    companies = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for c in companies:
        code = c.get("edinet_code")
        if not code:
            continue
        for key in ("name", "name_full", "name_short", "name_en"):
            v = c.get(key)
            if v:
                nk = normalize(v)
                if nk and nk not in out:
                    out[nk] = code
    return out


def load_kr_lookup() -> dict[str, str]:
    p = VAULT / "_scripts" / "research-company" / "kr" / "companies.json"
    if not p.exists():
        return {}
    companies = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for c in companies:
        code = c.get("corp_code")
        if not code:
            continue
        for key in ("name", "name_full", "name_en"):
            v = c.get(key)
            if v:
                nk = normalize(v)
                if nk and nk not in out:
                    out[nk] = code
    return out


def resolve_jp(name: str, lkp: dict[str, str]) -> str | None:
    """Try direct match → alias → normalized match."""
    if not name:
        return None
    # Direct
    nk = normalize(name)
    if nk in lkp:
        return lkp[nk]
    # Try alias
    canon = JP_ALIASES.get(name) or JP_ALIASES.get(nk)
    if canon:
        nk_canon = normalize(canon)
        if nk_canon in lkp:
            return lkp[nk_canon]
    return None


def resolve_kr(name: str, lkp: dict[str, str]) -> str | None:
    if not name:
        return None
    nk = normalize(name)
    if nk in lkp:
        return lkp[nk]
    canon = KR_ALIASES.get(name) or KR_ALIASES.get(nk)
    if canon:
        nk_canon = normalize(canon)
        if nk_canon in lkp:
            return lkp[nk_canon]
    return None


def main():
    jp_lkp = load_jp_lookup()
    kr_lkp = load_kr_lookup()
    print(f"JP names indexed: {len(jp_lkp)}")
    print(f"KR names indexed: {len(kr_lkp)}")

    # Resolve names → codes; track unresolved for visibility
    unresolved_jp: dict[str, list[str]] = {}  # cas → list of names we couldn't match
    unresolved_kr: dict[str, list[str]] = {}

    chems_p = ROOT / "data" / "chemicals" / "chemicals.parquet"
    chem_df = pd.read_parquet(chems_p)
    chem_meta = chem_df.set_index("cas").to_dict(orient="index")

    rows = []
    for cas, data in MANUFACTURERS.items():
        if "/" in cas:  # placeholder rows
            continue
        meta = chem_meta.get(cas, {})
        jp_codes: list[str] = []
        for jp_name in data.get("jp") or []:
            code = resolve_jp(jp_name, jp_lkp)
            if code and code not in jp_codes:
                jp_codes.append(code)
            elif not code:
                unresolved_jp.setdefault(cas, []).append(jp_name)
        kr_codes: list[str] = []
        for kr_name in data.get("kr") or []:
            code = resolve_kr(kr_name, kr_lkp)
            if code and code not in kr_codes:
                kr_codes.append(code)
            elif not code:
                unresolved_kr.setdefault(cas, []).append(kr_name)
        rows.append({
            "cas": cas,
            "name_en": meta.get("name_en") or "",
            "category_norm": meta.get("category_norm") or "",
            "us_tickers": data.get("us") or [],
            "jp_edinet_codes": jp_codes,
            "kr_corp_codes": kr_codes,
            "tw_tickers": data.get("tw") or [],
            "jp_names_seed": data.get("jp") or [],
            "kr_names_seed": data.get("kr") or [],
            "_built_at": datetime.now(timezone.utc).isoformat(),
        })

    out_df = pd.DataFrame(rows)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_parquet(OUT_PATH, index=False)
    print(f"\nWrote {len(out_df)} mapped CAS → {OUT_PATH}")

    # Coverage stats
    n_us = (out_df["us_tickers"].str.len() > 0).sum()
    n_jp = (out_df["jp_edinet_codes"].str.len() > 0).sum()
    n_kr = (out_df["kr_corp_codes"].str.len() > 0).sum()
    n_tw = (out_df["tw_tickers"].str.len() > 0).sum()
    print(f"\nCoverage: US {n_us} / JP {n_jp} / KR {n_kr} / TW {n_tw}")

    # Write unresolved for follow-up
    with UNRESOLVED_PATH.open("w", encoding="utf-8") as f:
        f.write("# Unresolved company names — add to companies.json or fix spelling\n")
        f.write(f"\n## JP unresolved ({sum(len(v) for v in unresolved_jp.values())} refs across {len(unresolved_jp)} CAS)\n\n")
        from collections import Counter
        jp_freq = Counter()
        for names in unresolved_jp.values():
            for n in names:
                jp_freq[n] += 1
        for name, cnt in jp_freq.most_common():
            f.write(f"  - {name} (×{cnt})\n")
        f.write(f"\n## KR unresolved ({sum(len(v) for v in unresolved_kr.values())} refs across {len(unresolved_kr)} CAS)\n\n")
        kr_freq = Counter()
        for names in unresolved_kr.values():
            for n in names:
                kr_freq[n] += 1
        for name, cnt in kr_freq.most_common():
            f.write(f"  - {name} (×{cnt})\n")
    print(f"Wrote unresolved companies → {UNRESOLVED_PATH}")


if __name__ == "__main__":
    main()
