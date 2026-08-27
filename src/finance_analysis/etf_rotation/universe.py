"""Static V1 ETF universe shared by synchronization and strategy evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from finance_analysis.database.models.stock import validate_market_data_code


@dataclass(frozen=True)
class ETFUniverseMember:
    code: str
    name: str
    category: str
    theme: str
    risk_group: str
    enabled: bool = True
    market: str = "CN"

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


CN_ETF_UNIVERSE: tuple[ETFUniverseMember, ...] = (
    ETFUniverseMember("588000.SH", "科创50ETF", "BROAD_INDEX", "STAR50", "BROAD_GROWTH"),
    ETFUniverseMember("159915.SZ", "创业板ETF", "BROAD_INDEX", "CHINEXT", "BROAD_GROWTH"),
    ETFUniverseMember("512800.SH", "银行ETF", "FINANCE", "BANK", "FINANCE"),
    ETFUniverseMember("512880.SH", "证券ETF", "FINANCE", "BROKER", "FINANCE"),
    ETFUniverseMember("159851.SZ", "金融科技ETF", "FINANCE", "FINTECH", "FINANCE"),
    ETFUniverseMember("512200.SH", "房地产ETF", "REAL_ESTATE_INFRA", "REAL_ESTATE", "REAL_ESTATE_INFRA"),
    ETFUniverseMember("516970.SH", "基建ETF", "REAL_ESTATE_INFRA", "INFRASTRUCTURE", "REAL_ESTATE_INFRA"),
    ETFUniverseMember("159928.SZ", "消费ETF", "CONSUMER", "CONSUMER", "CONSUMER"),
    ETFUniverseMember("512690.SH", "酒ETF", "CONSUMER", "LIQUOR", "CONSUMER"),
    ETFUniverseMember("159996.SZ", "家电ETF", "CONSUMER", "HOME_APPLIANCE", "CONSUMER"),
    ETFUniverseMember("512170.SH", "医疗ETF", "HEALTHCARE", "MEDICAL", "HEALTHCARE"),
    ETFUniverseMember("159992.SZ", "创新药ETF", "HEALTHCARE", "INNOVATIVE_DRUG", "HEALTHCARE"),
    ETFUniverseMember("512400.SH", "有色金属ETF", "RESOURCE", "NONFERROUS", "RESOURCE"),
    ETFUniverseMember("517520.SH", "黄金股ETF", "RESOURCE", "GOLD_MINERS", "RESOURCE"),
    ETFUniverseMember("516150.SH", "稀土ETF", "RESOURCE", "RARE_EARTH", "RESOURCE"),
    ETFUniverseMember("515220.SH", "煤炭ETF", "RESOURCE", "COAL", "RESOURCE"),
    ETFUniverseMember("516020.SH", "化工ETF", "RESOURCE", "CHEMICAL", "RESOURCE"),
    ETFUniverseMember("159611.SZ", "电力ETF", "UTILITY", "POWER", "UTILITY"),
    ETFUniverseMember("159825.SZ", "农业ETF", "AGRICULTURE", "AGRICULTURE", "AGRICULTURE"),
    ETFUniverseMember("512480.SH", "半导体ETF", "TECHNOLOGY", "SEMICONDUCTOR", "TECH_HARDWARE"),
    ETFUniverseMember("159995.SZ", "芯片ETF", "TECHNOLOGY", "CHIP", "TECH_HARDWARE"),
    ETFUniverseMember("515880.SH", "通信ETF", "TECHNOLOGY", "COMMUNICATION", "TECH_HARDWARE"),
    ETFUniverseMember("159732.SZ", "消费电子ETF", "TECHNOLOGY", "CONSUMER_ELECTRONICS", "TECH_HARDWARE"),
    ETFUniverseMember("159819.SZ", "人工智能ETF", "TECHNOLOGY", "AI", "TECH_SOFTWARE"),
    ETFUniverseMember("516510.SH", "云计算ETF", "TECHNOLOGY", "CLOUD_COMPUTING", "TECH_SOFTWARE"),
    ETFUniverseMember("159852.SZ", "软件ETF", "TECHNOLOGY", "SOFTWARE", "TECH_SOFTWARE"),
    ETFUniverseMember("159869.SZ", "游戏ETF", "TMT", "GAME", "TECH_SOFTWARE"),
    ETFUniverseMember("512980.SH", "传媒ETF", "TMT", "MEDIA", "TECH_SOFTWARE"),
    ETFUniverseMember("562500.SH", "机器人ETF", "ADVANCED_MANUFACTURING", "ROBOT", "ADVANCED_MANUFACTURING"),
    ETFUniverseMember(
        "515970.SH",
        "工程机械ETF",
        "ADVANCED_MANUFACTURING",
        "CONSTRUCTION_MACHINERY",
        "ADVANCED_MANUFACTURING",
    ),
    ETFUniverseMember("515030.SH", "新能源车ETF", "AUTO", "NEW_ENERGY_VEHICLE", "NEW_ENERGY_AUTO"),
    ETFUniverseMember("516520.SH", "智能驾驶ETF", "AUTO", "AUTONOMOUS_DRIVING", "NEW_ENERGY_AUTO"),
    ETFUniverseMember("159565.SZ", "汽车零部件ETF", "AUTO", "AUTO_PARTS", "NEW_ENERGY_AUTO"),
    ETFUniverseMember("159566.SZ", "储能电池ETF", "NEW_ENERGY", "ENERGY_STORAGE", "NEW_ENERGY"),
    ETFUniverseMember("515790.SH", "光伏ETF", "NEW_ENERGY", "PHOTOVOLTAIC", "NEW_ENERGY"),
    ETFUniverseMember("159326.SZ", "电网设备ETF", "NEW_ENERGY", "POWER_GRID", "NEW_ENERGY"),
    ETFUniverseMember("512660.SH", "军工ETF", "DEFENSE_SPACE", "DEFENSE", "DEFENSE_SPACE"),
    ETFUniverseMember("563230.SH", "卫星ETF", "DEFENSE_SPACE", "SATELLITE", "DEFENSE_SPACE"),
    ETFUniverseMember("563380.SH", "航空航天ETF", "DEFENSE_SPACE", "AEROSPACE", "DEFENSE_SPACE"),
    ETFUniverseMember("563320.SH", "通用航空ETF", "DEFENSE_SPACE", "LOW_ALTITUDE_ECONOMY", "DEFENSE_SPACE"),
    ETFUniverseMember("159941.SZ", "广发纳指100ETF", "OVERSEAS_INDEX", "NASDAQ100", "US_GROWTH"),
    ETFUniverseMember("513650.SH", "南方标普500ETF", "OVERSEAS_INDEX", "SP500", "US_LARGE_CAP"),
)

# Backward-compatible name for the original A-share universe.
ETF_UNIVERSE = CN_ETF_UNIVERSE

US_ETF_UNIVERSE: tuple[ETFUniverseMember, ...] = (
    ETFUniverseMember("SPY.US", "S&P 500", "BROAD_MARKET", "LARGE_CAP", "BROAD_LARGE_CAP", market="US"),
    ETFUniverseMember("QQQ.US", "Nasdaq-100", "BROAD_MARKET", "GROWTH", "BROAD_LARGE_CAP", market="US"),
    ETFUniverseMember("IWM.US", "Russell 2000", "BROAD_MARKET", "SMALL_CAP", "BROAD_SMALL_CAP", market="US"),
    ETFUniverseMember("XLK.US", "Technology", "GICS_SECTOR", "TECHNOLOGY", "GICS_CORE_TECH", market="US"),
    ETFUniverseMember("XLF.US", "Financials", "GICS_SECTOR", "FINANCIALS", "GICS_CORE_FINANCE", market="US"),
    ETFUniverseMember("XLV.US", "Health Care", "GICS_SECTOR", "HEALTHCARE", "GICS_CORE_HEALTHCARE", market="US"),
    ETFUniverseMember("XLI.US", "Industrials", "GICS_SECTOR", "INDUSTRIALS", "GICS_CORE_INDUSTRIAL", market="US"),
    ETFUniverseMember("XLE.US", "Energy", "GICS_SECTOR", "ENERGY", "GICS_CORE_ENERGY", market="US"),
    ETFUniverseMember("XLB.US", "Materials", "GICS_SECTOR", "MATERIALS", "GICS_CORE_MATERIALS", market="US"),
    ETFUniverseMember(
        "XLY.US", "Consumer Discretionary", "GICS_SECTOR", "CONSUMER_DISCRETIONARY", "GICS_CORE_CONSUMER", market="US"
    ),
    ETFUniverseMember(
        "XLP.US", "Consumer Staples", "GICS_SECTOR", "CONSUMER_STAPLES", "GICS_CORE_CONSUMER", market="US"
    ),
    ETFUniverseMember(
        "XLC.US",
        "Communication Services",
        "GICS_SECTOR",
        "COMMUNICATION_SERVICES",
        "GICS_CORE_COMMUNICATION",
        market="US",
    ),
    ETFUniverseMember("XLU.US", "Utilities", "GICS_SECTOR", "UTILITIES", "GICS_CORE_UTILITY", market="US"),
    ETFUniverseMember("XLRE.US", "Real Estate", "GICS_SECTOR", "REAL_ESTATE", "GICS_CORE_REAL_ESTATE", market="US"),
    ETFUniverseMember("SMH.US", "Semiconductor", "AI_TECHNOLOGY", "SEMICONDUCTOR", "SEMICONDUCTOR", market="US"),
    ETFUniverseMember(
        "XSD.US",
        "Equal Weight Semiconductor",
        "AI_TECHNOLOGY",
        "EQUAL_WEIGHT_SEMICONDUCTOR",
        "SEMICONDUCTOR",
        market="US",
    ),
    ETFUniverseMember(
        "AIQ.US", "Artificial Intelligence", "AI_TECHNOLOGY", "ARTIFICIAL_INTELLIGENCE", "AI_INFRA", market="US"
    ),
    ETFUniverseMember("IGV.US", "Software", "AI_TECHNOLOGY", "SOFTWARE", "SOFTWARE", market="US"),
    ETFUniverseMember("CIBR.US", "Cybersecurity", "AI_TECHNOLOGY", "CYBERSECURITY", "SOFTWARE", market="US"),
    ETFUniverseMember(
        "DTCR.US", "Data Center / Digital Infrastructure", "AI_TECHNOLOGY", "DATA_CENTER", "AI_INFRA", market="US"
    ),
    ETFUniverseMember("BOTZ.US", "Robotics / Physical AI", "AI_TECHNOLOGY", "ROBOTICS", "AUTOMATION", market="US"),
    ETFUniverseMember("QTUM.US", "Quantum Computing", "AI_TECHNOLOGY", "QUANTUM_COMPUTING", "AI_INFRA", market="US"),
    ETFUniverseMember(
        "XAR.US", "Aerospace & Defense", "DEFENSE_SPACE", "AEROSPACE_DEFENSE", "DEFENSE_SPACE", market="US"
    ),
    ETFUniverseMember(
        "SHLD.US", "Defense Technology", "DEFENSE_SPACE", "DEFENSE_TECHNOLOGY", "DEFENSE_SPACE", market="US"
    ),
    ETFUniverseMember("UFO.US", "Commercial Space", "DEFENSE_SPACE", "COMMERCIAL_SPACE", "DEFENSE_SPACE", market="US"),
    ETFUniverseMember("KBE.US", "Banks", "FINANCIAL_SUBSECTOR", "BANKS", "FINANCE", market="US"),
    ETFUniverseMember("KRE.US", "Regional Banks", "FINANCIAL_SUBSECTOR", "REGIONAL_BANKS", "FINANCE", market="US"),
    ETFUniverseMember("KIE.US", "Insurance", "FINANCIAL_SUBSECTOR", "INSURANCE", "FINANCE", market="US"),
    ETFUniverseMember("KCE.US", "Capital Markets", "FINANCIAL_SUBSECTOR", "CAPITAL_MARKETS", "FINANCE", market="US"),
    ETFUniverseMember("XBI.US", "Biotechnology", "HEALTHCARE", "BIOTECHNOLOGY", "HEALTHCARE", market="US"),
    ETFUniverseMember("XPH.US", "Pharmaceuticals", "HEALTHCARE", "PHARMACEUTICALS", "HEALTHCARE", market="US"),
    ETFUniverseMember(
        "XHE.US", "Health Care Equipment", "HEALTHCARE", "HEALTHCARE_EQUIPMENT", "HEALTHCARE", market="US"
    ),
    ETFUniverseMember("XHS.US", "Health Care Services", "HEALTHCARE", "HEALTHCARE_SERVICES", "HEALTHCARE", market="US"),
    ETFUniverseMember("IHI.US", "Medical Devices", "HEALTHCARE", "MEDICAL_DEVICES", "HEALTHCARE", market="US"),
    ETFUniverseMember(
        "PAVE.US", "US Infrastructure", "INDUSTRIAL_CONSUMER", "INFRASTRUCTURE", "INDUSTRIAL", market="US"
    ),
    ETFUniverseMember("XTN.US", "Transportation", "INDUSTRIAL_CONSUMER", "TRANSPORTATION", "INDUSTRIAL", market="US"),
    ETFUniverseMember("XHB.US", "Homebuilders", "INDUSTRIAL_CONSUMER", "HOMEBUILDERS", "INDUSTRIAL", market="US"),
    ETFUniverseMember("XRT.US", "Retail", "INDUSTRIAL_CONSUMER", "RETAIL", "CONSUMER", market="US"),
    ETFUniverseMember(
        "XOP.US", "Oil & Gas Exploration & Production", "ENERGY_POWER", "OIL_GAS_EXPLORATION", "ENERGY", market="US"
    ),
    ETFUniverseMember("XES.US", "Oil Services", "ENERGY_POWER", "OIL_SERVICES", "ENERGY", market="US"),
    ETFUniverseMember(
        "MLPX.US", "Energy Infrastructure", "ENERGY_POWER", "ENERGY_INFRASTRUCTURE", "ENERGY", market="US"
    ),
    ETFUniverseMember(
        "URA.US", "Uranium / Nuclear Fuel", "ENERGY_POWER", "URANIUM_NUCLEAR", "POWER_NUCLEAR", market="US"
    ),
    ETFUniverseMember(
        "ZAP.US", "US Electrification / Power Grid", "ENERGY_POWER", "POWER_GRID", "POWER_NUCLEAR", market="US"
    ),
    ETFUniverseMember("XME.US", "Metals & Mining", "METALS_RESOURCES", "METALS_MINING", "METALS", market="US"),
    ETFUniverseMember("COPX.US", "Copper Miners", "METALS_RESOURCES", "COPPER_MINERS", "METALS", market="US"),
    ETFUniverseMember("GDX.US", "Gold Miners", "METALS_RESOURCES", "GOLD_MINERS", "METALS", market="US"),
    ETFUniverseMember("SIL.US", "Silver Miners", "METALS_RESOURCES", "SILVER_MINERS", "METALS", market="US"),
    ETFUniverseMember("TAN.US", "Solar", "OTHER_THEME", "SOLAR", "CLEAN_ENERGY", market="US"),
    ETFUniverseMember("FDN.US", "Internet", "OTHER_THEME", "INTERNET", "CONSUMER", market="US"),
)


def normalize_etf_market(market: str = "CN") -> str:
    normalized = str(market or "").strip().upper()
    if normalized not in {"CN", "US"}:
        raise ValueError(f"Unsupported ETF Rotation market={market!r}; expected CN or US")
    return normalized


def get_etf_universe(market: str = "CN") -> tuple[ETFUniverseMember, ...]:
    normalized = normalize_etf_market(market)
    return ETF_UNIVERSE if normalized == "CN" else US_ETF_UNIVERSE


def enabled_etfs(market: str = "CN") -> tuple[ETFUniverseMember, ...]:
    return tuple(member for member in get_etf_universe(market) if member.enabled)


def universe_by_code(market: str = "CN") -> dict[str, ETFUniverseMember]:
    return {member.code: member for member in get_etf_universe(market)}


def _validate_universe() -> None:
    all_members = CN_ETF_UNIVERSE + US_ETF_UNIVERSE
    codes = [member.code for member in all_members]
    if len(codes) != len(set(codes)):
        raise ValueError("ETF Rotation universe codes must be unique")
    for member in all_members:
        normalized_market = normalize_etf_market(member.market)
        validate_market_data_code(normalized_market, member.code)
        if member.enabled and not all((member.category, member.theme, member.risk_group)):
            raise ValueError(f"Enabled ETF {member.code} is missing classification metadata")


_validate_universe()

__all__ = [
    "CN_ETF_UNIVERSE",
    "ETF_UNIVERSE",
    "ETFUniverseMember",
    "US_ETF_UNIVERSE",
    "enabled_etfs",
    "get_etf_universe",
    "normalize_etf_market",
    "universe_by_code",
]
