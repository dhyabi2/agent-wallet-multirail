"""The multi-rail PaymentRail interface and its two shipped rails.

Purpose: show that an agent-wallet SDK can let an agent settle the *same*
x402-priced payment on any of four rails through one interface. This is the
"documented adapter with a working example" shape that the prepared first
contacts to agent-wallet SDKs (Coinbase AgentKit, Crossmint, Skyfire, Payman,
Nevermined, 0xgasless, Trust Wallet) propose.

The payments below are simulated against a local stub so the repository runs
with no wallet and no keys. The seam a real SDK would wire up is documented:
``NanoRail`` accepts an optional ``rpc`` callable; point it at a real Nano RPC
(or wrap the existing Nano x402 client, e.g. feeless402 / x402nano-exact) to
settle a real, feeless, sub-second XNO transfer.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict


@dataclass
class Quote:
    """A quote to settle one payment on one rail."""

    rail: str
    amount_usd: float
    fee_usd: float
    finality_s: float
    currency: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "rail": self.rail,
            "amount_usd": self.amount_usd,
            "fee_usd": self.fee_usd,
            "finality_s": self.finality_s,
            "currency": self.currency,
        }


@dataclass
class Settlement:
    """The outcome of settling a quote on a rail."""

    rail: str
    amount_usd: float
    fee_usd: float
    settled: bool
    tx_ref: str = ""
    meta: Dict[str, object] = field(default_factory=dict)


class PaymentRail(ABC):
    """One settlement rail an agent can pay on."""

    name: str = "abstract"

    @abstractmethod
    def quote(self, amount_usd: float) -> Quote:
        """Return what settling `amount_usd` costs and how long it takes."""

    @abstractmethod
    def pay(self, quote: Quote) -> Settlement:
        """Settle the quote and return its outcome and a tx reference."""


class NanoRail(PaymentRail):
    """Nano (XNO): feeless per transfer, sub-second finality, self-custody.

    ``rpc`` is an optional callable stub so tests and examples run offline. A
    real integration would pass a client that performs an actual XNO transfer
    (self-custodial, feeless) and returns on finality.
    """

    name = "nano-xno"

    def __init__(self, rpc: Callable[[Dict[str, object]], Dict[str, object]] | None = None):
        # nano is feeless: no per-tx network fee, no gas.
        self._fee_usd = 0.0
        # nano finality is sub-second (~<0.3s typical open representative
        # voting confirmation).
        self._finality_s = 0.3
        self._rpc = rpc or (lambda req: {"block": f"sim-{int(time.time())}", "confirmed": True})
        super().__init__()

    def quote(self, amount_usd: float) -> Quote:
        return Quote(
            rail=self.name,
            amount_usd=amount_usd,
            fee_usd=self._fee_usd,
            finality_s=self._finality_s,
            currency="XNO",
        )

    def pay(self, quote: Quote) -> Settlement:
        # Simulated settlement: ask the provided rpc to make the transfer and
        # report the confirmed block. A real rail would submit the signed XNO
        # block and wait for confirmation.
        resp = self._rpc({"action": "send", "amount_usd": quote.amount_usd})
        if not isinstance(resp, dict):
            resp = {"error": "rpc returned no reply object"}
        block = str(resp.get("block") or "")
        confirmed = resp.get("confirmed")
        # Fail closed. This is the seam an SDK points at a real Nano RPC, and a
        # node answers an error or a missing confirmation far more often than it
        # answers a confirmation; reading either as success reports a payment
        # that never happened. A Nano node sends `confirmed` as the string
        # "true", so both that and a bool count.
        settled = (
            "error" not in resp
            and block != ""
            and (confirmed is True or str(confirmed).strip().lower() == "true")
        )
        meta: Dict[str, object] = {"finality_s": self._finality_s}
        if not settled:
            # Say why, or a caller sees only settled=False and has to guess.
            meta["error"] = str(resp.get("error") or "rpc reported no confirmed block")
        return Settlement(
            rail=self.name,
            amount_usd=quote.amount_usd,
            fee_usd=self._fee_usd,
            settled=settled,
            tx_ref=block,
            meta=meta,
        )


class UsdcRail(PaymentRail):
    """Stablecoin (USDC on EVM/Base): the status-quo rail, with a fee + gas."""

    name = "usdc-evm"

    def __init__(self, fee_pct: float = 0.01, gas_usd: float = 0.05):
        # a small protocol/processing fee plus EVM network gas per transfer.
        self._fee_pct = fee_pct
        self._gas_usd = gas_usd
        # EVM layer-2 finality of a base/L2 block: a few seconds.
        self._finality_s = 3.0
        super().__init__()

    def quote(self, amount_usd: float) -> Quote:
        fee = round(amount_usd * self._fee_pct + self._gas_usd, 6)
        return Quote(
            rail=self.name,
            amount_usd=amount_usd,
            fee_usd=fee,
            finality_s=self._finality_s,
            currency="USDC",
        )

    def pay(self, quote: Quote) -> Settlement:
        # Simulated settlement on the EVM rail.
        return Settlement(
            rail=self.name,
            amount_usd=quote.amount_usd,
            fee_usd=quote.fee_usd,
            settled=True,
            tx_ref=f"0xsim-{int(time.time())}",
            meta={"finality_s": self._finality_s},
        )


class SkyfireRail(PaymentRail):
    """Skyfire (agentic payments): a closed US-dollar rail for AI micropayments.

    Skyfire settles micro-payments for AI agents in US-dollars (its own
    ledger/SDK) with a per-transfer fee. It is the kind of closed rail a wallet
    SDK might already offer; adding a Nano rail behind the same interface is
    additive, not a replacement.
    """

    name = "skyfire-usd"

    def __init__(self, fee_pct: float = 0.015):
        self._fee_pct = fee_pct
        self._finality_s = 2.0
        super().__init__()

    def quote(self, amount_usd: float) -> Quote:
        # Skyfire charges a fee on the settled amount.
        fee = round(amount_usd * self._fee_pct, 6)
        return Quote(
            rail=self.name,
            amount_usd=amount_usd,
            fee_usd=fee,
            finality_s=self._finality_s,
            currency="USD",
        )

    def pay(self, quote: Quote) -> Settlement:
        return Settlement(
            rail=self.name,
            amount_usd=quote.amount_usd,
            fee_usd=quote.fee_usd,
            settled=True,
            tx_ref=f"skyfire-{int(time.time())}",
            meta={"finality_s": self._finality_s},
        )


class PaymanRail(PaymentRail):
    """Payman (paymanai.com): a payments API for AI agents sending money to humans.

    Payman lets an AI agent instruct payments to real people/accounts. It is a
    platform/API rail (its public SDK was paykit; the company remains live).
    It charges a processing fee. Modeled here as a third-party platform rail a
    wallet SDK might already connect; a Nano rail behind the same interface is
    additive.
    """

    name = "payman-api"

    def __init__(self, fee_pct: float = 0.05):
        self._fee_pct = fee_pct
        self._finality_s = 1.5
        super().__init__()

    def quote(self, amount_usd: float) -> Quote:
        fee = round(amount_usd * self._fee_pct, 6)
        return Quote(
            rail=self.name,
            amount_usd=amount_usd,
            fee_usd=fee,
            finality_s=self._finality_s,
            currency="USD",
        )

    def pay(self, quote: Quote) -> Settlement:
        return Settlement(
            rail=self.name,
            amount_usd=quote.amount_usd,
            fee_usd=quote.fee_usd,
            settled=True,
            tx_ref=f"payman-{int(time.time())}",
            meta={"finality_s": self._finality_s},
        )


class NeverminedRail(PaymentRail):
    """Nevermined Payments Protocol (nevermined-io/payments): TS SDK resolving
    x402 schemes (`nvm:erc4337`, `nvm:card-delegation`) on EVM/Solana.

    Nevermined is a payment protocol for agents; its SDK resolves a settlement
    scheme per request. It is the kind of protocol rail a wallet SDK might
    already relay, and a Nano (`nano:mainnet`) scheme is additive behind the
    same interface - the x402 exact-scheme spec already accepts it.
    Modeled here with a protocol/processing fee like the other platform rails.
    """

    name = "nevermined-proto"

    def __init__(self, fee_pct: float = 0.02):
        self._fee_pct = fee_pct
        self._finality_s = 2.5
        super().__init__()

    def quote(self, amount_usd: float) -> Quote:
        fee = round(amount_usd * self._fee_pct, 6)
        return Quote(
            rail=self.name,
            amount_usd=amount_usd,
            fee_usd=fee,
            finality_s=self._finality_s,
            currency="USD",
        )

    def pay(self, quote: Quote) -> Settlement:
        return Settlement(
            rail=self.name,
            amount_usd=quote.amount_usd,
            fee_usd=quote.fee_usd,
            settled=True,
            tx_ref=f"nvm-{int(time.time())}",
            meta={"finality_s": self._finality_s},
        )


_REGISTRY: Dict[str, PaymentRail] = {
    NanoRail.name: NanoRail(),
    UsdcRail.name: UsdcRail(),
    SkyfireRail.name: SkyfireRail(),
    PaymanRail.name: PaymanRail(),
    NeverminedRail.name: NeverminedRail(),
}


def rail_for(name: str) -> PaymentRail:
    """Return the rail registered under `name` (e.g. 'nano-xno' or 'usdc-evm')."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown rail '{name}'; known: {sorted(_REGISTRY)}") from None


def settle(name: str, amount_usd: float) -> Settlement:
    """One-call helper: quote then settle `amount_usd` on the named rail."""
    rail = rail_for(name)
    return rail.pay(rail.quote(amount_usd))
