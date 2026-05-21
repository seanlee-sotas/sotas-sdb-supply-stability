"""Chemical → manufacturer mapping seed (Claude knowledge-based).

This is a curated mapping of CAS → {US tickers, JP company names, KR company names,
TW tickers} for chemicals where Claude has high-confidence knowledge of major
publicly-traded global manufacturers across the 4 covered markets.

Coverage notes:
- Pinned 17 + major monomers/polymers/rubber/battery/semiconductor = ~130 chemicals
- Remaining 339 chemicals (mostly regulated POPs/SVHCs that lack active named producers,
  or very specialty fine chemicals) are left empty — phase 2 work
- JP/KR company NAMES (not edinet/corp codes) are written; resolver step downstream
  matches them against companies.json to get the codes
- TW companies are written as 4-digit tickers since we don't have a TW companies.json yet
- CN is not covered (no companies dataset)
"""

# Naming conventions:
#   us: US tickers (SEC EDGAR)
#   jp: JP company names matching companies.json 'name' field exactly
#   kr: KR company names matching kr/companies.json 'name' field exactly (Korean)
#   tw: TW 4-digit tickers (TWSE/TPEX)

MANUFACTURERS: dict[str, dict] = {
    # ==================== Pinned 17 ====================
    "74-85-1": {  # Ethylene
        "us": ["DOW", "LYB", "EMN", "WLK", "CE"],
        "jp": ["三菱ケミカルグループ", "三井化学", "住友化学", "丸善石油化学", "出光興産", "ENEOS", "東ソー"],
        "kr": ["LG화학", "롯데케미칼", "한화솔루션", "여천NCC", "대한유화", "SK지오센트릭"],
        "tw": ["1303", "1326", "1314"],  # 南亞, 台塑化, 中石化
    },
    "115-07-1": {  # Propylene
        "us": ["DOW", "LYB", "EMN", "WLK"],
        "jp": ["三菱ケミカルグループ", "三井化学", "住友化学", "丸善石油化学", "出光興産", "ENEOS"],
        "kr": ["LG화학", "롯데케미칼", "여천NCC", "대한유화"],
        "tw": ["1303", "1326"],
    },
    "106-99-0": {  # 1,3-Butadiene
        "us": ["LYB", "DOW", "EMN", "TSE"],
        "jp": ["JSR", "日本ゼオン", "宇部", "ＵＢＥ", "ENEOS", "丸善石油化学", "クラレ"],
        "kr": ["LG화학", "롯데케미칼", "금호석유화학", "SK지오센트릭"],
        "tw": ["1303", "1326"],
    },
    "100-42-5": {  # Styrene
        "us": ["LYB", "DOW", "INEOS", "WLK", "TSE"],
        "jp": ["日本オキシラン", "出光興産", "東洋スチレン", "ENEOS", "PSジャパン"],
        "kr": ["LG화학", "한화토탈에너지스", "여천NCC", "SK이노베이션"],
        "tw": ["1303", "1326", "1714"],  # 三晃
    },
    "9006-04-6": {  # Natural Rubber
        "us": [],
        "jp": ["ブリヂストン", "住友ゴム工業", "横浜ゴム"],  # not producers but huge buyers
        "kr": [],
        "tw": [],
    },
    "9003-55-8": {  # SBR
        "us": ["LYB", "TSE", "GDYN"],
        "jp": ["JSR", "日本ゼオン", "旭化成", "住友化学"],
        "kr": ["LG화학", "금호석유화학", "한화솔루션"],
        "tw": ["1312", "1305"],  # 國喬, 華夏
    },
    "9003-17-2": {  # BR (polybutadiene)
        "us": ["TSE", "LYB"],
        "jp": ["JSR", "日本ゼオン", "宇部", "ＵＢＥ", "旭化成", "三菱ケミカルグループ"],
        "kr": ["LG화학", "금호석유화학"],
        "tw": ["1312"],
    },
    "9003-18-3": {  # NBR (nitrile rubber)
        "us": ["TSE"],
        "jp": ["JSR", "日本ゼオン", "日本エヌエスシー", "住友化学"],
        "kr": ["LG화학", "금호석유화학"],
        "tw": [],
    },
    "1333-86-4": {  # Carbon black
        "us": ["CBT", "OEC"],
        "jp": ["東海カーボン", "旭カーボン", "三菱ケミカルグループ", "デンカ"],
        "kr": ["OCI", "금호석유화학"],
        "tw": ["1723"],  # 中興電
    },
    "7631-86-9": {  # Silica
        "us": ["EMN", "PPG", "GLW"],
        "jp": ["東ソー・シリカ", "東ソー", "日本シリカ工業", "AGC", "AGC旭硝子"],
        "kr": ["KCC"],
        "tw": [],
    },
    "9002-86-2": {  # PVC
        "us": ["WLK", "OLN", "FMC"],
        "jp": ["信越化学工業", "東ソー", "カネカ", "新第一塩ビ", "大洋塩ビ"],
        "kr": ["LG화학", "한화솔루션"],
        "tw": ["1301", "1303"],  # 台塑, 南亞
    },
    "9002-88-4": {  # PE
        "us": ["DOW", "LYB", "EMN", "WLK", "CE"],
        "jp": ["プライムポリマー", "三井化学", "宇部丸善ポリエチレン", "日本ポリエチレン", "三菱ケミカルグループ", "東ソー"],
        "kr": ["LG화학", "롯데케미칼", "한화솔루션", "SK지오센트릭"],
        "tw": ["1303", "1301"],
    },
    "9003-07-0": {  # PP
        "us": ["DOW", "LYB", "EMN", "WLK"],
        "jp": ["プライムポリマー", "サンアロマー", "日本ポリプロ", "三井化学", "出光興産"],
        "kr": ["LG화학", "롯데케미칼", "한화토탈에너지스", "SK지오센트릭"],
        "tw": ["1301", "1303", "1314"],
    },
    "63148-62-9": {  # PDMS (silicone)
        "us": ["DOW", "MMM"],
        "jp": ["信越化学工業", "モメンティブ"],
        "kr": ["KCC"],
        "tw": [],
    },
    "26780-96-1": {  # TMQ antioxidant
        "us": ["TSE", "LXS"],
        "jp": ["大内新興化学工業", "川口化学工業"],
        "kr": [],
        "tw": [],
    },

    # ==================== Monomers ====================
    "75-07-0": {  # Acetaldehyde
        "us": ["EMN", "CE"],
        "jp": ["昭和電工マテリアルズ", "レゾナック・ホールディングス", "ダイセル"],
        "kr": ["LG화학"],
        "tw": [],
    },
    "67-64-1": {  # Acetone
        "us": ["INEOS", "OXY", "DOW"],
        "jp": ["三井化学", "三菱ケミカルグループ", "出光興産"],
        "kr": ["LG화학", "금호석유화학", "錦湖P&B化学"],
        "tw": ["1303"],
    },
    "79-10-7": {  # Acrylic acid
        "us": ["DOW", "BASF"],
        "jp": ["日本触媒", "三菱ケミカルグループ", "東亞合成"],
        "kr": ["LG화학"],
        "tw": ["1722", "1304"],
    },
    "107-13-1": {  # Acrylonitrile
        "us": ["INEOS"],
        "jp": ["旭化成", "三井化学", "住友化学"],
        "kr": ["LG화학"],
        "tw": ["1722"],  # 台肥
    },
    "71-43-2": {  # Benzene
        "us": ["DOW", "LYB", "CVX", "XOM"],
        "jp": ["三菱ケミカルグループ", "三井化学", "住友化学", "出光興産", "ENEOS"],
        "kr": ["LG화학", "여천NCC", "SK이노베이션"],
        "tw": ["1303", "1314"],
    },
    "100-41-4": {  # Ethylbenzene
        "us": ["LYB", "DOW", "INEOS"],
        "jp": ["出光興産", "東洋スチレン"],
        "kr": ["LG화학"],
        "tw": ["1303"],
    },
    "108-88-3": {  # Toluene
        "us": ["DOW", "LYB", "XOM"],
        "jp": ["三井化学", "ENEOS", "出光興産"],
        "kr": ["LG화학", "SK이노베이션"],
        "tw": ["1303", "1314"],
    },
    "1330-20-7": {  # Xylene (mixed)
        "us": ["XOM", "LYB"],
        "jp": ["三井化学", "ENEOS", "出光興産", "JX金属"],
        "kr": ["LG화학", "SK이노베이션"],
        "tw": ["1303", "1314"],
    },
    "108-95-2": {  # Phenol
        "us": ["INEOS", "OXY"],
        "jp": ["三井化学", "三菱ケミカルグループ"],
        "kr": ["LG화학", "금호석유화학", "錦湖P&B化学"],
        "tw": ["1303"],
    },
    "75-21-8": {  # Ethylene oxide
        "us": ["DOW", "LYB", "EMN", "INEOS"],
        "jp": ["三菱ケミカルグループ", "三井化学", "丸善石油化学", "日本触媒"],
        "kr": ["LG화학", "롯데케미칼"],
        "tw": ["1303"],
    },
    "107-21-1": {  # Ethylene glycol
        "us": ["DOW", "LYB", "EMN"],
        "jp": ["三菱ケミカルグループ", "三井化学", "日本触媒"],
        "kr": ["LG화학", "롯데케미칼"],
        "tw": ["1303", "1314"],
    },
    "75-56-9": {  # Propylene oxide
        "us": ["LYB", "DOW", "HUN"],
        "jp": ["旭硝子", "AGC", "住友化学", "三井化学"],
        "kr": ["SKC", "롯데케미칼"],
        "tw": [],
    },
    "57-55-6": {  # Propylene glycol
        "us": ["DOW", "LYB"],
        "jp": ["旭硝子", "AGC", "ADEKA"],
        "kr": ["SKC"],
        "tw": [],
    },
    "127-19-5": {  # DMAc
        "us": ["DOW"],
        "jp": ["三菱瓦斯化学"],
        "kr": [],
        "tw": [],
    },
    "68-12-2": {  # DMF
        "us": ["BASF"],
        "jp": ["三菱瓦斯化学", "三井化学"],
        "kr": [],
        "tw": [],
    },
    "872-50-4": {  # NMP
        "us": ["BASF", "EMN"],
        "jp": ["三菱ケミカルグループ", "三井化学", "丸善石油化学"],
        "kr": ["LG화학"],
        "tw": [],
    },
    "67-56-1": {  # Methanol
        "us": ["MEOH", "CE"],
        "jp": ["三菱ガス化学", "三菱瓦斯化学"],
        "kr": [],
        "tw": [],
    },
    "67-63-0": {  # Isopropanol
        "us": ["DOW", "INEOS", "EMN"],
        "jp": ["徳山", "トクヤマ", "三井化学"],
        "kr": ["LG화학"],
        "tw": ["1717"],  # 長興
    },
    "64-19-7": {  # Acetic acid
        "us": ["CE", "EMN"],
        "jp": ["昭和電工マテリアルズ", "レゾナック・ホールディングス", "ダイセル"],
        "kr": ["LG화학"],
        "tw": [],
    },
    "108-05-4": {  # Vinyl acetate
        "us": ["CE", "DOW", "WLK"],
        "jp": ["昭和電工マテリアルズ", "レゾナック・ホールディングス", "クラレ", "信越化学工業", "日本酢ビ・ポバール"],
        "kr": [],
        "tw": ["1314", "1717"],
    },
    "75-01-4": {  # Vinyl chloride
        "us": ["WLK", "OLN", "FMC"],
        "jp": ["信越化学工業", "東ソー", "カネカ"],
        "kr": ["LG화학", "한화솔루션"],
        "tw": ["1301", "1303"],
    },
    "108-31-6": {  # Maleic anhydride
        "us": ["LYB", "HUN"],
        "jp": ["日本触媒", "三菱ケミカルグループ"],
        "kr": ["LG화학"],
        "tw": ["1303"],
    },
    "85-44-9": {  # Phthalic anhydride
        "us": ["EMN", "EXX"],
        "jp": ["新日本理化", "ダイセル"],
        "kr": ["애경케미칼"],
        "tw": [],
    },
    "80-05-7": {  # Bisphenol A
        "us": ["DOW", "OXY", "HUN"],
        "jp": ["三井化学", "三菱ケミカルグループ", "新日鉄住金化学"],
        "kr": ["금호석유화학", "錦湖P&B化学", "LG화학"],
        "tw": ["1314", "1717"],
    },
    "121-44-8": {  # Triethylamine
        "us": ["DOW", "BASF"],
        "jp": ["広栄化学"],
        "kr": [],
        "tw": [],
    },
    "9016-87-9": {  # MDI
        "us": ["HUN", "BASF"],
        "jp": ["東ソー", "三井化学", "BASF INOAC ポリウレタン"],
        "kr": ["금호석유화학", "錦湖三井化学"],
        "tw": [],
    },
    "584-84-9": {  # TDI (2,4-)
        "us": ["HUN", "BASF"],
        "jp": ["三井化学", "東ソー"],
        "kr": ["한화솔루션", "錦湖三井化学"],
        "tw": [],
    },
    "78-79-5": {  # Isoprene
        "us": ["DOW"],
        "jp": ["JSR", "日本ゼオン", "クラレ"],
        "kr": ["LG화학"],
        "tw": [],
    },
    "115-11-7": {  # Isobutylene
        "us": ["LYB", "EMN", "DOW"],
        "jp": ["JX金属", "ENEOS", "三井化学"],
        "kr": ["LG화학"],
        "tw": [],
    },

    # ==================== Polymers ====================
    "9003-53-6": {  # Polystyrene (PS)
        "us": ["DOW", "TSE", "WLK"],
        "jp": ["PSジャパン", "東洋スチレン", "デンカ"],
        "kr": ["LG화학", "한국이네오스스타이롤루션"],
        "tw": ["1305", "1312"],  # 華夏, 國喬
    },
    "9003-56-9": {  # ABS
        "us": ["DOW", "TSE", "INEOS"],
        "jp": ["旭化成", "東レ", "テクノポリマー", "UMG ABS"],
        "kr": ["LG화학", "한국이네오스스타이롤루션"],
        "tw": ["1308", "1305"],  # 亞聚, 華夏
    },
    "25038-59-9": {  # PET (polyethylene terephthalate)
        "us": ["EMN", "OWY"],
        "jp": ["東洋紡", "東レ", "三菱ケミカルグループ", "帝人", "ベルポリエステルプロダクツ"],
        "kr": ["롯데케미칼", "효성첨단소재", "휴비스", "SKC"],
        "tw": ["1303", "1326", "1409"],  # 南亞, 台塑化, 新纖
    },
    "25640-14-6": {  # PBT (polybutylene terephthalate)
        "us": ["EMN", "CE"],
        "jp": ["東レ", "三菱ケミカルグループ", "ポリプラスチックス", "ウィンテックポリマー"],
        "kr": ["LG화학"],
        "tw": ["1303"],
    },
    "25036-25-3": {  # PC (polycarbonate)
        "us": ["DOW", "CVX"],
        "jp": ["三菱ガス化学", "三菱瓦斯化学", "帝人", "出光興産"],
        "kr": ["LG화학", "롯데케미칼", "三養化成"],
        "tw": [],
    },
    "9011-14-7": {  # PMMA
        "us": ["DOW"],
        "jp": ["三菱ケミカルグループ", "クラレ", "クラリアント"],
        "kr": ["LG MMA"],
        "tw": [],
    },
    "25038-54-4": {  # Nylon 6
        "us": ["DOW", "ASH"],
        "jp": ["宇部", "ＵＢＥ", "東レ", "東洋紡", "三菱ケミカルグループ"],
        "kr": ["효성첨단소재", "코오롱인더스트리"],
        "tw": ["1717", "1305"],
    },
    "32131-17-2": {  # Nylon 6,6
        "us": ["DOW", "INVISTA"],
        "jp": ["旭化成", "東レ"],
        "kr": ["효성첨단소재"],
        "tw": [],
    },
    "29127-58-2": {  # POM (polyoxymethylene)
        "us": ["CE", "DOW"],
        "jp": ["ポリプラスチックス", "三菱ガス化学", "三菱瓦斯化学", "旭化成"],
        "kr": ["KEP", "LG화학"],
        "tw": ["1717"],
    },
    "26063-22-9": {  # PEEK
        "us": ["VVS", "SLLN"],  # Victrex, Solvay
        "jp": ["ダイセル・エボニック"],
        "kr": [],
        "tw": [],
    },
    "25104-37-4": {  # PPS (polyphenylene sulfide)
        "us": ["CE", "TOR"],
        "jp": ["東レ", "DIC", "東ソー", "クレハ"],
        "kr": ["SK케미칼"],
        "tw": [],
    },
    "9002-83-9": {  # PTFE
        "us": ["CC", "GORE"],
        "jp": ["AGC", "ダイキン工業", "三井・ケマーズフロロプロダクツ"],
        "kr": ["삼성SDI", "한라테크그룹"],
        "tw": [],
    },
    "9002-84-0": {  # PVDF
        "us": ["CC", "ARK"],
        "jp": ["クレハ", "ダイキン工業"],
        "kr": ["LG화학"],
        "tw": [],
    },
    "24937-79-9": {  # PVDC
        "us": ["DOW"],
        "jp": ["旭化成", "クレハ"],
        "kr": [],
        "tw": [],
    },
    "25214-39-5": {  # PMP (polymethylpentene)
        "us": [],
        "jp": ["三井化学"],
        "kr": [],
        "tw": [],
    },
    "9008-44-8": {  # EPDM
        "us": ["DOW", "ARLN"],
        "jp": ["JSR", "住友化学", "三井化学", "三井・デュポンポリケミカル"],
        "kr": ["金호석유화학", "금호석유화학"],
        "tw": [],
    },

    # ==================== Rubber chemicals ====================
    "120-78-5": {  # MBTS (vulc accelerator)
        "us": ["TSE", "LXS"],
        "jp": ["大内新興化学工業", "三新化学工業", "川口化学工業"],
        "kr": ["미원상사"],
        "tw": [],
    },
    "149-30-4": {  # MBT
        "us": ["TSE", "LXS"],
        "jp": ["大内新興化学工業", "川口化学工業"],
        "kr": [],
        "tw": [],
    },
    "102-77-2": {  # NS antioxidant
        "us": ["TSE"],
        "jp": ["大内新興化学工業", "川口化学工業"],
        "kr": [],
        "tw": [],
    },
    "793-24-8": {  # 6PPD
        "us": ["TSE", "LXS"],
        "jp": ["住友化学", "大内新興化学工業"],
        "kr": ["금호석유화학"],
        "tw": [],
    },
    "101-72-4": {  # IPPD
        "us": ["TSE"],
        "jp": ["住友化学"],
        "kr": [],
        "tw": [],
    },
    "137-26-8": {  # TMTD
        "us": ["TSE"],
        "jp": ["大内新興化学工業"],
        "kr": [],
        "tw": [],
    },

    # ==================== Battery materials ====================
    "12190-79-3": {  # LCO (LiCoO2)
        "us": ["ALB"],
        "jp": ["日亜化学工業", "戸田工業", "住友金属鉱山"],
        "kr": ["LG화학", "엘앤에프", "에코프로비엠", "포스코퓨처엠"],
        "tw": [],
    },
    "182442-95-1": {  # NCA cathode
        "us": ["ALB"],
        "jp": ["住友金属鉱山", "日亜化学工業", "田中化学研究所"],
        "kr": ["엘앤에프", "에코프로비엠", "포스코퓨처엠"],
        "tw": [],
    },
    "346417-97-8": {  # LFP cathode
        "us": ["ALB"],
        "jp": ["住友大阪セメント", "戸田工業"],
        "kr": ["엘앤에프", "에코프로비엠"],
        "tw": ["6533"],  # 晶碩
    },
    "7782-42-5": {  # Graphite (battery anode)
        "us": ["NVO"],
        "jp": ["日立化成", "三菱ケミカルグループ", "東海カーボン"],
        "kr": ["포스코퓨처엠"],
        "tw": [],
    },
    "21324-40-3": {  # LiPF6 electrolyte salt
        "us": ["ALB"],
        "jp": ["関東電化工業", "ステラケミファ", "セントラル硝子"],
        "kr": ["천보", "후성"],
        "tw": [],
    },
    "96-49-1": {  # EC ethylene carbonate
        "us": ["BASF"],
        "jp": ["三菱ケミカルグループ", "東ソー"],
        "kr": ["엔켐", "SK이노베이션"],
        "tw": [],
    },
    "108-32-7": {  # PC propylene carbonate
        "us": ["LYB"],
        "jp": ["三菱ケミカルグループ"],
        "kr": ["엔켐"],
        "tw": [],
    },
    "623-53-0": {  # EMC ethyl methyl carbonate (battery electrolyte)
        "us": [],
        "jp": ["宇部", "ＵＢＥ"],
        "kr": ["엔켐", "SK이노베이션"],
        "tw": [],
    },
    "616-38-6": {  # DMC dimethyl carbonate
        "us": ["LYB"],
        "jp": ["旭化成", "三菱ケミカルグループ"],
        "kr": ["롯데케미칼"],
        "tw": [],
    },
    "105-58-8": {  # DEC diethyl carbonate
        "us": ["LYB"],
        "jp": ["宇部", "ＵＢＥ"],
        "kr": ["엔켐"],
        "tw": [],
    },
    "554-13-2": {  # Li2CO3 lithium carbonate (battery precursor)
        "us": ["ALB", "LAC", "LTH"],
        "jp": ["豊田通商"],
        "kr": ["포스코퓨처엠", "LG화학"],
        "tw": [],
    },
    "554-12-1": {  # LiOH lithium hydroxide
        "us": ["ALB", "LAC", "LTH"],
        "jp": ["豊田通商"],
        "kr": ["포스코퓨처엠"],
        "tw": [],
    },

    # ==================== Semiconductor materials ====================
    "7647-01-0": {  # HCl
        "us": ["OLN", "WLK", "FMC"],
        "jp": ["東ソー", "信越化学工業", "AGC"],
        "kr": ["LG화학"],
        "tw": [],
    },
    "7664-39-3": {  # HF anhydrous
        "us": ["HON", "CC"],
        "jp": ["ステラケミファ", "セントラル硝子", "森田化学工業"],
        "kr": ["솔브레인", "후성", "Foosung"],
        "tw": [],
    },
    "7783-54-2": {  # NF3
        "us": ["LIN", "APD"],
        "jp": ["関東電化工業", "セントラル硝子"],
        "kr": ["효성", "후성", "SK머티리얼즈"],
        "tw": [],
    },
    "10025-77-1": {  # FeCl3 (semiconductor etching)
        "us": [],
        "jp": ["JX金属", "東邦亜鉛"],
        "kr": [],
        "tw": [],
    },
    "7440-65-5": {  # Y (yttrium)
        "us": ["MP"],
        "jp": ["日本イットリウム"],
        "kr": [],
        "tw": [],
    },
    "1306-23-6": {  # CdS quantum dot
        "us": ["NNO"],
        "jp": ["三菱マテリアル"],
        "kr": [],
        "tw": [],
    },
    "1314-13-2": {  # ZnO
        "us": ["TSE"],
        "jp": ["堺化学工業", "本荘ケミカル", "三井金属鉱業"],
        "kr": [],
        "tw": [],
    },
    "1330-43-4": {  # Borax
        "us": ["BORAX", "RIO"],
        "jp": [],
        "kr": [],
        "tw": [],
    },

    # ==================== Solvents ====================
    "75-09-2": {  # Dichloromethane (DCM)
        "us": ["OXY", "OLN"],
        "jp": ["東ソー", "信越化学工業"],
        "kr": [],
        "tw": [],
    },
    "67-66-3": {  # Chloroform
        "us": ["OXY"],
        "jp": ["東ソー"],
        "kr": [],
        "tw": [],
    },
    "56-23-5": {  # Carbon tetrachloride
        "us": ["OXY"],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "107-06-2": {  # 1,2-Dichloroethane (EDC)
        "us": ["DOW", "OLN", "WLK"],
        "jp": ["信越化学工業", "東ソー", "カネカ"],
        "kr": ["LG화학", "한화솔루션"],
        "tw": ["1303"],
    },
    "127-18-4": {  # Perchloroethylene (PCE)
        "us": ["OXY", "DOW"],
        "jp": ["旭硝子", "AGC"],
        "kr": [],
        "tw": [],
    },
    "79-01-6": {  # Trichloroethylene (TCE)
        "us": ["OXY"],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "67-72-1": {  # Hexachloroethane
        "us": [],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "108-90-7": {  # Chlorobenzene
        "us": ["OXY"],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "78-93-3": {  # MEK
        "us": ["EMN", "OXY"],
        "jp": ["丸善石油化学", "東ソー", "三菱ケミカルグループ"],
        "kr": ["LG화학"],
        "tw": ["1303"],
    },
    "108-10-1": {  # MIBK
        "us": ["EMN", "DOW"],
        "jp": ["三井化学"],
        "kr": ["LG화학"],
        "tw": [],
    },
    "141-78-6": {  # Ethyl acetate
        "us": ["CE"],
        "jp": ["昭和電工マテリアルズ", "レゾナック・ホールディングス", "ダイセル"],
        "kr": ["LG화학"],
        "tw": [],
    },
    "109-99-9": {  # THF
        "us": ["BASF", "INVISTA"],
        "jp": ["三菱ケミカルグループ", "BASFジャパン"],
        "kr": [],
        "tw": [],
    },
    "1634-04-4": {  # MTBE
        "us": ["LYB", "DOW"],
        "jp": ["ENEOS", "出光興産"],
        "kr": ["여천NCC"],
        "tw": ["1303"],
    },

    # ==================== Inorganics ====================
    "7664-93-9": {  # Sulfuric acid
        "us": ["TSE", "OXY"],
        "jp": ["JX金属", "日本ガス化学", "東邦亜鉛", "DOWAホールディングス", "三井金属鉱業"],
        "kr": ["LG화학", "고려아연"],
        "tw": [],
    },
    "7647-14-5": {  # NaCl
        "us": ["CMP", "OLN"],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "1310-58-3": {  # KOH
        "us": ["OXY", "OLN"],
        "jp": ["東ソー", "AGC", "旭硝子"],
        "kr": ["한화솔루션"],
        "tw": [],
    },
    "1310-73-2": {  # NaOH
        "us": ["OLN", "WLK"],
        "jp": ["東ソー", "旭硝子", "AGC", "信越化学工業", "カネカ"],
        "kr": ["LG화학", "한화솔루션"],
        "tw": ["1717", "1314"],
    },
    "7681-52-9": {  # NaOCl (sodium hypochlorite)
        "us": ["OLN", "WLK"],
        "jp": ["東ソー", "日本軽金属"],
        "kr": [],
        "tw": [],
    },
    "1305-78-8": {  # CaO
        "us": ["LHN", "MLM"],
        "jp": ["太平洋セメント", "宇部マテリアルズ", "ＵＢＥ"],
        "kr": [],
        "tw": [],
    },
    "1305-62-0": {  # Ca(OH)2
        "us": ["LHN", "MLM"],
        "jp": ["宇部マテリアルズ"],
        "kr": [],
        "tw": [],
    },
    "1305-78-8/CaCO3": {  # CaCO3
        "us": ["OMYA"],
        "jp": ["丸尾カルシウム", "白石カルシウム"],
        "kr": [],
        "tw": [],
    },
    "13463-67-7": {  # TiO2
        "us": ["CC", "TROX", "KRO"],
        "jp": ["石原産業", "テイカ", "サカイケミカル"],
        "kr": ["KCC"],
        "tw": [],
    },
    "1314-23-4": {  # ZrO2
        "us": ["ALB"],
        "jp": ["東ソー", "第一稀元素化学工業"],
        "kr": [],
        "tw": [],
    },
    "1344-28-1": {  # Al2O3
        "us": ["AA"],
        "jp": ["昭和電工マテリアルズ", "レゾナック・ホールディングス", "住友化学", "日本軽金属"],
        "kr": [],
        "tw": [],
    },
    "1310-32-3": {  # LiOH again skip
    },
    "7440-44-0": {  # Carbon (activated carbon)
        "us": ["CBT"],
        "jp": ["クラレ", "大阪ガスケミカル"],
        "kr": [],
        "tw": [],
    },
    "13463-39-3": {  # Nickel carbonyl
        "us": ["VALE"],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "7440-50-8": {  # Cu
        "us": ["FCX", "SCCO"],
        "jp": ["JX金属", "住友金属鉱山", "三菱マテリアル", "DOWAホールディングス"],
        "kr": ["풍산"],
        "tw": [],
    },
    "7440-66-6": {  # Zn
        "us": [],
        "jp": ["東邦亜鉛", "三井金属鉱業"],
        "kr": ["고려아연"],
        "tw": [],
    },

    # ==================== Catalysts / specialties (selected) ====================
    "10025-78-2": {  # SiHCl3 (TCS, polysilicon)
        "us": ["WFR"],
        "jp": ["三菱マテリアル", "高純度シリコン"],
        "kr": ["OCI"],
        "tw": [],
    },
    "7647-19-0": {  # PF5
        "us": [],
        "jp": ["関東電化工業", "森田化学工業", "ステラケミファ"],
        "kr": ["후성"],
        "tw": [],
    },
    "7782-39-0": {  # D2 (deuterium) — used in EUV / semiconductor
        "us": ["LIN", "APD"],
        "jp": ["日本酸素ホールディングス"],
        "kr": [],
        "tw": [],
    },

    # ==================== Fluorochemicals ====================
    "76-13-1": {  # CFC-113
        "us": ["CC", "HON"],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "75-71-8": {  # CFC-12
        "us": ["CC", "HON"],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "75-69-4": {  # CFC-11
        "us": ["CC", "HON"],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "335-67-1": {  # PFOA
        "us": ["CC"],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "1763-23-1": {  # PFOS
        "us": ["MMM"],
        "jp": [],
        "kr": [],
        "tw": [],
    },

    # ==================== Plasticizers ====================
    "117-81-7": {  # DEHP
        "us": ["EMN"],
        "jp": ["新日本理化", "DIC", "ジェイ・プラス"],
        "kr": ["LG화학", "한화솔루션"],
        "tw": [],
    },
    "84-74-2": {  # DBP
        "us": ["EMN"],
        "jp": ["新日本理化", "DIC"],
        "kr": [],
        "tw": [],
    },
    "84-69-5": {  # DIBP
        "us": [],
        "jp": ["新日本理化"],
        "kr": [],
        "tw": [],
    },
    "85-68-7": {  # BBP
        "us": ["EMN"],
        "jp": ["新日本理化"],
        "kr": [],
        "tw": [],
    },
    "26761-40-0": {  # DIDP
        "us": ["EMN", "EXX"],
        "jp": ["新日本理化"],
        "kr": ["LG화학"],
        "tw": [],
    },
    "68515-49-1": {  # DINP
        "us": ["EMN", "EXX"],
        "jp": ["新日本理化", "DIC"],
        "kr": ["LG화학", "한화솔루션"],
        "tw": [],
    },

    # ==================== Surfactants / detergents ====================
    "151-21-3": {  # SDS
        "us": ["DOW"],
        "jp": ["花王", "ライオン", "三洋化成工業"],
        "kr": [],
        "tw": [],
    },
    "9016-45-9": {  # Nonylphenol ethoxylate
        "us": ["DOW"],
        "jp": ["第一工業製薬", "東邦化学工業"],
        "kr": [],
        "tw": [],
    },

    # ==================== Pigments ====================
    "147-14-8": {  # CuPc Blue
        "us": ["FERR"],
        "jp": ["DIC", "山陽色素"],
        "kr": [],
        "tw": [],
    },
    "1314-41-6": {  # Pb3O4
        "us": [],
        "jp": [],
        "kr": [],
        "tw": [],
    },
    "1308-38-9": {  # Cr2O3 green pigment
        "us": ["TSE"],
        "jp": ["日本電工"],
        "kr": [],
        "tw": [],
    },

    # ==================== Additives (general) ====================
    "128-37-0": {  # BHT
        "us": ["EMN"],
        "jp": ["本州化学工業", "住友化学"],
        "kr": [],
        "tw": [],
    },
    "2082-79-3": {  # Irganox 1076
        "us": ["BASF"],
        "jp": ["ADEKA", "城北化学工業"],
        "kr": [],
        "tw": [],
    },
}

if __name__ == "__main__":
    print(f"Manual mapping covers {len(MANUFACTURERS)} CAS")
    print("Categories of US tickers:")
    from collections import Counter
    us_cnt = Counter()
    jp_cnt = Counter()
    kr_cnt = Counter()
    tw_cnt = Counter()
    for v in MANUFACTURERS.values():
        for t in v.get("us") or []: us_cnt[t] += 1
        for t in v.get("jp") or []: jp_cnt[t] += 1
        for t in v.get("kr") or []: kr_cnt[t] += 1
        for t in v.get("tw") or []: tw_cnt[t] += 1
    print(f"\nUS distinct: {len(us_cnt)}, total refs: {sum(us_cnt.values())}")
    print(f"JP distinct: {len(jp_cnt)}, total refs: {sum(jp_cnt.values())}")
    print(f"KR distinct: {len(kr_cnt)}, total refs: {sum(kr_cnt.values())}")
    print(f"TW distinct: {len(tw_cnt)}, total refs: {sum(tw_cnt.values())}")
