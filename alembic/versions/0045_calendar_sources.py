"""Provider-neutral earnings/macro calendar; no new tables.

Unsupported calendar rows are removed. Existing IDs/event keys of retained events
survive consolidation. Removed SDK metadata is retained only in source audit JSON.
"""

import hashlib
import json
import re
from datetime import date, timedelta

import sqlalchemy as sa

from alembic import op

revision = "0045_calendar_sources"
down_revision = "0044_crypto_btc"
branch_labels = None
depends_on = None


def _session(value):
    if "盘前" in str(value or ""):
        return "bmo"
    if "盘后" in str(value or ""):
        return "amc"
    if "盘中" in str(value or ""):
        return "during_market"
    value = re.sub(r"[^a-z]", "", str(value or "").lower())
    if value in {"bmo", "beforemarketopen", "beforeopen", "premarket", "beforetrading"}:
        return "bmo"
    if value in {"amc", "aftermarketclose", "afterclose", "postmarket", "aftertrading"}:
        return "amc"
    if value in {"dmh", "duringmarket", "duringmarkethours", "duringtrading", "intraday"}:
        return "during_market"
    return "unknown"


def _json(value):
    try:
        return json.loads(value or "{}")
    except (ValueError, TypeError):
        return {"unparsed": str(value)}


def _macro_type(name: str) -> str:
    """Explicit cross-language aliases; preserve frequency/core/release distinctions."""
    text = str(name or "").lower().strip()
    base = None
    if re.search(r"(?<![a-z])cpi(?![a-z])|consumer price index|消费者物价|消费者价格|消费价格", text):
        base = "cpi"
    elif re.search(r"non.?farm payroll|non.?farm employment|非农就业|非农人口", text):
        base = "nonfarm_payrolls"
    elif re.search(
        r"^fomc$|fomc.*(rate|decision)|fed.*interest rate|fed(?:eral)? funds target rate|联邦基金利率|美联储.*利率",
        text,
    ):
        base = "fomc_rate_decision"
    elif re.search(r"(?<![a-z])pce(?![a-z])|personal consumption expenditure|个人消费支出", text):
        base = "pce"
    elif re.search(r"(?<![a-z])gdp(?![a-z])|gross domestic product|国内生产总值", text):
        base = "gdp"
    if base:
        qualifiers = []
        for label, pattern in (
            ("core", r"core|核心"),
            ("yoy", r"yoy|y/y|\byy\b|year.over.year|年率|同比"),
            ("mom", r"mom|m/m|\bmm\b|month.over.month|月率|环比"),
            ("qoq", r"qoq|q/q|\bqq\b|quarter.over.quarter|季率"),
            ("advance", r"advance|初值"),
            ("preliminary", r"prelim|修正值"),
            ("final", r"final|终值"),
            ("upper", r"upper|上限"),
            ("lower", r"lower|下限"),
        ):
            if re.search(pattern, text):
                qualifiers.append(label)
        return "_".join([base, *qualifiers])
    text = re.sub(r"^(united states|u\.s\.|us|美国)\s*", "", text)
    return re.sub(r"[^\w]+", "_", text).strip("_")[:64]


def upgrade():
    bind = op.get_bind()
    old = sa.Table("finance_events", sa.MetaData(), autoload_with=bind)
    rows = [dict(row) for row in bind.execute(sa.select(old).order_by(old.c.id)).mappings()]
    op.execute(
        sa.delete(old).where(
            sa.or_(
                old.c.calendar_type.not_in(("earnings", "macro")),
                sa.and_(old.c.calendar_type == "macro", old.c.market != "US"),
                sa.and_(
                    old.c.calendar_type == "earnings", sa.or_(old.c.market.not_in(("US", "CN")), old.c.symbol.is_(None))
                ),
            )
        )
    )
    with op.batch_alter_table("finance_events") as batch:
        batch.alter_column("financial_market_time", new_column_name="market_session", existing_type=sa.String(64))
        batch.add_column(sa.Column("reporting_period", sa.String(64)))
        for name in ("eps_estimate", "reported_eps", "eps_surprise_pct"):
            batch.add_column(sa.Column(name, sa.Float()))
        for index in sa.inspect(bind).get_indexes("finance_events"):
            if "star" in index["column_names"]:
                batch.drop_index(index["name"])
        for name in ("activity_type", "date_type", "star", "data_kv_json"):
            batch.drop_column(name)
    table = sa.Table("finance_events", sa.MetaData(), autoload_with=bind)
    retained = []
    for row in rows:
        kind, market = row["calendar_type"], row["market"]
        if kind not in {"earnings", "macro"} or market not in {"US", "CN"}:
            continue
        if kind == "macro" and market != "US" or kind == "earnings" and not row["symbol"]:
            continue
        symbol = row["symbol"] if kind == "earnings" else None
        if symbol and market == "US" and not symbol.endswith(".US"):
            symbol += ".US"
        values = {
            "symbol": symbol,
            "market_session": _session(row["financial_market_time"] or row["date_type"]),
            "event_type": "earnings_release" if kind == "earnings" else _macro_type(row["content"] or row["title"]),
            "content": "\n".join(
                line
                for line in row["content"].splitlines()
                if "重要性 star" not in line and "来源 provider" not in line
            ),
        }
        fiscal = re.search(r"\bQ([1-4])\s+(20\d{2})\b", row["title"] + " " + row["content"], re.I)
        values["reporting_period"] = f"{fiscal[2]}-Q{fiscal[1]}" if fiscal and kind == "earnings" else None
        normalized = {
            key: values.get(key, row.get(key))
            for key in (
                "provider",
                "provider_event_id",
                "calendar_type",
                "market",
                "symbol",
                "counter_name",
                "event_type",
                "event_date",
                "event_datetime",
                "market_session",
                "reporting_period",
                "title",
                "content",
                "currency",
            )
        }
        raw = _json(row["raw_payload_json"])
        # Frozen audit structure; no runtime compatibility adapter after migration.
        values["raw_payload_json"] = json.dumps(
            {
                row["provider"]: {
                    "normalized": normalized,
                    "raw": raw,
                    "observed_at": row["last_seen_at"].isoformat(),
                    "legacy_metadata": {
                        key: row.get(key) for key in ("activity_type", "date_type", "star", "data_kv_json")
                    },
                }
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        for key in (
            "importance_score",
            "importance_reason",
            "importance_confidence",
            "importance_model",
            "importance_prompt_version",
            "importance_input_hash",
            "importance_scored_at",
        ):
            values[key] = None
        if row["notified_at"]:
            fingerprint = {
                "calendar_type": kind,
                "symbol": symbol,
                "event_date": row["event_date"].isoformat(),
                "event_datetime": row["event_datetime"].isoformat() if row["event_datetime"] else None,
                "market_session": values["market_session"],
            }
            values["notification_fingerprint"] = hashlib.sha256(
                json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, default=str).encode()
            ).hexdigest()[:48]
        candidate = next(
            (
                item
                for item in retained
                if item["calendar_type"] == kind
                and item["market"] == market
                and not (
                    item.get("reporting_period")
                    and values["reporting_period"]
                    and item["reporting_period"] != values["reporting_period"]
                )
                and item["symbol"] == symbol
                and (
                    kind == "earnings"
                    and (
                        item.get("reporting_period")
                        and item["reporting_period"] == values["reporting_period"]
                        or item["event_date"] == row["event_date"]
                        or min(item["event_date"], row["event_date"]) >= date.today() - timedelta(days=7)
                        and abs((item["event_date"] - row["event_date"]).days) <= 21
                    )
                    or kind == "macro"
                    and item["event_type"] == values["event_type"]
                    and item["event_date"] == row["event_date"]
                )
            ),
            None,
        )
        if candidate:
            # Keep oldest identity; newest observation supplies mutable values.
            values["first_seen_at"] = min(row["first_seen_at"], candidate["first_seen_at"])
            values["notified_at"] = row["notified_at"] or candidate["notified_at"]
            if row["last_seen_at"] >= candidate["last_seen_at"]:
                values.update(
                    event_date=row["event_date"],
                    event_datetime=row["event_datetime"],
                    last_seen_at=row["last_seen_at"],
                    provider_event_id=row["provider_event_id"],
                )
                bind.execute(table.update().where(table.c.id == candidate["id"]).values(**values))
                candidate.update(values)
            bind.execute(table.delete().where(table.c.id == row["id"]))
        else:
            bind.execute(table.update().where(table.c.id == row["id"]).values(**values))
            retained.append({**row, **values})
    with op.batch_alter_table("finance_events") as batch:
        batch.create_check_constraint("ck_finance_events_type", "calendar_type IN ('earnings', 'macro')")
        batch.create_check_constraint(
            "ck_finance_events_scope",
            "(calendar_type = 'macro' AND market = 'US' AND symbol IS NULL) OR "
            "(calendar_type = 'earnings' AND market IN ('US', 'CN') AND symbol IS NOT NULL)",
        )


def downgrade():
    raise RuntimeError("Calendar consolidation is irreversible; restore a pre-migration backup to roll back.")
