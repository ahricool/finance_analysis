"""Portfolio application service and centralized cross-table validation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Callable

from sqlalchemy.exc import IntegrityError

from finance_analysis.core.time import utc_now
from finance_analysis.database.models import PortfolioAccount, Position
from finance_analysis.database.repositories.portfolio import (
    AccountCashBalanceRepository,
    InstrumentRepository,
    PortfolioAccountRepository,
    PositionRepository,
)
from finance_analysis.database.session import DatabaseManager
from finance_analysis.portfolio.domain import (
    coerce_decimal,
    current_us_market_date,
    decimal_to_string,
    option_days_to_expiration,
)


class PortfolioError(ValueError):
    """Base error for portfolio validation and ownership failures."""


class PortfolioNotFoundError(PortfolioError):
    pass


class PortfolioConflictError(PortfolioError):
    pass


class PortfolioValidationError(PortfolioError):
    pass


class PortfolioService:
    """Coordinate portfolio persistence while enforcing all domain invariants."""

    def __init__(
        self,
        db: DatabaseManager | None = None,
        *,
        now_provider: Callable[[], datetime] = utc_now,
    ):
        self.db = db or DatabaseManager.get_instance()
        self.accounts = PortfolioAccountRepository(self.db)
        self.cash = AccountCashBalanceRepository(self.db)
        self.instruments = InstrumentRepository(self.db)
        self.positions = PositionRepository(self.db)
        self.now_provider = now_provider

    def ensure_fixed_portfolio_accounts(self, uid: int) -> list[PortfolioAccount]:
        """Ensure a user has exactly the required CN, HK, and US account identities."""
        return self.accounts.ensure_fixed_accounts(uid)

    def get_account(self, uid: int, account_id: int) -> PortfolioAccount:
        account = self.accounts.get_by_id(account_id, uid)
        if account is None:
            raise PortfolioNotFoundError("portfolio account not found")
        return account

    def set_cash_balance(self, uid: int, account_id: int, balance: Decimal | str) -> PortfolioAccount:
        parsed = self._parse_decimal(balance, field_name="balance")
        account = self.cash.set_balance(account_id, uid, parsed)
        if account is None:
            raise PortfolioNotFoundError("portfolio account not found")
        return account

    @staticmethod
    def _parse_decimal(value: Decimal | str, *, field_name: str) -> Decimal:
        try:
            return coerce_decimal(value, field_name=field_name)
        except ValueError as exc:
            raise PortfolioValidationError(str(exc)) from exc

    @staticmethod
    def _validate_cost(avg_cost: Decimal | str) -> Decimal:
        value = PortfolioService._parse_decimal(avg_cost, field_name="avg_cost")
        if value < 0:
            raise PortfolioValidationError("avg_cost must be greater than or equal to 0")
        return value

    @staticmethod
    def _validate_quantity(asset_type: str, quantity: Decimal | str) -> Decimal:
        value = PortfolioService._parse_decimal(quantity, field_name="quantity")
        if value == 0:
            raise PortfolioValidationError("quantity must not be 0")
        if asset_type in {"STOCK", "ETF"} and value <= 0:
            raise PortfolioValidationError("stock and ETF quantity must be greater than 0")
        if asset_type == "OPTION" and value != value.to_integral_value():
            raise PortfolioValidationError("option quantity must be an integer number of contracts")
        return value

    @staticmethod
    def _validate_account_instrument(account: PortfolioAccount, *, market: str, currency: str) -> None:
        if account.market != market:
            raise PortfolioValidationError("instrument market does not match account market")
        if account.currency != currency:
            raise PortfolioValidationError("instrument currency does not match account currency")

    def list_positions(
        self,
        uid: int,
        account_id: int,
        *,
        status: str = "OPEN",
        asset_type: str = "ALL",
    ) -> list[Position]:
        self.get_account(uid, account_id)
        return self.positions.list_by_account(account_id, uid, status=status, asset_type=asset_type)

    def create_equity_position(
        self,
        uid: int,
        account_id: int,
        *,
        canonical_symbol: str,
        display_symbol: str,
        name: str | None,
        asset_type: str,
        quantity: Decimal | str,
        avg_cost: Decimal | str,
        opened_at: datetime | None,
        notes: str | None,
    ) -> Position:
        account = self.get_account(uid, account_id)
        normalized_type = asset_type.strip().upper()
        if normalized_type not in {"STOCK", "ETF"}:
            raise PortfolioValidationError("asset_type must be STOCK or ETF")
        parsed_quantity = self._validate_quantity(normalized_type, quantity)
        parsed_cost = self._validate_cost(avg_cost)
        try:
            instrument = self.instruments.get_or_create_equity(
                market=account.market,
                asset_type=normalized_type,
                canonical_symbol=canonical_symbol,
                display_symbol=display_symbol,
                name=name,
            )
        except ValueError as exc:
            raise PortfolioValidationError(str(exc)) from exc
        self._validate_account_instrument(account, market=instrument.market, currency=instrument.currency)
        if instrument.contract_multiplier != Decimal("1"):
            raise PortfolioValidationError("stock and ETF contract multiplier must equal 1")
        try:
            return self.positions.create(
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=parsed_quantity,
                avg_cost=parsed_cost,
                opened_at=opened_at,
                notes=notes,
            )
        except IntegrityError as exc:
            raise PortfolioConflictError("this instrument already has a position in the account") from exc

    def create_option_position(
        self,
        uid: int,
        account_id: int,
        *,
        underlying_canonical_symbol: str,
        underlying_display_symbol: str,
        underlying_name: str | None,
        underlying_asset_type: str,
        option_type: str,
        expiration_date: date,
        strike_price: Decimal | str,
        quantity: Decimal | str,
        avg_cost: Decimal | str,
        contract_multiplier: Decimal | str = Decimal("100"),
        opened_at: datetime | None = None,
        notes: str | None = None,
    ) -> Position:
        account = self.get_account(uid, account_id)
        if account.account_code != "US" or account.market != "US":
            raise PortfolioValidationError("options may only be held in the US account")
        underlying_type = underlying_asset_type.strip().upper()
        if underlying_type not in {"STOCK", "ETF"}:
            raise PortfolioValidationError("option underlying_asset_type must be STOCK or ETF")
        kind = option_type.strip().upper()
        if kind not in {"CALL", "PUT"}:
            raise PortfolioValidationError("option_type must be CALL or PUT")
        strike = self._parse_decimal(strike_price, field_name="strike_price")
        if strike <= 0:
            raise PortfolioValidationError("strike_price must be greater than 0")
        multiplier = self._parse_decimal(contract_multiplier, field_name="contract_multiplier")
        if multiplier != Decimal("100"):
            raise PortfolioValidationError("standard US option contract_multiplier must equal 100")
        parsed_quantity = self._validate_quantity("OPTION", quantity)
        parsed_cost = self._validate_cost(avg_cost)
        if expiration_date < current_us_market_date(self.now_provider()):
            raise PortfolioValidationError("expiration_date cannot be earlier than the current US market date")
        try:
            instrument = self.instruments.get_or_create_option(
                underlying_canonical_symbol=underlying_canonical_symbol,
                underlying_display_symbol=underlying_display_symbol,
                underlying_name=underlying_name,
                underlying_asset_type=underlying_type,
                expiration_date=expiration_date,
                strike_price=strike,
                option_type=kind,
                contract_multiplier=multiplier,
            )
        except ValueError as exc:
            raise PortfolioValidationError(str(exc)) from exc
        self._validate_account_instrument(account, market=instrument.market, currency=instrument.currency)
        if instrument.asset_type != "OPTION" or instrument.market_data_symbol_id is not None:
            raise PortfolioValidationError("invalid option instrument")
        contract = instrument.option_contract
        if contract is None or contract.underlying.asset_type != underlying_type:
            raise PortfolioValidationError("option underlying identity does not match the request")
        if Decimal(instrument.contract_multiplier) != multiplier:
            raise PortfolioValidationError(
                "contract_multiplier does not match the existing standard option contract"
            )
        try:
            return self.positions.create(
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=parsed_quantity,
                avg_cost=parsed_cost,
                opened_at=opened_at,
                notes=notes,
            )
        except IntegrityError as exc:
            raise PortfolioConflictError("this option already has a position in the account") from exc

    def update_position(self, uid: int, position_id: int, **changes) -> Position:
        position = self.positions.get_by_id(position_id, uid)
        if position is None:
            raise PortfolioNotFoundError("position not found")
        asset_type = position.instrument.asset_type
        normalized: dict = {}
        if "quantity" in changes:
            normalized["quantity"] = self._validate_quantity(asset_type, changes["quantity"])
        if "avg_cost" in changes:
            normalized["avg_cost"] = self._validate_cost(changes["avg_cost"])
        for key in ("opened_at", "notes"):
            if key in changes:
                normalized[key] = changes[key]

        target_status = str(changes.get("status", position.status)).upper()
        if target_status not in {"OPEN", "CLOSED", "EXPIRED"}:
            raise PortfolioValidationError("status must be OPEN, CLOSED, or EXPIRED")
        if target_status == "OPEN":
            if changes.get("closed_at") is not None:
                raise PortfolioValidationError("OPEN position closed_at must be null")
            normalized["status"] = "OPEN"
            normalized["closed_at"] = None
        elif target_status == "CLOSED":
            normalized["status"] = "CLOSED"
            normalized["closed_at"] = changes.get("closed_at") or position.closed_at or self.now_provider()
        else:
            contract = position.instrument.option_contract
            if asset_type != "OPTION" or contract is None:
                raise PortfolioValidationError("only options may be marked EXPIRED")
            if contract.expiration_date > current_us_market_date(self.now_provider()):
                raise PortfolioValidationError("option cannot be marked EXPIRED before expiration")
            normalized["status"] = "EXPIRED"
            normalized["closed_at"] = changes.get("closed_at") or position.closed_at or self.now_provider()

        updated = self.positions.update(position_id, uid, **normalized)
        if updated is None:
            raise PortfolioNotFoundError("position not found")
        return updated

    def delete_position(self, uid: int, position_id: int) -> None:
        if not self.positions.delete(position_id, uid):
            raise PortfolioNotFoundError("position not found")

    def account_payload(self, account: PortfolioAccount) -> dict:
        balance = account.cash_balance.balance if account.cash_balance is not None else Decimal("0")
        return {
            "id": account.id,
            "account_code": account.account_code,
            "name": account.name,
            "market": account.market,
            "currency": account.currency,
            "cash_balance": decimal_to_string(balance),
        }

    def position_payload(self, position: Position) -> dict:
        instrument = position.instrument
        multiplier = Decimal(instrument.contract_multiplier)
        quantity = Decimal(position.quantity)
        with localcontext() as context:
            context.prec = max(context.prec, 38)
            cost_amount = (
                abs(quantity) * Decimal(position.avg_cost) * multiplier
            ).quantize(Decimal("0.00000001"))
        option_payload = None
        if instrument.asset_type == "OPTION":
            contract = instrument.option_contract
            if contract is None:
                raise RuntimeError("option instrument is missing OptionContract")
            dte = option_days_to_expiration(contract.expiration_date, self.now_provider())
            underlying = contract.underlying
            underlying_name = (
                underlying.market_data_symbol.name
                if underlying.market_data_symbol is not None
                else underlying.name
            )
            option_payload = {
                "underlying_canonical_symbol": underlying.canonical_symbol,
                "underlying_display_symbol": underlying.display_symbol,
                "underlying_name": underlying_name,
                "option_type": contract.option_type,
                "expiration_date": contract.expiration_date,
                "strike_price": decimal_to_string(Decimal(contract.strike_price)),
                "days_to_expiration": dte,
                "expiration_action_required": position.status == "OPEN" and dte < 0,
            }
        return {
            "id": position.id,
            "account_id": position.account_id,
            "account_code": position.account.account_code,
            "asset_type": instrument.asset_type,
            "market": instrument.market,
            "currency": instrument.currency,
            "canonical_symbol": instrument.canonical_symbol,
            "display_symbol": instrument.display_symbol,
            "name": (
                instrument.market_data_symbol.name
                if instrument.market_data_symbol is not None
                else instrument.name
            ),
            "quantity": decimal_to_string(quantity),
            "position_side": "SHORT" if quantity < 0 else "LONG",
            "avg_cost": decimal_to_string(Decimal(position.avg_cost)),
            "contract_multiplier": decimal_to_string(multiplier),
            "cost_amount": decimal_to_string(cost_amount),
            "opened_at": position.opened_at,
            "status": position.status,
            "closed_at": position.closed_at,
            "notes": position.notes,
            "created_at": position.created_at,
            "updated_at": position.updated_at,
            "option": option_payload,
        }


def ensure_fixed_portfolio_accounts(uid: int, db: DatabaseManager | None = None) -> list[PortfolioAccount]:
    """Shared initialization entrypoint used after user creation and as API defense."""
    return PortfolioService(db).ensure_fixed_portfolio_accounts(uid)
