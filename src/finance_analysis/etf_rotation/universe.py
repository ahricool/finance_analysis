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

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


ETF_UNIVERSE: tuple[ETFUniverseMember, ...] = (
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
)


def enabled_etfs() -> tuple[ETFUniverseMember, ...]:
    return tuple(member for member in ETF_UNIVERSE if member.enabled)


def universe_by_code() -> dict[str, ETFUniverseMember]:
    return {member.code: member for member in ETF_UNIVERSE}


def _validate_universe() -> None:
    codes = [member.code for member in ETF_UNIVERSE]
    if len(codes) != len(set(codes)):
        raise ValueError("ETF Rotation universe codes must be unique")
    for member in ETF_UNIVERSE:
        validate_market_data_code("CN", member.code)
        if member.enabled and not all((member.category, member.theme, member.risk_group)):
            raise ValueError(f"Enabled ETF {member.code} is missing classification metadata")


_validate_universe()

__all__ = ["ETF_UNIVERSE", "ETFUniverseMember", "enabled_etfs", "universe_by_code"]
