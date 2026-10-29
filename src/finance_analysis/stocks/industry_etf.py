"""Reviewed industry → ETF proxies, not ETF holdings or investment recommendations.

US keys are exact (Yahoo sector, industry) pairs from Instrument classification.
CN keys are Fuyao industry_catalog codes; CN Instrument has no classification.
Unknown categories stay unmapped. No name inference or broad-market fallback.
This registry does not enable the Confluence ETF dimension by itself.
"""

from dataclasses import dataclass

MAPPING_VERSION = "industry_etf_v1"


@dataclass(frozen=True)
class IndustryETF:
    etf_code: str | None
    reason: str


# 每个条目是行业代理判断；不是成分股证明，不能据此声称ETF持有该股票。
US_INDUSTRY_ETF: dict[tuple[str, str], IndustryETF] = {
    # Agricultural Inputs：材料板块宽口径代理，非该细分行业专属基金。
    ("Basic Materials", "Agricultural Inputs"): IndustryETF("XLB.US", "材料板块宽口径代理，非该细分行业专属基金"),
    # Aluminum：金属矿业行业代理，不将其等同于商品价格。
    ("Basic Materials", "Aluminum"): IndustryETF("XME.US", "金属矿业行业代理，不将其等同于商品价格"),
    # Building Materials：材料板块宽口径代理，非该细分行业专属基金。
    ("Basic Materials", "Building Materials"): IndustryETF("XLB.US", "材料板块宽口径代理，非该细分行业专属基金"),
    # Chemicals：材料板块宽口径代理，非该细分行业专属基金。
    ("Basic Materials", "Chemicals"): IndustryETF("XLB.US", "材料板块宽口径代理，非该细分行业专属基金"),
    # Coking Coal：金属矿业行业代理，不将其等同于商品价格。
    ("Basic Materials", "Coking Coal"): IndustryETF("XME.US", "金属矿业行业代理，不将其等同于商品价格"),
    # Copper：铜矿业主题代理。
    ("Basic Materials", "Copper"): IndustryETF("COPX.US", "铜矿业主题代理"),
    # Gold：黄金矿业主题代理，区别于黄金现货基金。
    ("Basic Materials", "Gold"): IndustryETF("GDX.US", "黄金矿业主题代理，区别于黄金现货基金"),
    # Lumber & Wood Production：材料板块宽口径代理，非该细分行业专属基金。
    ("Basic Materials", "Lumber & Wood Production"): IndustryETF("XLB.US", "材料板块宽口径代理，非该细分行业专属基金"),
    # Other Industrial Metals & Mining：金属矿业行业代理，不将其等同于商品价格。
    ("Basic Materials", "Other Industrial Metals & Mining"): IndustryETF(
        "XME.US", "金属矿业行业代理，不将其等同于商品价格"
    ),
    # Other Precious Metals & Mining：金属矿业行业代理，不将其等同于商品价格。
    ("Basic Materials", "Other Precious Metals & Mining"): IndustryETF(
        "XME.US", "金属矿业行业代理，不将其等同于商品价格"
    ),
    # Paper & Paper Products：材料板块宽口径代理，非该细分行业专属基金。
    ("Basic Materials", "Paper & Paper Products"): IndustryETF("XLB.US", "材料板块宽口径代理，非该细分行业专属基金"),
    # Silver：白银矿业主题代理。
    ("Basic Materials", "Silver"): IndustryETF("SIL.US", "白银矿业主题代理"),
    # Specialty Chemicals：材料板块宽口径代理，非该细分行业专属基金。
    ("Basic Materials", "Specialty Chemicals"): IndustryETF("XLB.US", "材料板块宽口径代理，非该细分行业专属基金"),
    # Steel：金属矿业行业代理，不将其等同于商品价格。
    ("Basic Materials", "Steel"): IndustryETF("XME.US", "金属矿业行业代理，不将其等同于商品价格"),
    # Advertising Agencies：通信服务板块宽口径代理，包含传媒及通信业务。
    ("Communication Services", "Advertising Agencies"): IndustryETF(
        "XLC.US", "通信服务板块宽口径代理，包含传媒及通信业务"
    ),
    # Broadcasting：通信服务板块宽口径代理，包含传媒及通信业务。
    ("Communication Services", "Broadcasting"): IndustryETF("XLC.US", "通信服务板块宽口径代理，包含传媒及通信业务"),
    # Electronic Gaming & Multimedia：通信服务板块宽口径代理，包含传媒及通信业务。
    ("Communication Services", "Electronic Gaming & Multimedia"): IndustryETF(
        "XLC.US", "通信服务板块宽口径代理，包含传媒及通信业务"
    ),
    # Entertainment：通信服务板块宽口径代理，包含传媒及通信业务。
    ("Communication Services", "Entertainment"): IndustryETF("XLC.US", "通信服务板块宽口径代理，包含传媒及通信业务"),
    # Internet Content & Information：通信服务板块宽口径代理，包含传媒及通信业务。
    ("Communication Services", "Internet Content & Information"): IndustryETF(
        "XLC.US", "通信服务板块宽口径代理，包含传媒及通信业务"
    ),
    # Publishing：通信服务板块宽口径代理，包含传媒及通信业务。
    ("Communication Services", "Publishing"): IndustryETF("XLC.US", "通信服务板块宽口径代理，包含传媒及通信业务"),
    # Telecom Services：通信服务板块宽口径代理，包含传媒及通信业务。
    ("Communication Services", "Telecom Services"): IndustryETF("XLC.US", "通信服务板块宽口径代理，包含传媒及通信业务"),
    # Apparel Manufacturing：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Apparel Manufacturing"): IndustryETF(
        "XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"
    ),
    # Apparel Retail：零售行业代理，不推断实际持仓。
    ("Consumer Cyclical", "Apparel Retail"): IndustryETF("XRT.US", "零售行业代理，不推断实际持仓"),
    # Auto & Truck Dealerships：零售行业代理，不推断实际持仓。
    ("Consumer Cyclical", "Auto & Truck Dealerships"): IndustryETF("XRT.US", "零售行业代理，不推断实际持仓"),
    # Auto Manufacturers：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Auto Manufacturers"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Auto Parts：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Auto Parts"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Department Stores：零售行业代理，不推断实际持仓。
    ("Consumer Cyclical", "Department Stores"): IndustryETF("XRT.US", "零售行业代理，不推断实际持仓"),
    # Footwear & Accessories：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Footwear & Accessories"): IndustryETF(
        "XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"
    ),
    # Furnishings, Fixtures & Appliances：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Furnishings, Fixtures & Appliances"): IndustryETF(
        "XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"
    ),
    # Gambling：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Gambling"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Home Improvement Retail：零售行业代理，不推断实际持仓。
    ("Consumer Cyclical", "Home Improvement Retail"): IndustryETF("XRT.US", "零售行业代理，不推断实际持仓"),
    # Internet Retail：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Internet Retail"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Leisure：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Leisure"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Lodging：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Lodging"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Luxury Goods：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Luxury Goods"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Packaging & Containers：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Packaging & Containers"): IndustryETF(
        "XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"
    ),
    # Personal Services：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Personal Services"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Recreational Vehicles：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Recreational Vehicles"): IndustryETF(
        "XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"
    ),
    # Residential Construction：住宅建造行业代理。
    ("Consumer Cyclical", "Residential Construction"): IndustryETF("XHB.US", "住宅建造行业代理"),
    # Resorts & Casinos：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Resorts & Casinos"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Restaurants：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Restaurants"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Specialty Retail：零售行业代理，不推断实际持仓。
    ("Consumer Cyclical", "Specialty Retail"): IndustryETF("XRT.US", "零售行业代理，不推断实际持仓"),
    # Textile Manufacturing：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Textile Manufacturing"): IndustryETF(
        "XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"
    ),
    # Travel Services：可选消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Cyclical", "Travel Services"): IndustryETF("XLY.US", "可选消费板块宽口径代理，非该细分行业专属基金"),
    # Beverages—Brewers：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Beverages—Brewers"): IndustryETF("XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"),
    # Beverages—Non-Alcoholic：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Beverages—Non-Alcoholic"): IndustryETF(
        "XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"
    ),
    # Beverages—Wineries & Distilleries：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Beverages—Wineries & Distilleries"): IndustryETF(
        "XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"
    ),
    # Confectioners：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Confectioners"): IndustryETF("XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"),
    # Discount Stores：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Discount Stores"): IndustryETF("XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"),
    # Education & Training Services：教育培训不属于现有必需消费ETF的可靠行业代理，保留未关联。
    ("Consumer Defensive", "Education & Training Services"): IndustryETF(
        None, "教育培训不属于现有必需消费ETF的可靠行业代理，保留未关联"
    ),
    # Farm Products：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Farm Products"): IndustryETF("XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"),
    # Food Distribution：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Food Distribution"): IndustryETF("XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"),
    # Grocery Stores：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Grocery Stores"): IndustryETF("XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"),
    # Household & Personal Products：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Household & Personal Products"): IndustryETF(
        "XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"
    ),
    # Packaged Foods：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Packaged Foods"): IndustryETF("XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"),
    # Tobacco：必需消费板块宽口径代理，非该细分行业专属基金。
    ("Consumer Defensive", "Tobacco"): IndustryETF("XLP.US", "必需消费板块宽口径代理，非该细分行业专属基金"),
    # Oil & Gas Drilling：油气设备及服务行业代理。
    ("Energy", "Oil & Gas Drilling"): IndustryETF("XES.US", "油气设备及服务行业代理"),
    # Oil & Gas E&P：油气勘探开采行业代理。
    ("Energy", "Oil & Gas E&P"): IndustryETF("XOP.US", "油气勘探开采行业代理"),
    # Oil & Gas Equipment & Services：油气设备及服务行业代理。
    ("Energy", "Oil & Gas Equipment & Services"): IndustryETF("XES.US", "油气设备及服务行业代理"),
    # Oil & Gas Integrated：能源板块宽口径代理，非该细分行业专属基金。
    ("Energy", "Oil & Gas Integrated"): IndustryETF("XLE.US", "能源板块宽口径代理，非该细分行业专属基金"),
    # Oil & Gas Midstream：能源中游及基础设施代理。
    ("Energy", "Oil & Gas Midstream"): IndustryETF("MLPX.US", "能源中游及基础设施代理"),
    # Oil & Gas Refining & Marketing：能源板块宽口径代理，非该细分行业专属基金。
    ("Energy", "Oil & Gas Refining & Marketing"): IndustryETF("XLE.US", "能源板块宽口径代理，非该细分行业专属基金"),
    # Thermal Coal：动力煤与现有油气能源ETF范围不同，池中没有煤炭代理。
    ("Energy", "Thermal Coal"): IndustryETF(None, "动力煤与现有油气能源ETF范围不同，池中没有煤炭代理"),
    # Uranium：铀矿及核燃料主题代理。
    ("Energy", "Uranium"): IndustryETF("URA.US", "铀矿及核燃料主题代理"),
    # Asset Management：金融板块宽口径代理，不表示基金持有该股票。
    ("Financial Services", "Asset Management"): IndustryETF("XLF.US", "金融板块宽口径代理，不表示基金持有该股票"),
    # Banks—Diversified：银行行业代理。
    ("Financial Services", "Banks—Diversified"): IndustryETF("KBE.US", "银行行业代理"),
    # Banks—Regional：区域银行行业代理。
    ("Financial Services", "Banks—Regional"): IndustryETF("KRE.US", "区域银行行业代理"),
    # Capital Markets：资本市场行业代理。
    ("Financial Services", "Capital Markets"): IndustryETF("KCE.US", "资本市场行业代理"),
    # Credit Services：金融板块宽口径代理，不表示基金持有该股票。
    ("Financial Services", "Credit Services"): IndustryETF("XLF.US", "金融板块宽口径代理，不表示基金持有该股票"),
    # Financial Conglomerates：金融板块宽口径代理，不表示基金持有该股票。
    ("Financial Services", "Financial Conglomerates"): IndustryETF(
        "XLF.US", "金融板块宽口径代理，不表示基金持有该股票"
    ),
    # Financial Data & Stock Exchanges：资本市场行业代理。
    ("Financial Services", "Financial Data & Stock Exchanges"): IndustryETF("KCE.US", "资本市场行业代理"),
    # Insurance Brokers：保险行业代理。
    ("Financial Services", "Insurance Brokers"): IndustryETF("KIE.US", "保险行业代理"),
    # Insurance—Diversified：保险行业代理。
    ("Financial Services", "Insurance—Diversified"): IndustryETF("KIE.US", "保险行业代理"),
    # Insurance—Life：保险行业代理。
    ("Financial Services", "Insurance—Life"): IndustryETF("KIE.US", "保险行业代理"),
    # Insurance—Property & Casualty：保险行业代理。
    ("Financial Services", "Insurance—Property & Casualty"): IndustryETF("KIE.US", "保险行业代理"),
    # Insurance—Reinsurance：保险行业代理。
    ("Financial Services", "Insurance—Reinsurance"): IndustryETF("KIE.US", "保险行业代理"),
    # Insurance—Specialty：保险行业代理。
    ("Financial Services", "Insurance—Specialty"): IndustryETF("KIE.US", "保险行业代理"),
    # Mortgage Finance：金融板块宽口径代理，不表示基金持有该股票。
    ("Financial Services", "Mortgage Finance"): IndustryETF("XLF.US", "金融板块宽口径代理，不表示基金持有该股票"),
    # Shell Companies：空壳公司无稳定经营行业，不用金融ETF强行覆盖。
    ("Financial Services", "Shell Companies"): IndustryETF(None, "空壳公司无稳定经营行业，不用金融ETF强行覆盖"),
    # Biotechnology：生物技术行业代理。
    ("Healthcare", "Biotechnology"): IndustryETF("XBI.US", "生物技术行业代理"),
    # Diagnostics & Research：医疗健康板块宽口径代理，非该细分行业专属基金。
    ("Healthcare", "Diagnostics & Research"): IndustryETF("XLV.US", "医疗健康板块宽口径代理，非该细分行业专属基金"),
    # Drug Manufacturers—General：制药行业代理，不把全部药企判为创新药。
    ("Healthcare", "Drug Manufacturers—General"): IndustryETF("XPH.US", "制药行业代理，不把全部药企判为创新药"),
    # Drug Manufacturers—Specialty & Generic：制药行业代理，不把全部药企判为创新药。
    ("Healthcare", "Drug Manufacturers—Specialty & Generic"): IndustryETF(
        "XPH.US", "制药行业代理，不把全部药企判为创新药"
    ),
    # Health Information Services：医疗健康板块宽口径代理，非该细分行业专属基金。
    ("Healthcare", "Health Information Services"): IndustryETF(
        "XLV.US", "医疗健康板块宽口径代理，非该细分行业专属基金"
    ),
    # Healthcare Plans：医疗服务行业代理。
    ("Healthcare", "Healthcare Plans"): IndustryETF("XHS.US", "医疗服务行业代理"),
    # Medical Care Facilities：医疗服务行业代理。
    ("Healthcare", "Medical Care Facilities"): IndustryETF("XHS.US", "医疗服务行业代理"),
    # Medical Devices：医疗器械行业代理。
    ("Healthcare", "Medical Devices"): IndustryETF("IHI.US", "医疗器械行业代理"),
    # Medical Distribution：医疗服务行业代理。
    ("Healthcare", "Medical Distribution"): IndustryETF("XHS.US", "医疗服务行业代理"),
    # Medical Instruments & Supplies：医疗设备及用品行业代理。
    ("Healthcare", "Medical Instruments & Supplies"): IndustryETF("XHE.US", "医疗设备及用品行业代理"),
    # Pharmaceutical Retailers：医疗健康板块宽口径代理，非该细分行业专属基金。
    ("Healthcare", "Pharmaceutical Retailers"): IndustryETF("XLV.US", "医疗健康板块宽口径代理，非该细分行业专属基金"),
    # Aerospace & Defense：航空航天与国防行业代理，不推断商业航天子主题。
    ("Industrials", "Aerospace & Defense"): IndustryETF("XAR.US", "航空航天与国防行业代理，不推断商业航天子主题"),
    # Airlines：交通运输行业代理。
    ("Industrials", "Airlines"): IndustryETF("XTN.US", "交通运输行业代理"),
    # Airports & Air Services：交通运输行业代理。
    ("Industrials", "Airports & Air Services"): IndustryETF("XTN.US", "交通运输行业代理"),
    # Building Products & Equipment：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Building Products & Equipment"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Business Equipment & Supplies：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Business Equipment & Supplies"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Conglomerates：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Conglomerates"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Consulting Services：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Consulting Services"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Electrical Equipment & Parts：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Electrical Equipment & Parts"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Engineering & Construction：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Engineering & Construction"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Farm & Heavy Construction Machinery：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Farm & Heavy Construction Machinery"): IndustryETF(
        "XLI.US", "工业板块宽口径代理，非该细分行业专属基金"
    ),
    # Industrial Distribution：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Industrial Distribution"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Infrastructure Operations：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Infrastructure Operations"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Integrated Freight & Logistics：交通运输行业代理。
    ("Industrials", "Integrated Freight & Logistics"): IndustryETF("XTN.US", "交通运输行业代理"),
    # Marine Shipping：交通运输行业代理。
    ("Industrials", "Marine Shipping"): IndustryETF("XTN.US", "交通运输行业代理"),
    # Metal Fabrication：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Metal Fabrication"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Pollution & Treatment Controls：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Pollution & Treatment Controls"): IndustryETF(
        "XLI.US", "工业板块宽口径代理，非该细分行业专属基金"
    ),
    # Railroads：交通运输行业代理。
    ("Industrials", "Railroads"): IndustryETF("XTN.US", "交通运输行业代理"),
    # Rental & Leasing Services：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Rental & Leasing Services"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Security & Protection Services：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Security & Protection Services"): IndustryETF(
        "XLI.US", "工业板块宽口径代理，非该细分行业专属基金"
    ),
    # Specialty Business Services：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Specialty Business Services"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Specialty Industrial Machinery：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Specialty Industrial Machinery"): IndustryETF(
        "XLI.US", "工业板块宽口径代理，非该细分行业专属基金"
    ),
    # Staffing & Employment Services：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Staffing & Employment Services"): IndustryETF(
        "XLI.US", "工业板块宽口径代理，非该细分行业专属基金"
    ),
    # Tools & Accessories：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Tools & Accessories"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # Trucking：交通运输行业代理。
    ("Industrials", "Trucking"): IndustryETF("XTN.US", "交通运输行业代理"),
    # Waste Management：工业板块宽口径代理，非该细分行业专属基金。
    ("Industrials", "Waste Management"): IndustryETF("XLI.US", "工业板块宽口径代理，非该细分行业专属基金"),
    # REIT—Diversified：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "REIT—Diversified"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # REIT—Healthcare Facilities：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "REIT—Healthcare Facilities"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # REIT—Hotel & Motel：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "REIT—Hotel & Motel"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # REIT—Industrial：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "REIT—Industrial"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # REIT—Mortgage：抵押REIT与现有权益房地产ETF范围不同，池中没有可靠抵押REIT代理。
    ("Real Estate", "REIT—Mortgage"): IndustryETF(
        None, "抵押REIT与现有权益房地产ETF范围不同，池中没有可靠抵押REIT代理"
    ),
    # REIT—Office：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "REIT—Office"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # REIT—Residential：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "REIT—Residential"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # REIT—Retail：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "REIT—Retail"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # REIT—Specialty：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "REIT—Specialty"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # Real Estate Services：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "Real Estate Services"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # Real Estate—Development：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "Real Estate—Development"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # Real Estate—Diversified：房地产板块宽口径代理，不表示基金持有该股票。
    ("Real Estate", "Real Estate—Diversified"): IndustryETF("XLRE.US", "房地产板块宽口径代理，不表示基金持有该股票"),
    # Communication Equipment：科技板块宽口径代理，非该细分行业专属基金。
    ("Technology", "Communication Equipment"): IndustryETF("XLK.US", "科技板块宽口径代理，非该细分行业专属基金"),
    # Computer Hardware：科技板块宽口径代理，非该细分行业专属基金。
    ("Technology", "Computer Hardware"): IndustryETF("XLK.US", "科技板块宽口径代理，非该细分行业专属基金"),
    # Consumer Electronics：科技板块宽口径代理，非该细分行业专属基金。
    ("Technology", "Consumer Electronics"): IndustryETF("XLK.US", "科技板块宽口径代理，非该细分行业专属基金"),
    # Electronic Components：科技板块宽口径代理，非该细分行业专属基金。
    ("Technology", "Electronic Components"): IndustryETF("XLK.US", "科技板块宽口径代理，非该细分行业专属基金"),
    # Electronics & Computer Distribution：科技板块宽口径代理，非该细分行业专属基金。
    ("Technology", "Electronics & Computer Distribution"): IndustryETF(
        "XLK.US", "科技板块宽口径代理，非该细分行业专属基金"
    ),
    # Information Technology Services：科技板块宽口径代理，非该细分行业专属基金。
    ("Technology", "Information Technology Services"): IndustryETF(
        "XLK.US", "科技板块宽口径代理，非该细分行业专属基金"
    ),
    # Scientific & Technical Instruments：科技板块宽口径代理，非该细分行业专属基金。
    ("Technology", "Scientific & Technical Instruments"): IndustryETF(
        "XLK.US", "科技板块宽口径代理，非该细分行业专属基金"
    ),
    # Semiconductor Equipment & Materials：半导体产业链代理；设备材料与芯片共享行业背景。
    ("Technology", "Semiconductor Equipment & Materials"): IndustryETF(
        "SMH.US", "半导体产业链代理；设备材料与芯片共享行业背景"
    ),
    # Semiconductors：半导体产业链代理；设备材料与芯片共享行业背景。
    ("Technology", "Semiconductors"): IndustryETF("SMH.US", "半导体产业链代理；设备材料与芯片共享行业背景"),
    # Software—Application：软件行业代理，不从软件分类推断网络安全或人工智能主题。
    ("Technology", "Software—Application"): IndustryETF(
        "IGV.US", "软件行业代理，不从软件分类推断网络安全或人工智能主题"
    ),
    # Software—Infrastructure：软件行业代理，不从软件分类推断网络安全或人工智能主题。
    ("Technology", "Software—Infrastructure"): IndustryETF(
        "IGV.US", "软件行业代理，不从软件分类推断网络安全或人工智能主题"
    ),
    # Solar：太阳能主题代理。
    ("Technology", "Solar"): IndustryETF("TAN.US", "太阳能主题代理"),
    # Utilities—Diversified：公用事业板块宽口径代理，非该细分行业专属基金。
    ("Utilities", "Utilities—Diversified"): IndustryETF("XLU.US", "公用事业板块宽口径代理，非该细分行业专属基金"),
    # Utilities—Independent Power Producers：公用事业板块宽口径代理，非该细分行业专属基金。
    ("Utilities", "Utilities—Independent Power Producers"): IndustryETF(
        "XLU.US", "公用事业板块宽口径代理，非该细分行业专属基金"
    ),
    # Utilities—Regulated Electric：公用事业板块宽口径代理，非该细分行业专属基金。
    ("Utilities", "Utilities—Regulated Electric"): IndustryETF(
        "XLU.US", "公用事业板块宽口径代理，非该细分行业专属基金"
    ),
    # Utilities—Regulated Gas：公用事业板块宽口径代理，非该细分行业专属基金。
    ("Utilities", "Utilities—Regulated Gas"): IndustryETF("XLU.US", "公用事业板块宽口径代理，非该细分行业专属基金"),
    # Utilities—Regulated Water：公用事业板块宽口径代理，非该细分行业专属基金。
    ("Utilities", "Utilities—Regulated Water"): IndustryETF("XLU.US", "公用事业板块宽口径代理，非该细分行业专属基金"),
    # Utilities—Renewable：公用事业板块宽口径代理，非该细分行业专属基金。
    ("Utilities", "Utilities—Renewable"): IndustryETF("XLU.US", "公用事业板块宽口径代理，非该细分行业专属基金"),
}


# A股使用明确行业代码，一级及细分行业分别审核；未关联不是负向信号。
CN_INDUSTRY_ETF: dict[str, IndustryETF] = {
    # 种植业与林业：农业产业链代理。
    "881101.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 养殖业：农业产业链代理。
    "881102.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 农产品加工：农业产业链代理。
    "881103.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 煤炭开采加工：煤炭行业代理。
    "881105.TI": IndustryETF("515220.SH", "煤炭行业代理"),
    # 油气开采及服务：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881107.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 化学原料：化工行业宽口径代理。
    "881108.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 化学制品：化工行业宽口径代理。
    "881109.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 钢铁：钢铁不属于有色金属，现有池无钢铁ETF。
    "881112.TI": IndustryETF(None, "钢铁不属于有色金属，现有池无钢铁ETF"),
    # 金属新材料：有色金属行业代理，不以稀土ETF代表所有小金属。
    "881114.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 建筑材料：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881115.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 建筑装饰：建筑施工与基建行业宽口径代理。
    "881116.TI": IndustryETF("516970.SH", "建筑施工与基建行业宽口径代理"),
    # 通用设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881117.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 专用设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881118.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 半导体：半导体产业链代理。
    "881121.TI": IndustryETF("512480.SH", "半导体产业链代理"),
    # 光学光电子：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881122.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他电子：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881123.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 消费电子：消费电子产业链代理。
    "881124.TI": IndustryETF("159732.SZ", "消费电子产业链代理"),
    # 汽车整车：整车含燃油及商用车，不能统一映射新能源车ETF。
    "881125.TI": IndustryETF(None, "整车含燃油及商用车，不能统一映射新能源车ETF"),
    # 汽车零部件：汽车零部件行业代理。
    "881126.TI": IndustryETF("159565.SZ", "汽车零部件行业代理"),
    # 汽车服务及其他：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881128.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 通信设备：通信设备产业链代理，不扩大到电信运营商。
    "881129.TI": IndustryETF("515880.SH", "通信设备产业链代理，不扩大到电信运营商"),
    # 计算机设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881130.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 白色家电：家电行业代理。
    "881131.TI": IndustryETF("159996.SZ", "家电行业代理"),
    # 黑色家电：家电行业代理。
    "881132.TI": IndustryETF("159996.SZ", "家电行业代理"),
    # 饮料制造：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "881133.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 食品加工制造：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "881134.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 纺织制造：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881135.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 服装家纺：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881136.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 造纸：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881137.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 包装印刷：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881138.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 家居用品：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881139.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 化学制药：制药不等同创新药，现有池无宽口径制药代理。
    "881140.TI": IndustryETF(None, "制药不等同创新药，现有池无宽口径制药代理"),
    # 中药：现有医疗ETF不能直接代表中药行业。
    "881141.TI": IndustryETF(None, "现有医疗ETF不能直接代表中药行业"),
    # 生物制品：生物制品含疫苗血制品，不能一概归为创新药。
    "881142.TI": IndustryETF(None, "生物制品含疫苗血制品，不能一概归为创新药"),
    # 医药商业：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881143.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 医疗器械：医疗器械与服务行业代理，不扩大到中药及药品流通。
    "881144.TI": IndustryETF("512170.SH", "医疗器械与服务行业代理，不扩大到中药及药品流通"),
    # 电力：电力运营行业代理，不等同于设备制造。
    "881145.TI": IndustryETF("159611.SZ", "电力运营行业代理，不等同于设备制造"),
    # 燃气：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881146.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 港口航运：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881148.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 公路铁路运输：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881149.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 机场航运：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881151.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 物流：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881152.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 房地产：房地产行业代理。
    "881153.TI": IndustryETF("512200.SH", "房地产行业代理"),
    # 银行：银行行业代理。
    "881155.TI": IndustryETF("512800.SH", "银行行业代理"),
    # 保险：保险不等同银行或证券，现有池无保险代理。
    "881156.TI": IndustryETF(None, "保险不等同银行或证券，现有池无保险代理"),
    # 证券：证券行业代理，不扩大到保险及多元金融。
    "881157.TI": IndustryETF("512880.SH", "证券行业代理，不扩大到保险及多元金融"),
    # 零售：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881158.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 贸易：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881159.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 旅游及酒店：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881160.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 通信服务：通信运营服务不等同通信设备，现有池无明确运营商代理。
    "881162.TI": IndustryETF(None, "通信运营服务不等同通信设备，现有池无明确运营商代理"),
    # 文化传媒：传媒行业代理。
    "881164.TI": IndustryETF("512980.SH", "传媒行业代理"),
    # 综合：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881165.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 军工装备：国防军工行业代理。
    "881166.TI": IndustryETF("512660.SH", "国防军工行业代理"),
    # 非金属材料：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881167.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 工业金属：有色金属行业代理，不以稀土ETF代表所有小金属。
    "881168.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 贵金属：贵金属矿业宽口径代理，黄金股主题不能代表贵金属现货。
    "881169.TI": IndustryETF("517520.SH", "贵金属矿业宽口径代理，黄金股主题不能代表贵金属现货"),
    # 小金属：有色金属行业代理，不以稀土ETF代表所有小金属。
    "881170.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 自动化设备：自动化不等同机器人，保留到具体机器人子行业再映射。
    "881171.TI": IndustryETF(None, "自动化不等同机器人，保留到具体机器人子行业再映射"),
    # 电子化学品：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881172.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 小家电：家电行业代理。
    "881173.TI": IndustryETF("159996.SZ", "家电行业代理"),
    # 厨卫电器：家电行业代理。
    "881174.TI": IndustryETF("159996.SZ", "家电行业代理"),
    # 医疗服务：医疗器械与服务行业代理，不扩大到中药及药品流通。
    "881175.TI": IndustryETF("512170.SH", "医疗器械与服务行业代理，不扩大到中药及药品流通"),
    # 互联网电商：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881177.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 教育：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881178.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他社会服务：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881179.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 石油加工贸易：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881180.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 环境治理：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881181.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 美容护理：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "881182.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 农化制品：化工行业宽口径代理。
    "881263.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 化学纤维：化工行业宽口径代理。
    "881264.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 塑料制品：化工行业宽口径代理。
    "881265.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 橡胶制品：化工行业宽口径代理。
    "881266.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 能源金属：有色金属行业代理，不以稀土ETF代表所有小金属。
    "881267.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 工程机械：工程机械行业代理，不扩大到全部通用或专用设备。
    "881268.TI": IndustryETF("515970.SH", "工程机械行业代理，不扩大到全部通用或专用设备"),
    # 轨交设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881269.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 元件：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881270.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # IT服务：软件行业代理；IT服务仅使用软件生态宽口径代理。
    "881271.TI": IndustryETF("159852.SZ", "软件行业代理；IT服务仅使用软件生态宽口径代理"),
    # 软件开发：软件行业代理；IT服务仅使用软件生态宽口径代理。
    "881272.TI": IndustryETF("159852.SZ", "软件行业代理；IT服务仅使用软件生态宽口径代理"),
    # 白酒：白酒行业对应酒类ETF代理。
    "881273.TI": IndustryETF("512690.SH", "白酒行业对应酒类ETF代理"),
    # 影视院线：传媒行业代理。
    "881274.TI": IndustryETF("512980.SH", "传媒行业代理"),
    # 游戏：游戏行业代理。
    "881275.TI": IndustryETF("159869.SZ", "游戏行业代理"),
    # 军工电子：国防军工行业代理。
    "881276.TI": IndustryETF("512660.SH", "国防军工行业代理"),
    # 电机：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881277.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 电网设备：电网设备产业链代理。
    "881278.TI": IndustryETF("159326.SZ", "电网设备产业链代理"),
    # 光伏设备：光伏产业链代理。
    "881279.TI": IndustryETF("515790.SH", "光伏产业链代理"),
    # 风电设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881280.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 电池：电池产业链代理，不推断个股具体储能收入占比。
    "881281.TI": IndustryETF("159566.SZ", "电池产业链代理，不推断个股具体储能收入占比"),
    # 其他电源设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881282.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 多元金融：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881283.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 环保设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "881284.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 种子生产：农业产业链代理。
    "884001.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 粮食种植：农业产业链代理。
    "884002.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 其他种植业：农业产业链代理。
    "884003.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 林业：农业产业链代理。
    "884004.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 海洋捕捞：农业产业链代理。
    "884005.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 水产养殖：农业产业链代理。
    "884006.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 果蔬加工：农业产业链代理。
    "884009.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 粮油加工：农业产业链代理。
    "884010.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 其他农产品加工：农业产业链代理。
    "884011.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 农业综合：农业产业链代理。
    "884012.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 动物保健：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884013.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 煤炭开采：煤炭行业代理。
    "884014.TI": IndustryETF("515220.SH", "煤炭行业代理"),
    # 焦炭加工：煤炭行业代理。
    "884015.TI": IndustryETF("515220.SH", "煤炭行业代理"),
    # 油气开采：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884016.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 油服工程：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884018.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 石油加工：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884020.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 油品石化贸易：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884021.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 纯碱：化工行业宽口径代理。
    "884022.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 氯碱：化工行业宽口径代理。
    "884023.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 无机盐：化工行业宽口径代理。
    "884024.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 其他化学原料：化工行业宽口径代理。
    "884025.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 氮肥：化工行业宽口径代理。
    "884026.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 磷肥及磷化工：化工行业宽口径代理。
    "884027.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 农药：化工行业宽口径代理。
    "884028.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 涂料油墨：化工行业宽口径代理。
    "884030.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 钾肥：化工行业宽口径代理。
    "884031.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 民爆用品：化工行业宽口径代理。
    "884032.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 纺织化学用品：化工行业宽口径代理。
    "884033.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 其他化学制品：化工行业宽口径代理。
    "884034.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 复合肥：化工行业宽口径代理。
    "884035.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 氟化工：化工行业宽口径代理。
    "884036.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 聚氨酯：化工行业宽口径代理。
    "884039.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 涤纶：化工行业宽口径代理。
    "884041.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 粘胶：化工行业宽口径代理。
    "884043.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 其他纤维：化工行业宽口径代理。
    "884044.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 氨纶：化工行业宽口径代理。
    "884045.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 其他塑料制品：化工行业宽口径代理。
    "884046.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 改性塑料：化工行业宽口径代理。
    "884048.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 其他橡胶制品：化工行业宽口径代理。
    "884050.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 炭黑：化工行业宽口径代理。
    "884051.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 普钢：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884052.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 铝：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884053.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 铜：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884054.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 铅锌：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884055.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 其他金属新材料：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884056.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 磁性材料：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884057.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 玻璃玻纤：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884059.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 水泥：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884060.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他建材：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884062.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 耐火材料：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884063.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 管材：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884064.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 装饰园林：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884065.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 房屋建设：建筑施工与基建行业宽口径代理。
    "884066.TI": IndustryETF("516970.SH", "建筑施工与基建行业宽口径代理"),
    # 基础建设：建筑施工与基建行业宽口径代理。
    "884067.TI": IndustryETF("516970.SH", "建筑施工与基建行业宽口径代理"),
    # 专业工程：建筑施工与基建行业宽口径代理。
    "884068.TI": IndustryETF("516970.SH", "建筑施工与基建行业宽口径代理"),
    # 机床工具：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884069.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 磨具磨料：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884071.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 制冷空调设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884073.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他通用设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884074.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 金属制品：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884075.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 纺织服装设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884076.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 农用机械：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884078.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 能源及重型设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884080.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 印刷包装机械：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884081.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他专用设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884082.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 楼宇设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884083.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 电气自控设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884086.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 输变电设备：电网设备产业链代理。
    "884088.TI": IndustryETF("159326.SZ", "电网设备产业链代理"),
    # 线缆部件及其他：电网设备产业链代理。
    "884089.TI": IndustryETF("159326.SZ", "电网设备产业链代理"),
    # 分立器件：半导体产业链代理。
    "884090.TI": IndustryETF("512480.SH", "半导体产业链代理"),
    # 半导体材料：半导体产业链代理。
    "884091.TI": IndustryETF("512480.SH", "半导体产业链代理"),
    # 印制电路板：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884092.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 被动元件：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884093.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 面板：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884094.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # LED：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884095.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 光学元件：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884096.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 消费电子零部件及组装：消费电子产业链代理。
    "884098.TI": IndustryETF("159732.SZ", "消费电子产业链代理"),
    # 乘用车：乘用车不等同新能源车，缺少动力类型证据。
    "884099.TI": IndustryETF(None, "乘用车不等同新能源车，缺少动力类型证据"),
    # 商用载货车：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884100.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 商用载客车：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884101.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他运输设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884106.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 汽车服务：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884107.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 冰洗：家电行业代理。
    "884112.TI": IndustryETF("159996.SZ", "家电行业代理"),
    # 空调：家电行业代理。
    "884113.TI": IndustryETF("159996.SZ", "家电行业代理"),
    # 家电零部件：家电行业代理。
    "884116.TI": IndustryETF("159996.SZ", "家电行业代理"),
    # 彩电：家电行业代理。
    "884117.TI": IndustryETF("159996.SZ", "家电行业代理"),
    # 其他黑色家电：家电行业代理。
    "884118.TI": IndustryETF("159996.SZ", "家电行业代理"),
    # 其他酒类：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884119.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 软饮料：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884120.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 肉制品：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884123.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 调味发酵品：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884124.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 乳品：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884125.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 其他食品：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884126.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 棉纺：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884128.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 印染：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884130.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 辅料：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884131.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他纺织：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884132.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 鞋帽及其他：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884136.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 家纺：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884137.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他家居用品：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884140.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 饰品：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884141.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 文娱用品：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884142.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 原料药：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884143.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 化学制剂：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884144.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 医疗设备：医疗器械与服务行业代理，不扩大到中药及药品流通。
    "884145.TI": IndustryETF("512170.SH", "医疗器械与服务行业代理，不扩大到中药及药品流通"),
    # 火电：电力运营行业代理，不等同于设备制造。
    "884146.TI": IndustryETF("159611.SZ", "电力运营行业代理，不等同于设备制造"),
    # 水电：电力运营行业代理，不等同于设备制造。
    "884147.TI": IndustryETF("159611.SZ", "电力运营行业代理，不等同于设备制造"),
    # 热力：电力运营行业代理，不等同于设备制造。
    "884149.TI": IndustryETF("159611.SZ", "电力运营行业代理，不等同于设备制造"),
    # 新能源发电：电力运营行业代理，不等同于设备制造。
    "884150.TI": IndustryETF("159611.SZ", "电力运营行业代理，不等同于设备制造"),
    # 港口：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884153.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 高速公路：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884154.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 铁路运输：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884155.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 机场：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884156.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 航空运输：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884157.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 百货零售：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884160.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 专业连锁：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884161.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 商业物业经营：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884162.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 人工景点：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884163.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 自然景点：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884164.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 旅游综合：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884165.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 酒店：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884167.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 餐饮：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884168.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 电视广播：传媒行业代理。
    "884172.TI": IndustryETF("512980.SH", "传媒行业代理"),
    # 出版：传媒行业代理。
    "884176.TI": IndustryETF("512980.SH", "传媒行业代理"),
    # 广告营销：传媒行业代理。
    "884178.TI": IndustryETF("512980.SH", "传媒行业代理"),
    # 航天装备：航空航天装备行业代理。
    "884180.TI": IndustryETF("563380.SH", "航空航天装备行业代理"),
    # 航空装备：航空航天装备行业代理。
    "884181.TI": IndustryETF("563380.SH", "航空航天装备行业代理"),
    # 地面兵装：国防军工行业代理。
    "884182.TI": IndustryETF("512660.SH", "国防军工行业代理"),
    # 航海装备：国防军工行业代理。
    "884183.TI": IndustryETF("512660.SH", "国防军工行业代理"),
    # 特钢：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884184.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他小金属：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884186.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 啤酒：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884189.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 航运：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884191.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 仪器仪表：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884192.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 医药流通：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884199.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 公交：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884200.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 住宅开发：房地产行业代理。
    "884202.TI": IndustryETF("512200.SH", "房地产行业代理"),
    # 产业地产：房地产行业代理。
    "884203.TI": IndustryETF("512200.SH", "房地产行业代理"),
    # 其他计算机设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884207.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 钛白粉：化工行业宽口径代理。
    "884209.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 食品及饲料添加剂：化工行业宽口径代理。
    "884210.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 有机硅：化工行业宽口径代理。
    "884211.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 合成树脂：化工行业宽口径代理。
    "884212.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 膜材料：化工行业宽口径代理。
    "884213.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 冶钢原料：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884214.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 稀土：稀土行业代理。
    "884215.TI": IndustryETF("516150.SH", "稀土行业代理"),
    # 工程咨询服务：建筑施工与基建行业宽口径代理。
    "884217.TI": IndustryETF("516970.SH", "建筑施工与基建行业宽口径代理"),
    # 机器人：机器人行业代理，不把全部自动化设备推断为机器人。
    "884218.TI": IndustryETF("562500.SH", "机器人行业代理，不把全部自动化设备推断为机器人"),
    # 工控设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884219.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 激光设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884220.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他自动化设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884221.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 集成电路制造：半导体产业链代理。
    "884227.TI": IndustryETF("512480.SH", "半导体产业链代理"),
    # 集成电路封测：半导体产业链代理。
    "884228.TI": IndustryETF("512480.SH", "半导体产业链代理"),
    # 半导体设备：半导体产业链代理。
    "884229.TI": IndustryETF("512480.SH", "半导体产业链代理"),
    # 品牌消费电子：消费电子产业链代理。
    "884230.TI": IndustryETF("159732.SZ", "消费电子产业链代理"),
    # 休闲食品：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884233.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 服装：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884234.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 印刷：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884235.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 包装：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884236.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 瓷砖地板：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884237.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 血液制品：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884238.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 疫苗：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884239.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 其他生物制品：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884240.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 医疗耗材：医疗器械与服务行业代理，不扩大到中药及药品流通。
    "884242.TI": IndustryETF("512170.SH", "医疗器械与服务行业代理，不扩大到中药及药品流通"),
    # 体外诊断：医疗器械与服务行业代理，不扩大到中药及药品流通。
    "884243.TI": IndustryETF("512170.SH", "医疗器械与服务行业代理，不扩大到中药及药品流通"),
    # 医疗研发外包：医疗器械与服务行业代理，不扩大到中药及药品流通。
    "884244.TI": IndustryETF("512170.SH", "医疗器械与服务行业代理，不扩大到中药及药品流通"),
    # 其他医疗服务：医疗器械与服务行业代理，不扩大到中药及药品流通。
    "884245.TI": IndustryETF("512170.SH", "医疗器械与服务行业代理，不扩大到中药及药品流通"),
    # 电能综合服务：电力运营行业代理，不等同于设备制造。
    "884246.TI": IndustryETF("159611.SZ", "电力运营行业代理，不等同于设备制造"),
    # 商业地产：房地产行业代理。
    "884247.TI": IndustryETF("512200.SH", "房地产行业代理"),
    # 房地产服务：房地产行业代理。
    "884248.TI": IndustryETF("512200.SH", "房地产行业代理"),
    # 国有大型银行：银行行业代理。
    "884249.TI": IndustryETF("512800.SH", "银行行业代理"),
    # 股份制银行：银行行业代理。
    "884250.TI": IndustryETF("512800.SH", "银行行业代理"),
    # 城商行：银行行业代理。
    "884251.TI": IndustryETF("512800.SH", "银行行业代理"),
    # 农商行：银行行业代理。
    "884252.TI": IndustryETF("512800.SH", "银行行业代理"),
    # 旅游零售：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884254.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 专业服务：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884257.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 体育：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884258.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 数字媒体：传媒行业代理。
    "884261.TI": IndustryETF("512980.SH", "传媒行业代理"),
    # 通信网络设备及器件：通信设备产业链代理，不扩大到电信运营商。
    "884262.TI": IndustryETF("515880.SH", "通信设备产业链代理，不扩大到电信运营商"),
    # 通信线缆及配套：通信设备产业链代理，不扩大到电信运营商。
    "884263.TI": IndustryETF("515880.SH", "通信设备产业链代理，不扩大到电信运营商"),
    # 通信终端及配件：通信设备产业链代理，不扩大到电信运营商。
    "884264.TI": IndustryETF("515880.SH", "通信设备产业链代理，不扩大到电信运营商"),
    # 其他通信设备：通信设备产业链代理，不扩大到电信运营商。
    "884265.TI": IndustryETF("515880.SH", "通信设备产业链代理，不扩大到电信运营商"),
    # 大气治理：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884267.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 水务及水治理：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884268.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 固废治理：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884269.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 综合环境治理：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884270.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 个护用品：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884271.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 化妆品：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884272.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 医疗美容：医疗器械与服务行业代理，不扩大到中药及药品流通。
    "884273.TI": IndustryETF("512170.SH", "医疗器械与服务行业代理，不扩大到中药及药品流通"),
    # 生猪养殖：农业产业链代理。
    "884275.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 肉鸡养殖：农业产业链代理。
    "884276.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 其他养殖：农业产业链代理。
    "884277.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 畜禽饲料：农业产业链代理。
    "884278.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 水产饲料：农业产业链代理。
    "884279.TI": IndustryETF("159825.SZ", "农业产业链代理"),
    # 宠物食品：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884280.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 煤化工：化工行业宽口径代理。
    "884281.TI": IndustryETF("516020.SH", "化工行业宽口径代理"),
    # 钨：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884282.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 钼：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884283.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 钴：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884284.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 镍：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884285.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 锂：有色金属行业代理，不以稀土ETF代表所有小金属。
    "884286.TI": IndustryETF("512400.SH", "有色金属行业代理，不以稀土ETF代表所有小金属"),
    # 数字芯片设计：半导体产业链代理。
    "884287.TI": IndustryETF("512480.SH", "半导体产业链代理"),
    # 模拟芯片设计：半导体产业链代理。
    "884288.TI": IndustryETF("512480.SH", "半导体产业链代理"),
    # 车身附件及饰件：汽车零部件行业代理。
    "884289.TI": IndustryETF("159565.SZ", "汽车零部件行业代理"),
    # 底盘与发动机系统：汽车零部件行业代理。
    "884290.TI": IndustryETF("159565.SZ", "汽车零部件行业代理"),
    # 轮胎轮毂：汽车零部件行业代理。
    "884291.TI": IndustryETF("159565.SZ", "汽车零部件行业代理"),
    # 其他汽车零部件：汽车零部件行业代理。
    "884292.TI": IndustryETF("159565.SZ", "汽车零部件行业代理"),
    # 汽车电子电气系统：汽车零部件行业代理。
    "884293.TI": IndustryETF("159565.SZ", "汽车零部件行业代理"),
    # 安防设备：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884294.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 垂直应用软件：软件行业代理；IT服务仅使用软件生态宽口径代理。
    "884295.TI": IndustryETF("159852.SZ", "软件行业代理；IT服务仅使用软件生态宽口径代理"),
    # 横向通用软件：软件行业代理；IT服务仅使用软件生态宽口径代理。
    "884296.TI": IndustryETF("159852.SZ", "软件行业代理；IT服务仅使用软件生态宽口径代理"),
    # 预加工食品：消费行业宽口径代理，仅表达食品饮料及日常消费背景。
    "884297.TI": IndustryETF("159928.SZ", "消费行业宽口径代理，仅表达食品饮料及日常消费背景"),
    # 成品家居：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884298.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 定制家居：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884299.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 药店：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884300.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 医院：医疗器械与服务行业代理，不扩大到中药及药品流通。
    "884301.TI": IndustryETF("512170.SH", "医疗器械与服务行业代理，不扩大到中药及药品流通"),
    # 硅料硅片：光伏产业链代理。
    "884302.TI": IndustryETF("515790.SH", "光伏产业链代理"),
    # 光伏电池组件：光伏产业链代理。
    "884303.TI": IndustryETF("515790.SH", "光伏产业链代理"),
    # 逆变器：光伏产业链代理。
    "884304.TI": IndustryETF("515790.SH", "光伏产业链代理"),
    # 光伏辅材：光伏产业链代理。
    "884305.TI": IndustryETF("515790.SH", "光伏产业链代理"),
    # 光伏加工设备：光伏产业链代理。
    "884306.TI": IndustryETF("515790.SH", "光伏产业链代理"),
    # 风电整机：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884307.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 风电零部件：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884308.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 锂电池：电池产业链代理，不推断个股具体储能收入占比。
    "884309.TI": IndustryETF("159566.SZ", "电池产业链代理，不推断个股具体储能收入占比"),
    # 电池化学品：电池产业链代理，不推断个股具体储能收入占比。
    "884310.TI": IndustryETF("159566.SZ", "电池产业链代理，不推断个股具体储能收入占比"),
    # 锂电专用设备：电池产业链代理，不推断个股具体储能收入占比。
    "884311.TI": IndustryETF("159566.SZ", "电池产业链代理，不推断个股具体储能收入占比"),
    # 其他电池：电池产业链代理，不推断个股具体储能收入占比。
    "884312.TI": IndustryETF("159566.SZ", "电池产业链代理，不推断个股具体储能收入占比"),
    # 电信运营商：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884313.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 通信工程及服务：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884314.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
    # 通信应用增值服务：现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖。
    "884315.TI": IndustryETF(None, "现有ETF池无范围足够匹配的行业代理，不借邻近主题或宽基凑覆盖"),
}


def resolve_industry_etf(market: str, industry: str, *, sector: str | None = None) -> IndustryETF:
    """Resolve an exact source key. CN industry is a code, US industry is a name."""
    if market == "US":
        return US_INDUSTRY_ETF.get((sector, industry), IndustryETF(None, "未审核的美股行业组合，不按sector自动回退"))
    if market == "CN":
        return CN_INDUSTRY_ETF.get(industry, IndustryETF(None, "未审核的A股行业代码，不按名称猜测"))
    return IndustryETF(None, "当前仅审核CN/US行业，其他市场保持未关联")
