"""Pure paper-portfolio accounting using the average-cost method (no database access)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol

from app.exceptions import InvalidRequestError

EPSILON = 1e-9


class TransactionLike(Protocol):
    ticker: str
    side: str
    quantity: float
    price: float
    fee: float


@dataclass
class Position:
    ticker: str
    quantity: float = 0.0
    cost_basis: float = 0.0  # total cost of the shares still held, fees included

    @property
    def average_cost(self) -> float:
        return self.cost_basis / self.quantity if self.quantity > EPSILON else 0.0


@dataclass
class PortfolioState:
    cash: float
    realized_pnl: float = 0.0
    total_fees: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if p.quantity > EPSILON]


def compute_portfolio_state(
    starting_cash: float, transactions: Iterable[TransactionLike]
) -> PortfolioState:
    """Replay transactions in order.

    BUY adds `quantity * price + fee` to cost basis and removes it from cash.
    SELL realizes `quantity * price - fee - average_cost * quantity`.
    Raises InvalidRequestError for overselling or negative cash.
    """
    state = PortfolioState(cash=float(starting_cash))
    for tx in transactions:
        position = state.positions.setdefault(tx.ticker, Position(ticker=tx.ticker))
        gross = tx.quantity * tx.price
        state.total_fees += tx.fee
        if tx.side == "BUY":
            state.cash -= gross + tx.fee
            if state.cash < -EPSILON:
                raise InvalidRequestError(
                    "Insufficient paper cash for this purchase.",
                    details={"ticker": tx.ticker, "cash_after": round(state.cash, 2)},
                )
            position.quantity += tx.quantity
            position.cost_basis += gross + tx.fee
        elif tx.side == "SELL":
            if tx.quantity > position.quantity + EPSILON:
                raise InvalidRequestError(
                    "Cannot sell more shares than are held (short selling is not supported).",
                    details={
                        "ticker": tx.ticker,
                        "held": position.quantity,
                        "requested": tx.quantity,
                    },
                )
            average = position.average_cost
            state.realized_pnl += gross - tx.fee - average * tx.quantity
            state.cash += gross - tx.fee
            position.cost_basis -= average * tx.quantity
            position.quantity -= tx.quantity
            if position.quantity <= EPSILON:
                position.quantity = 0.0
                position.cost_basis = 0.0
        else:  # pragma: no cover - guarded by the request schema
            raise InvalidRequestError(f"Unknown transaction side '{tx.side}'.")
    return state
