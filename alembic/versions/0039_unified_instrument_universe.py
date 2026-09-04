"""Replace portfolio and symbol domains with security master and universes.

Revision ID: 0039_unified_security
Revises: 0038_remove_legacy_minute
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_unified_security"
down_revision: Union[str, Sequence[str], None] = "0038_remove_legacy_minute"
branch_labels = None
depends_on = None

JSON_TYPE = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")

SECURITY_FK_TABLES = (
    "stock_daily", "trend_following_snapshot", "etf_momentum_snapshot", "market_event",
    "event_feature_daily", "daily_feature_snapshot", "model_prediction", "model_signal",
    "portfolio_recommendation_item",
)

UNIVERSES = (
    ("cn_all_a", "全部A股", "CN", "MARKET"),
    ("cn_csi300", "沪深300", "CN", "INDEX"),
    ("cn_csi500", "中证500", "CN", "INDEX"),
    ("cn_csi1000", "中证1000", "CN", "INDEX"),
    ("us_sp500", "S&P 500", "US", "INDEX"),
    ("cn_trend", "A股趋势跟踪", "CN", "STRATEGY"),
    ("us_trend", "美股趋势跟踪", "US", "STRATEGY"),
    ("cn_etf_rotation", "A股ETF轮动", "CN", "STRATEGY"),
    ("us_etf_rotation", "美股ETF轮动", "US", "STRATEGY"),
    ("cn_quant", "A股量化", "CN", "STRATEGY"),
    ("us_quant", "美股量化", "US", "STRATEGY"),
)

# code, name, category, theme, risk_group, market. This is migration-only seed data.
ETF_MEMBERS = [('588000.SH', '科创50ETF', 'BROAD_INDEX', 'STAR50', 'BROAD_GROWTH', 'CN'),
 ('159915.SZ', '创业板ETF', 'BROAD_INDEX', 'CHINEXT', 'BROAD_GROWTH', 'CN'),
 ('512800.SH', '银行ETF', 'FINANCE', 'BANK', 'FINANCE', 'CN'),
 ('512880.SH', '证券ETF', 'FINANCE', 'BROKER', 'FINANCE', 'CN'),
 ('159851.SZ', '金融科技ETF', 'FINANCE', 'FINTECH', 'FINANCE', 'CN'),
 ('512200.SH', '房地产ETF', 'REAL_ESTATE_INFRA', 'REAL_ESTATE', 'REAL_ESTATE_INFRA', 'CN'),
 ('516970.SH', '基建ETF', 'REAL_ESTATE_INFRA', 'INFRASTRUCTURE', 'REAL_ESTATE_INFRA', 'CN'),
 ('159928.SZ', '消费ETF', 'CONSUMER', 'CONSUMER', 'CONSUMER', 'CN'),
 ('512690.SH', '酒ETF', 'CONSUMER', 'LIQUOR', 'CONSUMER', 'CN'),
 ('159996.SZ', '家电ETF', 'CONSUMER', 'HOME_APPLIANCE', 'CONSUMER', 'CN'),
 ('512170.SH', '医疗ETF', 'HEALTHCARE', 'MEDICAL', 'HEALTHCARE', 'CN'),
 ('159992.SZ', '创新药ETF', 'HEALTHCARE', 'INNOVATIVE_DRUG', 'HEALTHCARE', 'CN'),
 ('512400.SH', '有色金属ETF', 'RESOURCE', 'NONFERROUS', 'RESOURCE', 'CN'),
 ('517520.SH', '黄金股ETF', 'RESOURCE', 'GOLD_MINERS', 'RESOURCE', 'CN'),
 ('516150.SH', '稀土ETF', 'RESOURCE', 'RARE_EARTH', 'RESOURCE', 'CN'),
 ('515220.SH', '煤炭ETF', 'RESOURCE', 'COAL', 'RESOURCE', 'CN'),
 ('516020.SH', '化工ETF', 'RESOURCE', 'CHEMICAL', 'RESOURCE', 'CN'),
 ('159611.SZ', '电力ETF', 'UTILITY', 'POWER', 'UTILITY', 'CN'),
 ('159825.SZ', '农业ETF', 'AGRICULTURE', 'AGRICULTURE', 'AGRICULTURE', 'CN'),
 ('512480.SH', '半导体ETF', 'TECHNOLOGY', 'SEMICONDUCTOR', 'TECH_HARDWARE', 'CN'),
 ('159995.SZ', '芯片ETF', 'TECHNOLOGY', 'CHIP', 'TECH_HARDWARE', 'CN'),
 ('515880.SH', '通信ETF', 'TECHNOLOGY', 'COMMUNICATION', 'TECH_HARDWARE', 'CN'),
 ('159732.SZ', '消费电子ETF', 'TECHNOLOGY', 'CONSUMER_ELECTRONICS', 'TECH_HARDWARE', 'CN'),
 ('159819.SZ', '人工智能ETF', 'TECHNOLOGY', 'AI', 'TECH_SOFTWARE', 'CN'),
 ('516510.SH', '云计算ETF', 'TECHNOLOGY', 'CLOUD_COMPUTING', 'TECH_SOFTWARE', 'CN'),
 ('159852.SZ', '软件ETF', 'TECHNOLOGY', 'SOFTWARE', 'TECH_SOFTWARE', 'CN'),
 ('159869.SZ', '游戏ETF', 'TMT', 'GAME', 'TECH_SOFTWARE', 'CN'),
 ('512980.SH', '传媒ETF', 'TMT', 'MEDIA', 'TECH_SOFTWARE', 'CN'),
 ('562500.SH', '机器人ETF', 'ADVANCED_MANUFACTURING', 'ROBOT', 'ADVANCED_MANUFACTURING', 'CN'),
 ('515970.SH', '工程机械ETF', 'ADVANCED_MANUFACTURING', 'CONSTRUCTION_MACHINERY', 'ADVANCED_MANUFACTURING', 'CN'),
 ('515030.SH', '新能源车ETF', 'AUTO', 'NEW_ENERGY_VEHICLE', 'NEW_ENERGY_AUTO', 'CN'),
 ('516520.SH', '智能驾驶ETF', 'AUTO', 'AUTONOMOUS_DRIVING', 'NEW_ENERGY_AUTO', 'CN'),
 ('159565.SZ', '汽车零部件ETF', 'AUTO', 'AUTO_PARTS', 'NEW_ENERGY_AUTO', 'CN'),
 ('159566.SZ', '储能电池ETF', 'NEW_ENERGY', 'ENERGY_STORAGE', 'NEW_ENERGY', 'CN'),
 ('515790.SH', '光伏ETF', 'NEW_ENERGY', 'PHOTOVOLTAIC', 'NEW_ENERGY', 'CN'),
 ('159326.SZ', '电网设备ETF', 'NEW_ENERGY', 'POWER_GRID', 'NEW_ENERGY', 'CN'),
 ('512660.SH', '军工ETF', 'DEFENSE_SPACE', 'DEFENSE', 'DEFENSE_SPACE', 'CN'),
 ('563230.SH', '卫星ETF', 'DEFENSE_SPACE', 'SATELLITE', 'DEFENSE_SPACE', 'CN'),
 ('563380.SH', '航空航天ETF', 'DEFENSE_SPACE', 'AEROSPACE', 'DEFENSE_SPACE', 'CN'),
 ('563320.SH', '通用航空ETF', 'DEFENSE_SPACE', 'LOW_ALTITUDE_ECONOMY', 'DEFENSE_SPACE', 'CN'),
 ('159941.SZ', '广发纳指100ETF', 'OVERSEAS_INDEX', 'NASDAQ100', 'US_GROWTH', 'CN'),
 ('513650.SH', '南方标普500ETF', 'OVERSEAS_INDEX', 'SP500', 'US_LARGE_CAP', 'CN'),
 ('SPY.US', 'S&P 500', 'BROAD_MARKET', 'LARGE_CAP', 'BROAD_LARGE_CAP', 'US'),
 ('QQQ.US', 'Nasdaq-100', 'BROAD_MARKET', 'GROWTH', 'BROAD_LARGE_CAP', 'US'),
 ('IWM.US', 'Russell 2000', 'BROAD_MARKET', 'SMALL_CAP', 'BROAD_SMALL_CAP', 'US'),
 ('XLK.US', 'Technology', 'GICS_SECTOR', 'TECHNOLOGY', 'GICS_CORE_TECH', 'US'),
 ('XLF.US', 'Financials', 'GICS_SECTOR', 'FINANCIALS', 'GICS_CORE_FINANCE', 'US'),
 ('XLV.US', 'Health Care', 'GICS_SECTOR', 'HEALTHCARE', 'GICS_CORE_HEALTHCARE', 'US'),
 ('XLI.US', 'Industrials', 'GICS_SECTOR', 'INDUSTRIALS', 'GICS_CORE_INDUSTRIAL', 'US'),
 ('XLE.US', 'Energy', 'GICS_SECTOR', 'ENERGY', 'GICS_CORE_ENERGY', 'US'),
 ('XLB.US', 'Materials', 'GICS_SECTOR', 'MATERIALS', 'GICS_CORE_MATERIALS', 'US'),
 ('XLY.US', 'Consumer Discretionary', 'GICS_SECTOR', 'CONSUMER_DISCRETIONARY', 'GICS_CORE_CONSUMER', 'US'),
 ('XLP.US', 'Consumer Staples', 'GICS_SECTOR', 'CONSUMER_STAPLES', 'GICS_CORE_CONSUMER', 'US'),
 ('XLC.US', 'Communication Services', 'GICS_SECTOR', 'COMMUNICATION_SERVICES', 'GICS_CORE_COMMUNICATION', 'US'),
 ('XLU.US', 'Utilities', 'GICS_SECTOR', 'UTILITIES', 'GICS_CORE_UTILITY', 'US'),
 ('XLRE.US', 'Real Estate', 'GICS_SECTOR', 'REAL_ESTATE', 'GICS_CORE_REAL_ESTATE', 'US'),
 ('SMH.US', 'Semiconductor', 'AI_TECHNOLOGY', 'SEMICONDUCTOR', 'SEMICONDUCTOR', 'US'),
 ('XSD.US', 'Equal Weight Semiconductor', 'AI_TECHNOLOGY', 'EQUAL_WEIGHT_SEMICONDUCTOR', 'SEMICONDUCTOR', 'US'),
 ('AIQ.US', 'Artificial Intelligence', 'AI_TECHNOLOGY', 'ARTIFICIAL_INTELLIGENCE', 'AI_INFRA', 'US'),
 ('IGV.US', 'Software', 'AI_TECHNOLOGY', 'SOFTWARE', 'SOFTWARE', 'US'),
 ('CIBR.US', 'Cybersecurity', 'AI_TECHNOLOGY', 'CYBERSECURITY', 'SOFTWARE', 'US'),
 ('DTCR.US', 'Data Center / Digital Infrastructure', 'AI_TECHNOLOGY', 'DATA_CENTER', 'AI_INFRA', 'US'),
 ('BOTZ.US', 'Robotics / Physical AI', 'AI_TECHNOLOGY', 'ROBOTICS', 'AUTOMATION', 'US'),
 ('QTUM.US', 'Quantum Computing', 'AI_TECHNOLOGY', 'QUANTUM_COMPUTING', 'AI_INFRA', 'US'),
 ('XAR.US', 'Aerospace & Defense', 'DEFENSE_SPACE', 'AEROSPACE_DEFENSE', 'DEFENSE_SPACE', 'US'),
 ('SHLD.US', 'Defense Technology', 'DEFENSE_SPACE', 'DEFENSE_TECHNOLOGY', 'DEFENSE_SPACE', 'US'),
 ('UFO.US', 'Commercial Space', 'DEFENSE_SPACE', 'COMMERCIAL_SPACE', 'DEFENSE_SPACE', 'US'),
 ('KBE.US', 'Banks', 'FINANCIAL_SUBSECTOR', 'BANKS', 'FINANCE', 'US'),
 ('KRE.US', 'Regional Banks', 'FINANCIAL_SUBSECTOR', 'REGIONAL_BANKS', 'FINANCE', 'US'),
 ('KIE.US', 'Insurance', 'FINANCIAL_SUBSECTOR', 'INSURANCE', 'FINANCE', 'US'),
 ('KCE.US', 'Capital Markets', 'FINANCIAL_SUBSECTOR', 'CAPITAL_MARKETS', 'FINANCE', 'US'),
 ('XBI.US', 'Biotechnology', 'HEALTHCARE', 'BIOTECHNOLOGY', 'HEALTHCARE', 'US'),
 ('XPH.US', 'Pharmaceuticals', 'HEALTHCARE', 'PHARMACEUTICALS', 'HEALTHCARE', 'US'),
 ('XHE.US', 'Health Care Equipment', 'HEALTHCARE', 'HEALTHCARE_EQUIPMENT', 'HEALTHCARE', 'US'),
 ('XHS.US', 'Health Care Services', 'HEALTHCARE', 'HEALTHCARE_SERVICES', 'HEALTHCARE', 'US'),
 ('IHI.US', 'Medical Devices', 'HEALTHCARE', 'MEDICAL_DEVICES', 'HEALTHCARE', 'US'),
 ('PAVE.US', 'US Infrastructure', 'INDUSTRIAL_CONSUMER', 'INFRASTRUCTURE', 'INDUSTRIAL', 'US'),
 ('XTN.US', 'Transportation', 'INDUSTRIAL_CONSUMER', 'TRANSPORTATION', 'INDUSTRIAL', 'US'),
 ('XHB.US', 'Homebuilders', 'INDUSTRIAL_CONSUMER', 'HOMEBUILDERS', 'INDUSTRIAL', 'US'),
 ('XRT.US', 'Retail', 'INDUSTRIAL_CONSUMER', 'RETAIL', 'CONSUMER', 'US'),
 ('XOP.US', 'Oil & Gas Exploration & Production', 'ENERGY_POWER', 'OIL_GAS_EXPLORATION', 'ENERGY', 'US'),
 ('XES.US', 'Oil Services', 'ENERGY_POWER', 'OIL_SERVICES', 'ENERGY', 'US'),
 ('MLPX.US', 'Energy Infrastructure', 'ENERGY_POWER', 'ENERGY_INFRASTRUCTURE', 'ENERGY', 'US'),
 ('URA.US', 'Uranium / Nuclear Fuel', 'ENERGY_POWER', 'URANIUM_NUCLEAR', 'POWER_NUCLEAR', 'US'),
 ('ZAP.US', 'US Electrification / Power Grid', 'ENERGY_POWER', 'POWER_GRID', 'POWER_NUCLEAR', 'US'),
 ('XME.US', 'Metals & Mining', 'METALS_RESOURCES', 'METALS_MINING', 'METALS', 'US'),
 ('COPX.US', 'Copper Miners', 'METALS_RESOURCES', 'COPPER_MINERS', 'METALS', 'US'),
 ('GDX.US', 'Gold Miners', 'METALS_RESOURCES', 'GOLD_MINERS', 'METALS', 'US'),
 ('SIL.US', 'Silver Miners', 'METALS_RESOURCES', 'SILVER_MINERS', 'METALS', 'US'),
 ('TAN.US', 'Solar', 'OTHER_THEME', 'SOLAR', 'CLEAN_ENERGY', 'US'),
 ('FDN.US', 'Internet', 'OTHER_THEME', 'INTERNET', 'CONSUMER', 'US')]


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _constraint_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    names = {item.get("name") for item in inspector.get_unique_constraints(table)}
    names.update(item.get("name") for item in inspector.get_check_constraints(table))
    return {name for name in names if name}


def _index_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table) if item.get("name")}


def upgrade() -> None:
    tables = _tables()
    for table in ("position", "option_contract", "account_cash_balance", "portfolio_account"):
        if table in tables:
            op.drop_table(table)
    if "instrument" in tables:
        op.drop_table("instrument")

    op.rename_table("market_data_symbol", "instrument")
    if "ix_market_data_symbol_sync" in _index_names("instrument"):
        op.drop_index("ix_market_data_symbol_sync", table_name="instrument")
    with op.batch_alter_table("instrument") as batch:
        batch.add_column(sa.Column("native_code", sa.String(32)))
        batch.add_column(sa.Column("instrument_type", sa.String(16)))
        batch.add_column(sa.Column("currency", sa.String(8)))
        batch.add_column(sa.Column("listing_date", sa.Date()))
        batch.add_column(sa.Column("listing_status", sa.String(16)))
        batch.add_column(sa.Column("source", sa.String(32)))
        batch.add_column(sa.Column("metadata", JSON_TYPE, server_default=sa.text("'{}'"), nullable=False))
    op.execute(sa.text("""
        UPDATE instrument SET
            native_code = split_part(code, '.', 1), instrument_type = 'STOCK',
            currency = CASE market WHEN 'CN' THEN 'CNY' WHEN 'HK' THEN 'HKD' ELSE 'USD' END,
            listing_status = 'ACTIVE', source = 'MIGRATION'
    """))
    with op.batch_alter_table("instrument") as batch:
        for column in ("native_code", "instrument_type", "currency", "listing_status", "source"):
            batch.alter_column(column, nullable=False)
        for column in ("enabled", "sync_daily"):
            if column in _columns("instrument"):
                batch.drop_column(column)
        constraints = _constraint_names("instrument")
        if "uix_market_data_symbol_market_code" in constraints:
            batch.drop_constraint("uix_market_data_symbol_market_code", type_="unique")
        if "uix_market_data_symbol_code" in constraints:
            batch.drop_constraint("uix_market_data_symbol_code", type_="unique")
        if "ck_market_data_symbol_code_suffix" in constraints:
            batch.drop_constraint("ck_market_data_symbol_code_suffix", type_="check")
        if "ck_market_data_symbol_market" in constraints:
            batch.drop_constraint("ck_market_data_symbol_market", type_="check")
        batch.create_unique_constraint("uix_instrument_code", ["code"])
        batch.create_check_constraint("ck_instrument_market", "market IN ('US','HK','CN')")
        batch.create_check_constraint(
            "ck_instrument_code_suffix",
            "(market = 'US' AND code LIKE '%.US') OR "
            "(market = 'HK' AND code ~ '^[1-9][0-9]*\\.HK$') OR "
            "(market = 'CN' AND code ~ '^[0-9]{6}\\.(SH|SZ|BJ)$')",
        )
        batch.create_check_constraint("ck_instrument_type", "instrument_type IN ('STOCK','ETF','INDEX')")
        batch.create_check_constraint("ck_instrument_currency", "currency IN ('CNY','USD','HKD')")
        batch.create_check_constraint("ck_instrument_listing_status", "listing_status IN ('ACTIVE','DELISTED')")
        batch.create_index("ix_instrument_market_type_status", ["market", "instrument_type", "listing_status"])

    for table in SECURITY_FK_TABLES:
        if table in _tables() and "symbol_id" in _columns(table):
            op.alter_column(table, "symbol_id", new_column_name="instrument_id")

    if "stock_daily" in _tables():
        with op.batch_alter_table("stock_daily") as batch:
            constraints = _constraint_names("stock_daily")
            if "uix_stock_daily_symbol_date" in constraints:
                batch.drop_constraint("uix_stock_daily_symbol_date", type_="unique")
            if "uix_stock_daily_instrument_date" not in constraints:
                batch.create_unique_constraint(
                    "uix_stock_daily_instrument_date", ["instrument_id", "date"]
                )

    if "quant_universe" in _tables():
        op.rename_table("quant_universe", "universe")
        with op.batch_alter_table("universe") as batch:
            batch.add_column(sa.Column("universe_type", sa.String(16), server_default="INDEX", nullable=False))
            for column in ("description", "is_dynamic", "benchmark_code", "sector_benchmark_mode"):
                if column in _columns("universe"):
                    batch.drop_column(column)
            constraints = _constraint_names("universe")
            if "ck_quant_universe_market" in constraints:
                batch.drop_constraint("ck_quant_universe_market", type_="check")
            batch.create_check_constraint("ck_universe_market", "market IN ('US','HK','CN')")
            batch.create_check_constraint(
                "ck_universe_type", "universe_type IN ('MARKET','INDEX','STRATEGY')"
            )
    else:
        op.create_table(
            "universe", sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(64), nullable=False, unique=True),
            sa.Column("name", sa.String(128), nullable=False), sa.Column("market", sa.String(8), nullable=False),
            sa.Column("universe_type", sa.String(16), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("config", JSON_TYPE, server_default=sa.text("'{}'"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if "quant_universe_member" in _tables():
        op.execute(sa.text("DELETE FROM quant_universe_member WHERE enabled = false OR effective_to IS NOT NULL"))
        op.execute(
            sa.text(
                "DELETE FROM quant_universe_member WHERE id NOT IN "
                "(SELECT MIN(id) FROM quant_universe_member GROUP BY universe_id, symbol_id)"
            )
        )
        op.rename_table("quant_universe_member", "universe_member")
        if "symbol_id" in _columns("universe_member"):
            op.alter_column("universe_member", "symbol_id", new_column_name="instrument_id")
        if "ix_quant_member_active" in _index_names("universe_member"):
            op.drop_index("ix_quant_member_active", table_name="universe_member")
        with op.batch_alter_table("universe_member") as batch:
            batch.add_column(sa.Column("source", sa.String(32), server_default="MIGRATION", nullable=False))
            batch.add_column(sa.Column("metadata", JSON_TYPE, server_default=sa.text("'{}'"), nullable=False))
            constraints = _constraint_names("universe_member")
            if "uix_quant_member_period" in constraints:
                batch.drop_constraint("uix_quant_member_period", type_="unique")
            if "ck_quant_member_dates" in constraints:
                batch.drop_constraint("ck_quant_member_dates", type_="check")
            for column in ("effective_from", "effective_to", "sector_key", "sector_benchmark_code", "weight", "enabled"):
                if column in _columns("universe_member"):
                    batch.drop_column(column)
            batch.create_unique_constraint("uix_universe_member", ["universe_id", "instrument_id"])
    else:
        op.create_table(
            "universe_member", sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("universe_id", sa.Integer(), sa.ForeignKey("universe.id", ondelete="CASCADE"), nullable=False),
            sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instrument.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("metadata", JSON_TYPE, server_default=sa.text("'{}'"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("universe_id", "instrument_id", name="uix_universe_member"),
        )

    op.create_table(
        "universe_include", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("universe_id", sa.Integer(), sa.ForeignKey("universe.id", ondelete="CASCADE"), nullable=False),
        sa.Column("included_universe_id", sa.Integer(), sa.ForeignKey("universe.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("universe_id", "included_universe_id", name="uix_universe_include"),
        sa.CheckConstraint("universe_id <> included_universe_id", name="ck_universe_include_not_self"),
    )

    connection = op.get_bind()
    for key, name, market, universe_type in UNIVERSES:
        connection.execute(sa.text("""
            INSERT INTO universe (key, name, market, universe_type, enabled, config, created_at, updated_at)
            VALUES (:key, :name, :market, :universe_type, true, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name, universe_type=EXCLUDED.universe_type
        """), {"key": key, "name": name, "market": market, "universe_type": universe_type})
    for parent, child in (("cn_trend", "cn_all_a"), ("cn_quant", "cn_csi300"), ("us_quant", "us_sp500")):
        connection.execute(sa.text("""
            INSERT INTO universe_include (universe_id, included_universe_id)
            SELECT p.id, c.id FROM universe p, universe c WHERE p.key=:parent AND c.key=:child
            ON CONFLICT DO NOTHING
        """), {"parent": parent, "child": child})
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text("""
            SELECT setval(pg_get_serial_sequence('instrument', 'id'),
                          COALESCE((SELECT MAX(id) FROM instrument), 1), true)
        """))
    for code, name, category, theme, risk_group, market in ETF_MEMBERS:
        currency = {"CN": "CNY", "US": "USD"}[market]
        connection.execute(sa.text("""
            INSERT INTO instrument (market, code, native_code, name, instrument_type, currency, listing_status, source, metadata, created_at, updated_at)
            VALUES (:market, :code, :native, :name, 'ETF', :currency, 'ACTIVE', 'MIGRATION', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (code) DO UPDATE SET instrument_type='ETF'
        """), {"market": market, "code": code, "native": code.rsplit('.', 1)[0], "name": name, "currency": currency})
        connection.execute(sa.text("""
            INSERT INTO universe_member (universe_id, instrument_id, source, metadata, created_at, updated_at)
            SELECT u.id, i.id, 'MIGRATION', :metadata, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM universe u, instrument i WHERE u.key=:key AND i.code=:code ON CONFLICT DO NOTHING
        """), {"key": f"{market.lower()}_etf_rotation", "code": code,
                 "metadata": json.dumps({"category": category, "theme": theme, "risk_group": risk_group})})


def downgrade() -> None:
    raise NotImplementedError("The portfolio sunset and security-master migration are intentionally irreversible")
