"""Persistence for fixed accounts, instruments, cash balances, and positions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from finance_analysis.core.time import utc_now
from finance_analysis.database.models import (
    AccountCashBalance,
    Instrument,
    MarketDataSymbol,
    OptionContract,
    PortfolioAccount,
    Position,
)
from finance_analysis.database.session import DatabaseManager
from finance_analysis.portfolio.domain import (
    CURRENCY_BY_MARKET,
    FIXED_ACCOUNTS,
    build_option_canonical_symbol,
)
from finance_analysis.stocks.markets import normalize_market_type
from finance_analysis.database.models.stock import validate_market_data_code


def _position_load_options():
    return (
        joinedload(Position.account),
        joinedload(Position.instrument).joinedload(Instrument.market_data_symbol),
        joinedload(Position.instrument)
        .joinedload(Instrument.option_contract)
        .joinedload(OptionContract.underlying),
    )


class PortfolioAccountRepository:
    """Read and idempotently repair the three immutable user accounts."""

    def __init__(self, db: DatabaseManager | None = None):
        self.db = db or DatabaseManager.get_instance()

    def ensure_fixed_accounts(self, uid: int) -> list[PortfolioAccount]:
        """Create missing fixed accounts and missing cash rows without changing balances."""

        def _write(session: Session) -> None:
            existing = {
                row.account_code: row
                for row in session.execute(
                    select(PortfolioAccount).where(PortfolioAccount.uid == uid)
                ).scalars()
            }
            for definition in FIXED_ACCOUNTS:
                account = existing.get(definition.account_code)
                if account is None:
                    account = PortfolioAccount(
                        uid=uid,
                        account_code=definition.account_code,
                        name=definition.name,
                        market=definition.market,
                        currency=definition.currency,
                    )
                    session.add(account)
                    session.flush()
                if session.get(AccountCashBalance, account.id) is None:
                    session.add(AccountCashBalance(account_id=account.id, balance=Decimal("0")))
            session.flush()

        try:
            self.db._run_write_transaction("portfolio.ensure_fixed_accounts", _write)
        except IntegrityError:
            # A concurrent ensure may win the unique-key race; re-run to repair cash rows.
            self.db._run_write_transaction("portfolio.ensure_fixed_accounts.retry", _write)
        return self.list_by_uid(uid)

    def list_by_uid(self, uid: int) -> list[PortfolioAccount]:
        order = {definition.account_code: index for index, definition in enumerate(FIXED_ACCOUNTS)}
        with self.db.get_session() as session:
            rows = session.execute(
                select(PortfolioAccount)
                .options(joinedload(PortfolioAccount.cash_balance))
                .where(PortfolioAccount.uid == uid)
            ).scalars().all()
            return sorted(rows, key=lambda row: order.get(row.account_code, len(order)))

    def get_by_id(self, account_id: int, uid: int) -> PortfolioAccount | None:
        with self.db.get_session() as session:
            return session.execute(
                select(PortfolioAccount)
                .options(joinedload(PortfolioAccount.cash_balance))
                .where(PortfolioAccount.id == account_id, PortfolioAccount.uid == uid)
            ).scalars().first()

    def get_by_code(self, uid: int, account_code: str) -> PortfolioAccount | None:
        with self.db.get_session() as session:
            return session.execute(
                select(PortfolioAccount)
                .options(joinedload(PortfolioAccount.cash_balance))
                .where(
                    PortfolioAccount.uid == uid,
                    PortfolioAccount.account_code == account_code.strip().upper(),
                )
            ).scalars().first()


class AccountCashBalanceRepository:
    """Access cash only through an account ownership join."""

    def __init__(self, db: DatabaseManager | None = None):
        self.db = db or DatabaseManager.get_instance()

    def get_by_account(self, account_id: int, uid: int) -> AccountCashBalance | None:
        with self.db.get_session() as session:
            return session.execute(
                select(AccountCashBalance)
                .join(PortfolioAccount, PortfolioAccount.id == AccountCashBalance.account_id)
                .where(AccountCashBalance.account_id == account_id, PortfolioAccount.uid == uid)
            ).scalars().first()

    def set_balance(self, account_id: int, uid: int, balance: Decimal) -> PortfolioAccount | None:
        def _write(session: Session) -> int | None:
            account = session.execute(
                select(PortfolioAccount)
                .options(joinedload(PortfolioAccount.cash_balance))
                .where(PortfolioAccount.id == account_id, PortfolioAccount.uid == uid)
            ).scalars().first()
            if account is None:
                return None
            cash = account.cash_balance
            if cash is None:
                cash = AccountCashBalance(account_id=account.id, balance=balance)
                session.add(cash)
            else:
                cash.balance = balance
                cash.updated_at = utc_now()
            session.flush()
            return account.id

        updated_id = self.db._run_write_transaction("portfolio.cash.set", _write)
        return PortfolioAccountRepository(self.db).get_by_id(updated_id, uid) if updated_id else None


class InstrumentRepository:
    """Resolve shared equity and stable manual option identities."""

    def __init__(self, db: DatabaseManager | None = None):
        self.db = db or DatabaseManager.get_instance()

    def get_by_identity(self, market: str, asset_type: str, canonical_symbol: str) -> Instrument | None:
        with self.db.get_session() as session:
            return session.execute(
                select(Instrument)
                .options(
                    joinedload(Instrument.market_data_symbol),
                    joinedload(Instrument.option_contract).joinedload(OptionContract.underlying),
                )
                .where(
                    Instrument.market == market.strip().upper(),
                    Instrument.asset_type == asset_type.strip().upper(),
                    Instrument.canonical_symbol == canonical_symbol.strip().upper(),
                )
            ).scalars().first()

    def _matching_market_data_symbol(self, session: Session, market: str, canonical_symbol: str):
        return session.execute(
            select(MarketDataSymbol).where(
                MarketDataSymbol.market == market,
                MarketDataSymbol.code == canonical_symbol,
            )
        ).scalars().first()

    def get_or_create_equity(
        self,
        *,
        market: str,
        asset_type: str,
        canonical_symbol: str,
        display_symbol: str,
        name: str | None = None,
    ) -> Instrument:
        normalized_market = normalize_market_type(market, canonical_symbol)
        normalized_type = asset_type.strip().upper()
        if normalized_type not in {"STOCK", "ETF"}:
            raise ValueError("asset_type must be STOCK or ETF")
        canonical = validate_market_data_code(normalized_market, canonical_symbol)
        currency = CURRENCY_BY_MARKET[normalized_market]

        def _write(session: Session) -> int:
            existing = session.execute(
                select(Instrument).where(
                    Instrument.market == normalized_market,
                    Instrument.asset_type == normalized_type,
                    Instrument.canonical_symbol == canonical,
                )
            ).scalars().first()
            if existing is not None:
                return existing.id
            market_symbol = self._matching_market_data_symbol(session, normalized_market, canonical)
            instrument = Instrument(
                asset_type=normalized_type,
                market=normalized_market,
                canonical_symbol=canonical,
                display_symbol=display_symbol.strip().upper(),
                name=(name or "").strip() or None,
                currency=currency,
                contract_multiplier=Decimal("1"),
                market_data_symbol_id=market_symbol.id if market_symbol else None,
                extra={},
            )
            session.add(instrument)
            session.flush()
            return instrument.id

        try:
            instrument_id = self.db._run_write_transaction("portfolio.instrument.equity", _write)
        except IntegrityError:
            existing = self.get_by_identity(normalized_market, normalized_type, canonical)
            if existing is None:
                raise
            return existing
        result = self.get_by_identity(normalized_market, normalized_type, canonical)
        if result is None or result.id != instrument_id:
            raise RuntimeError("failed to load equity instrument")
        return result

    def get_or_create_option(
        self,
        *,
        underlying_canonical_symbol: str,
        underlying_display_symbol: str,
        underlying_name: str | None,
        underlying_asset_type: str,
        expiration_date: date,
        strike_price: Decimal,
        option_type: str,
        contract_multiplier: Decimal,
    ) -> Instrument:
        underlying = self.get_or_create_equity(
            market="US",
            asset_type=underlying_asset_type,
            canonical_symbol=underlying_canonical_symbol,
            display_symbol=underlying_display_symbol,
            name=underlying_name,
        )
        canonical = build_option_canonical_symbol(
            underlying.canonical_symbol, expiration_date, option_type, strike_price
        )
        kind = option_type.strip().upper()
        call_put = "C" if kind == "CALL" else "P"
        display = f"{underlying.display_symbol} {expiration_date.isoformat()} {strike_price.normalize()}{call_put}"

        def _write(session: Session) -> int:
            contract = session.execute(
                select(OptionContract)
                .where(
                    OptionContract.underlying_instrument_id == underlying.id,
                    OptionContract.expiration_date == expiration_date,
                    OptionContract.strike_price == strike_price,
                    OptionContract.option_type == kind,
                )
            ).scalars().first()
            if contract is not None:
                return contract.instrument_id
            instrument = Instrument(
                asset_type="OPTION",
                market="US",
                canonical_symbol=canonical,
                display_symbol=display,
                name=f"{underlying.display_symbol} {kind.title()}",
                currency="USD",
                contract_multiplier=contract_multiplier,
                market_data_symbol_id=None,
                extra={},
            )
            session.add(instrument)
            session.flush()
            session.add(
                OptionContract(
                    instrument_id=instrument.id,
                    underlying_instrument_id=underlying.id,
                    expiration_date=expiration_date,
                    strike_price=strike_price,
                    option_type=kind,
                )
            )
            session.flush()
            return instrument.id

        try:
            self.db._run_write_transaction("portfolio.instrument.option", _write)
        except IntegrityError:
            existing = self.get_by_identity("US", "OPTION", canonical)
            if existing is None:
                raise
            return existing
        result = self.get_by_identity("US", "OPTION", canonical)
        if result is None:
            raise RuntimeError("failed to load option instrument")
        return result

    def get_option_contract(self, instrument_id: int) -> OptionContract | None:
        with self.db.get_session() as session:
            return session.execute(
                select(OptionContract)
                .options(joinedload(OptionContract.underlying))
                .where(OptionContract.instrument_id == instrument_id)
            ).scalars().first()


class PositionRepository:
    """CRUD positions with account ownership enforced in every operation."""

    def __init__(self, db: DatabaseManager | None = None):
        self.db = db or DatabaseManager.get_instance()

    def list_by_account(
        self,
        account_id: int,
        uid: int,
        status: str | None = None,
        asset_type: str | None = None,
    ) -> list[Position]:
        with self.db.get_session() as session:
            stmt = (
                select(Position)
                .join(PortfolioAccount, PortfolioAccount.id == Position.account_id)
                .join(Instrument, Instrument.id == Position.instrument_id)
                .options(*_position_load_options())
                .where(Position.account_id == account_id, PortfolioAccount.uid == uid)
                .order_by(Position.created_at, Position.id)
            )
            if status and status != "ALL":
                stmt = stmt.where(Position.status == status)
            if asset_type and asset_type != "ALL":
                stmt = stmt.where(Instrument.asset_type == asset_type)
            return session.execute(stmt).unique().scalars().all()

    def list_open_by_uid_and_market(
        self,
        uid: int,
        market: str,
        asset_types: Iterable[str] = ("STOCK", "ETF"),
    ) -> list[Position]:
        allowed_types = tuple(str(item).upper() for item in asset_types)
        if not allowed_types:
            return []
        with self.db.get_session() as session:
            return session.execute(
                select(Position)
                .join(PortfolioAccount, PortfolioAccount.id == Position.account_id)
                .join(Instrument, Instrument.id == Position.instrument_id)
                .options(*_position_load_options())
                .where(
                    PortfolioAccount.uid == uid,
                    PortfolioAccount.market == market.strip().upper(),
                    Position.status == "OPEN",
                    Instrument.asset_type.in_(allowed_types),
                    Position.quantity > 0,
                )
                .order_by(Position.id)
            ).unique().scalars().all()

    def list_all_open_equities(self) -> list[Position]:
        """Return every user's open stock/ETF positions for subscription aggregation."""
        with self.db.get_session() as session:
            return session.execute(
                select(Position)
                .join(Instrument, Instrument.id == Position.instrument_id)
                .options(*_position_load_options())
                .where(
                    Position.status == "OPEN",
                    Position.quantity > 0,
                    Instrument.asset_type.in_(("STOCK", "ETF")),
                )
                .order_by(Position.id)
            ).unique().scalars().all()

    def get_by_id(self, position_id: int, uid: int) -> Position | None:
        with self.db.get_session() as session:
            return session.execute(
                select(Position)
                .join(PortfolioAccount, PortfolioAccount.id == Position.account_id)
                .options(*_position_load_options())
                .where(Position.id == position_id, PortfolioAccount.uid == uid)
            ).unique().scalars().first()

    def create(
        self,
        *,
        account_id: int,
        instrument_id: int,
        quantity: Decimal,
        avg_cost: Decimal,
        opened_at: datetime | None,
        notes: str | None,
    ) -> Position:
        def _write(session: Session) -> int:
            position = Position(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=quantity,
                avg_cost=avg_cost,
                opened_at=opened_at,
                status="OPEN",
                closed_at=None,
                notes=(notes or "").strip() or None,
            )
            session.add(position)
            session.flush()
            return position.id

        position_id = self.db._run_write_transaction("portfolio.position.create", _write)
        with self.db.get_session() as session:
            uid = session.scalar(
                select(PortfolioAccount.uid)
                .join(Position, Position.account_id == PortfolioAccount.id)
                .where(Position.id == position_id)
            )
        result = self.get_by_id(position_id, int(uid)) if uid is not None else None
        if result is None:
            raise RuntimeError("failed to load created position")
        return result

    def update(self, position_id: int, uid: int, **changes) -> Position | None:
        allowed = {"quantity", "avg_cost", "opened_at", "status", "closed_at", "notes"}
        unexpected = set(changes) - allowed
        if unexpected:
            raise ValueError(f"unsupported position fields: {', '.join(sorted(unexpected))}")

        def _write(session: Session) -> int | None:
            position = session.execute(
                select(Position)
                .join(PortfolioAccount, PortfolioAccount.id == Position.account_id)
                .where(Position.id == position_id, PortfolioAccount.uid == uid)
            ).scalars().first()
            if position is None:
                return None
            for key, value in changes.items():
                if key == "notes":
                    value = (value or "").strip() or None
                setattr(position, key, value)
            position.updated_at = utc_now()
            session.flush()
            return position.id

        updated_id = self.db._run_write_transaction("portfolio.position.update", _write)
        return self.get_by_id(updated_id, uid) if updated_id else None

    def delete(self, position_id: int, uid: int) -> bool:
        def _write(session: Session) -> bool:
            owned_id = session.scalar(
                select(Position.id)
                .join(PortfolioAccount, PortfolioAccount.id == Position.account_id)
                .where(Position.id == position_id, PortfolioAccount.uid == uid)
            )
            if owned_id is None:
                return False
            session.execute(delete(Position).where(Position.id == owned_id))
            return True

        return self.db._run_write_transaction("portfolio.position.delete", _write)
