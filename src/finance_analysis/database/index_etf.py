"""Curated Index ETF pool: the sole seed definition, shared by migrations and explicit seed."""

import sqlalchemy as sa

# Original ETF Rotation members, including their classification metadata.
INDEX_ETF_MEMBERS = {
    "CN": (
        ("588000.SH", "科创50ETF", "BROAD_INDEX", "STAR50", "BROAD_GROWTH"),
        ("159915.SZ", "创业板ETF", "BROAD_INDEX", "CHINEXT", "BROAD_GROWTH"),
        ("512800.SH", "银行ETF", "FINANCE", "BANK", "FINANCE"),
        ("512880.SH", "证券ETF", "FINANCE", "BROKER", "FINANCE"),
        ("159851.SZ", "金融科技ETF", "FINANCE", "FINTECH", "FINANCE"),
        ("512200.SH", "房地产ETF", "REAL_ESTATE_INFRA", "REAL_ESTATE", "REAL_ESTATE_INFRA"),
        ("516970.SH", "基建ETF", "REAL_ESTATE_INFRA", "INFRASTRUCTURE", "REAL_ESTATE_INFRA"),
        ("159928.SZ", "消费ETF", "CONSUMER", "CONSUMER", "CONSUMER"),
        ("512690.SH", "酒ETF", "CONSUMER", "LIQUOR", "CONSUMER"),
        ("159996.SZ", "家电ETF", "CONSUMER", "HOME_APPLIANCE", "CONSUMER"),
        ("512170.SH", "医疗ETF", "HEALTHCARE", "MEDICAL", "HEALTHCARE"),
        ("159992.SZ", "创新药ETF", "HEALTHCARE", "INNOVATIVE_DRUG", "HEALTHCARE"),
        ("512400.SH", "有色金属ETF", "RESOURCE", "NONFERROUS", "RESOURCE"),
        ("517520.SH", "黄金股ETF", "RESOURCE", "GOLD_MINERS", "RESOURCE"),
        ("516150.SH", "稀土ETF", "RESOURCE", "RARE_EARTH", "RESOURCE"),
        ("515220.SH", "煤炭ETF", "RESOURCE", "COAL", "RESOURCE"),
        ("516020.SH", "化工ETF", "RESOURCE", "CHEMICAL", "RESOURCE"),
        ("159611.SZ", "电力ETF", "UTILITY", "POWER", "UTILITY"),
        ("159825.SZ", "农业ETF", "AGRICULTURE", "AGRICULTURE", "AGRICULTURE"),
        ("512480.SH", "半导体ETF", "TECHNOLOGY", "SEMICONDUCTOR", "TECH_HARDWARE"),
        ("159995.SZ", "芯片ETF", "TECHNOLOGY", "CHIP", "TECH_HARDWARE"),
        ("515880.SH", "通信ETF", "TECHNOLOGY", "COMMUNICATION", "TECH_HARDWARE"),
        ("159732.SZ", "消费电子ETF", "TECHNOLOGY", "CONSUMER_ELECTRONICS", "TECH_HARDWARE"),
        ("159819.SZ", "人工智能ETF", "TECHNOLOGY", "AI", "TECH_SOFTWARE"),
        ("516510.SH", "云计算ETF", "TECHNOLOGY", "CLOUD_COMPUTING", "TECH_SOFTWARE"),
        ("159852.SZ", "软件ETF", "TECHNOLOGY", "SOFTWARE", "TECH_SOFTWARE"),
        ("159869.SZ", "游戏ETF", "TMT", "GAME", "TECH_SOFTWARE"),
        ("512980.SH", "传媒ETF", "TMT", "MEDIA", "TECH_SOFTWARE"),
        ("562500.SH", "机器人ETF", "ADVANCED_MANUFACTURING", "ROBOT", "ADVANCED_MANUFACTURING"),
        ("515970.SH", "工程机械ETF", "ADVANCED_MANUFACTURING", "CONSTRUCTION_MACHINERY", "ADVANCED_MANUFACTURING"),
        ("515030.SH", "新能源车ETF", "AUTO", "NEW_ENERGY_VEHICLE", "NEW_ENERGY_AUTO"),
        ("516520.SH", "智能驾驶ETF", "AUTO", "AUTONOMOUS_DRIVING", "NEW_ENERGY_AUTO"),
        ("159565.SZ", "汽车零部件ETF", "AUTO", "AUTO_PARTS", "NEW_ENERGY_AUTO"),
        ("159566.SZ", "储能电池ETF", "NEW_ENERGY", "ENERGY_STORAGE", "NEW_ENERGY"),
        ("515790.SH", "光伏ETF", "NEW_ENERGY", "PHOTOVOLTAIC", "NEW_ENERGY"),
        ("159326.SZ", "电网设备ETF", "NEW_ENERGY", "POWER_GRID", "NEW_ENERGY"),
        ("512660.SH", "军工ETF", "DEFENSE_SPACE", "DEFENSE", "DEFENSE_SPACE"),
        ("563230.SH", "卫星ETF", "DEFENSE_SPACE", "SATELLITE", "DEFENSE_SPACE"),
        ("563380.SH", "航空航天ETF", "DEFENSE_SPACE", "AEROSPACE", "DEFENSE_SPACE"),
        ("563320.SH", "通用航空ETF", "DEFENSE_SPACE", "LOW_ALTITUDE_ECONOMY", "DEFENSE_SPACE"),
        ("159941.SZ", "广发纳指100ETF", "OVERSEAS_INDEX", "NASDAQ100", "US_GROWTH"),
        ("513650.SH", "南方标普500ETF", "OVERSEAS_INDEX", "SP500", "US_LARGE_CAP"),
    ),
    "US": (
        ("SPY.US", "S&P 500", "BROAD_MARKET", "LARGE_CAP", "BROAD_LARGE_CAP"),
        ("QQQ.US", "Nasdaq-100", "BROAD_MARKET", "GROWTH", "BROAD_LARGE_CAP"),
        ("IWM.US", "Russell 2000", "BROAD_MARKET", "SMALL_CAP", "BROAD_SMALL_CAP"),
        ("XLK.US", "Technology", "GICS_SECTOR", "TECHNOLOGY", "GICS_CORE_TECH"),
        ("XLF.US", "Financials", "GICS_SECTOR", "FINANCIALS", "GICS_CORE_FINANCE"),
        ("XLV.US", "Health Care", "GICS_SECTOR", "HEALTHCARE", "GICS_CORE_HEALTHCARE"),
        ("XLI.US", "Industrials", "GICS_SECTOR", "INDUSTRIALS", "GICS_CORE_INDUSTRIAL"),
        ("XLE.US", "Energy", "GICS_SECTOR", "ENERGY", "GICS_CORE_ENERGY"),
        ("XLB.US", "Materials", "GICS_SECTOR", "MATERIALS", "GICS_CORE_MATERIALS"),
        ("XLY.US", "Consumer Discretionary", "GICS_SECTOR", "CONSUMER_DISCRETIONARY", "GICS_CORE_CONSUMER"),
        ("XLP.US", "Consumer Staples", "GICS_SECTOR", "CONSUMER_STAPLES", "GICS_CORE_CONSUMER"),
        ("XLC.US", "Communication Services", "GICS_SECTOR", "COMMUNICATION_SERVICES", "GICS_CORE_COMMUNICATION"),
        ("XLU.US", "Utilities", "GICS_SECTOR", "UTILITIES", "GICS_CORE_UTILITY"),
        ("XLRE.US", "Real Estate", "GICS_SECTOR", "REAL_ESTATE", "GICS_CORE_REAL_ESTATE"),
        ("SMH.US", "Semiconductor", "AI_TECHNOLOGY", "SEMICONDUCTOR", "SEMICONDUCTOR"),
        ("XSD.US", "Equal Weight Semiconductor", "AI_TECHNOLOGY", "EQUAL_WEIGHT_SEMICONDUCTOR", "SEMICONDUCTOR"),
        ("AIQ.US", "Artificial Intelligence", "AI_TECHNOLOGY", "ARTIFICIAL_INTELLIGENCE", "AI_INFRA"),
        ("IGV.US", "Software", "AI_TECHNOLOGY", "SOFTWARE", "SOFTWARE"),
        ("CIBR.US", "Cybersecurity", "AI_TECHNOLOGY", "CYBERSECURITY", "SOFTWARE"),
        ("DTCR.US", "Data Center / Digital Infrastructure", "AI_TECHNOLOGY", "DATA_CENTER", "AI_INFRA"),
        ("BOTZ.US", "Robotics / Physical AI", "AI_TECHNOLOGY", "ROBOTICS", "AUTOMATION"),
        ("QTUM.US", "Quantum Computing", "AI_TECHNOLOGY", "QUANTUM_COMPUTING", "AI_INFRA"),
        ("XAR.US", "Aerospace & Defense", "DEFENSE_SPACE", "AEROSPACE_DEFENSE", "DEFENSE_SPACE"),
        ("SHLD.US", "Defense Technology", "DEFENSE_SPACE", "DEFENSE_TECHNOLOGY", "DEFENSE_SPACE"),
        ("UFO.US", "Commercial Space", "DEFENSE_SPACE", "COMMERCIAL_SPACE", "DEFENSE_SPACE"),
        ("KBE.US", "Banks", "FINANCIAL_SUBSECTOR", "BANKS", "FINANCE"),
        ("KRE.US", "Regional Banks", "FINANCIAL_SUBSECTOR", "REGIONAL_BANKS", "FINANCE"),
        ("KIE.US", "Insurance", "FINANCIAL_SUBSECTOR", "INSURANCE", "FINANCE"),
        ("KCE.US", "Capital Markets", "FINANCIAL_SUBSECTOR", "CAPITAL_MARKETS", "FINANCE"),
        ("XBI.US", "Biotechnology", "HEALTHCARE", "BIOTECHNOLOGY", "HEALTHCARE"),
        ("XPH.US", "Pharmaceuticals", "HEALTHCARE", "PHARMACEUTICALS", "HEALTHCARE"),
        ("XHE.US", "Health Care Equipment", "HEALTHCARE", "HEALTHCARE_EQUIPMENT", "HEALTHCARE"),
        ("XHS.US", "Health Care Services", "HEALTHCARE", "HEALTHCARE_SERVICES", "HEALTHCARE"),
        ("IHI.US", "Medical Devices", "HEALTHCARE", "MEDICAL_DEVICES", "HEALTHCARE"),
        ("PAVE.US", "US Infrastructure", "INDUSTRIAL_CONSUMER", "INFRASTRUCTURE", "INDUSTRIAL"),
        ("XTN.US", "Transportation", "INDUSTRIAL_CONSUMER", "TRANSPORTATION", "INDUSTRIAL"),
        ("XHB.US", "Homebuilders", "INDUSTRIAL_CONSUMER", "HOMEBUILDERS", "INDUSTRIAL"),
        ("XRT.US", "Retail", "INDUSTRIAL_CONSUMER", "RETAIL", "CONSUMER"),
        ("XOP.US", "Oil & Gas Exploration & Production", "ENERGY_POWER", "OIL_GAS_EXPLORATION", "ENERGY"),
        ("XES.US", "Oil Services", "ENERGY_POWER", "OIL_SERVICES", "ENERGY"),
        ("MLPX.US", "Energy Infrastructure", "ENERGY_POWER", "ENERGY_INFRASTRUCTURE", "ENERGY"),
        ("URA.US", "Uranium / Nuclear Fuel", "ENERGY_POWER", "URANIUM_NUCLEAR", "POWER_NUCLEAR"),
        ("ZAP.US", "US Electrification / Power Grid", "ENERGY_POWER", "POWER_GRID", "POWER_NUCLEAR"),
        ("XME.US", "Metals & Mining", "METALS_RESOURCES", "METALS_MINING", "METALS"),
        ("COPX.US", "Copper Miners", "METALS_RESOURCES", "COPPER_MINERS", "METALS"),
        ("GDX.US", "Gold Miners", "METALS_RESOURCES", "GOLD_MINERS", "METALS"),
        ("SIL.US", "Silver Miners", "METALS_RESOURCES", "SILVER_MINERS", "METALS"),
        ("TAN.US", "Solar", "OTHER_THEME", "SOLAR", "CLEAN_ENERGY"),
        ("FDN.US", "Internet", "OTHER_THEME", "INTERNET", "CONSUMER"),
    ),
}


def seed_index_etf_universes(connection) -> None:
    """Initialize fresh pools or move existing memberships before deleting old pools."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from finance_analysis.database.models.stock import Instrument
    from finance_analysis.database.models.universe import Universe, UniverseMember

    insert = sqlite_insert if connection.dialect.name == "sqlite" else pg_insert
    for market, members in INDEX_ETF_MEMBERS.items():
        old_key = f"{market.lower()}_etf_rotation"
        key = f"{market.lower()}_index_etf"
        old_id = connection.execute(sa.select(Universe.id).where(Universe.key == old_key)).scalar_one_or_none()
        new_id = connection.execute(sa.select(Universe.id).where(Universe.key == key)).scalar_one_or_none()
        has_members = (
            new_id is not None
            and connection.execute(
                sa.select(UniverseMember.id).where(UniverseMember.universe_id == new_id).limit(1)
            ).first()
            is not None
        )
        old_has_members = (
            old_id is not None
            and connection.execute(
                sa.select(UniverseMember.id).where(UniverseMember.universe_id == old_id).limit(1)
            ).first()
            is not None
        )
        initialize = not has_members and not old_has_members
        # Existing memberships already have valid Instrument FKs. Only fresh
        # pools need identities, and those must exist before any member insert.
        if initialize:
            for code, name, *_ in members:
                connection.execute(
                    insert(Instrument.__table__)
                    .values(
                        market=market,
                        code=code,
                        native_code=code.rsplit(".", 1)[0],
                        name=name,
                        instrument_type="ETF",
                        currency="CNY" if market == "CN" else "USD",
                        listing_status="ACTIVE",
                        source="CURATED",
                        metadata={},
                    )
                    # 0039 labels legacy symbols STOCK. This curated list is
                    # explicit ETF identity, not a provider type inference.
                    .on_conflict_do_update(index_elements=["code"], set_={"instrument_type": "ETF"})
                )
        connection.execute(
            insert(Universe.__table__)
            .values(
                key=key,
                name=f"{market} Index ETF",
                market=market,
                universe_type="STRATEGY",
                enabled=True,
                config={},
            )
            .on_conflict_do_nothing(index_elements=["key"])
        )
        new_id = connection.execute(sa.select(Universe.id).where(Universe.key == key)).scalar_one()
        if old_id is not None:
            connection.execute(
                sa.text("""
                INSERT INTO universe_member (universe_id, instrument_id, source, metadata, created_at, updated_at)
                SELECT :new_id, instrument_id, source, metadata, created_at, updated_at
                FROM universe_member WHERE universe_id = :old_id
                ON CONFLICT (universe_id, instrument_id) DO UPDATE SET
                    source = EXCLUDED.source, metadata = EXCLUDED.metadata
            """),
                {"new_id": new_id, "old_id": old_id},
            )
            missing = connection.execute(
                sa.text("""
                SELECT COUNT(*) FROM universe_member old
                WHERE old.universe_id = :old_id AND NOT EXISTS (
                    SELECT 1 FROM universe_member new
                    WHERE new.universe_id = :new_id AND new.instrument_id = old.instrument_id
                )
            """),
                {"new_id": new_id, "old_id": old_id},
            ).scalar_one()
            if missing:
                raise ValueError(f"Index ETF member copy incomplete: {old_key}")
            _delete_old_pool(connection, old_id)
        if initialize:
            for code, _, category, theme, risk_group in members:
                instrument_id = connection.execute(sa.select(Instrument.id).where(Instrument.code == code)).scalar_one()
                connection.execute(
                    insert(UniverseMember.__table__)
                    .values(
                        universe_id=new_id,
                        instrument_id=instrument_id,
                        source="CURATED",
                        metadata={"category": category, "theme": theme, "risk_group": risk_group},
                    )
                    .on_conflict_do_nothing(index_elements=["universe_id", "instrument_id"])
                )


def _delete_old_pool(connection, old_id: int) -> None:
    """Discard rebuildable Quant rows referencing a retired ETF universe."""
    tables = set(sa.inspect(connection).get_table_names())
    params = {"old_id": old_id}
    if "model_publication" in tables:
        connection.execute(
            sa.text("""
            DELETE FROM model_publication WHERE model_run_id IN (
                SELECT id FROM model_run WHERE universe_id = :old_id
                OR dataset_snapshot_id IN (SELECT id FROM quant_dataset_snapshot WHERE universe_id = :old_id)
            )
        """),
            params,
        )
    if "model_run" in tables:
        connection.execute(
            sa.text("""
            DELETE FROM model_run WHERE universe_id = :old_id
            OR dataset_snapshot_id IN (SELECT id FROM quant_dataset_snapshot WHERE universe_id = :old_id)
        """),
            params,
        )
    for table in ("model_signal", "portfolio_recommendation", "quant_dataset_snapshot", "universe_member"):
        if table in tables:
            connection.execute(sa.text(f"DELETE FROM {table} WHERE universe_id = :old_id"), params)
    connection.execute(
        sa.text("""
        DELETE FROM universe_include WHERE universe_id = :old_id OR included_universe_id = :old_id
    """),
        params,
    )
    connection.execute(sa.text("DELETE FROM universe WHERE id = :old_id"), params)
