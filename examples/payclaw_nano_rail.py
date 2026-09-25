#!/usr/bin/env python3
"""PayClaw-shaped multi-rail example: show how a Nano (XNO) settle rail plugs
into an agent-wallet SDK such as Jc-asastu/payclaw.

PayClaw (https://github.com/Jc-asastu/payclaw) is a multi-chain agent wallet
SDK (Base L2, BSC, Solana) whose `wallet.pay()` settles USDC through an
on-chain policy engine. Today it offers no Nano (XNO) rail. This example keeps
PayClaw's exact public shape --

    payclaw = PayClaw({ chain })
    wallet  = payclaw.createWallet({ policies: { ... } })
    wallet.pay({ to, token, amount, memo })

-- and shows that adding `token: 'XNO'` (or a `rail: 'nano-xno'`) is additive:
the same $ amount settles feeless and sub-second, with no gas and no
freezeable stablecoin, behind the *same* `pay()` call the SDK already has.

Run (no wallet, no keys; payments are simulated against a local stub):

    python3 examples/payclaw_nano_rail.py

Tests live in tests/test_payclaw_nano_rail.py (`python -m pytest -q`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from agent_wallet_multirail import rail_for


@dataclass
class WalletReceipt:
    """The shape PayClaw returns from `wallet.pay()`."""

    rail: str
    token: str
    amount: float
    tx_ref: str
    memo: str
    fee_usd: float = 0.0
    finality_s: float = 0.0


class PayClawWallet:
    """A tiny stand-in for PayClaw's AgentWallet (policy-gated pay()).

    Only the parts this example needs: a `pay()` that routes to a settlement
    rail and returns a receipt. `token` selects the rail — 'USDC' settles on
    the status-quo stablecoin rail, 'XNO' (or 'NANO') on the feeless Nano
    rail. Everything is simulated against a local stub, so the example runs
    with no keys and no network.
    """

    def __init__(self, chain: str, policies: Dict[str, object]):
        self.chain = chain
        self.policies = policies

    def pay(
        self,
        to: str,
        token: str,
        amount: float,
        memo: str = "",
    ) -> WalletReceipt:
        rail = "usdc-evm" if token.upper() in ("USDC", "USDT") else "nano-xno"
        r = rail_for(rail)
        quote = r.quote(amount)
        result = r.pay(quote)
        return WalletReceipt(
            rail=result.rail,
            token="XNO" if result.rail == "nano-xno" else token.upper(),
            amount=result.amount_usd,
            tx_ref=result.tx_ref,
            memo=memo,
            fee_usd=result.fee_usd,
            finality_s=quote.finality_s,
        )


class PayClaw:
    """Minimal mirror of PayClaw's entry point (chain + createWallet)."""

    def __init__(self, chain: str, rpcUrl: str | None = None):
        self.chain = chain
        self.rpcUrl = rpcUrl

    def createWallet(self, *, policies: Dict[str, object]) -> PayClawWallet:
        return PayClawWallet(chain=self.chain, policies=policies)


def main() -> None:
    payclaw = PayClaw(chain="base-sepolia")
    wallet = payclaw.createWallet(
        policies={
            "dailyLimit": 500,
            "perTransactionLimit": 100,
            "approvalThreshold": 50,
            "allowedTokens": ["USDC", "XNO"],
        }
    )

    amount = 1.00

    print("=" * 62)
    print("One PayClaw agent, one $1.00 payment, two settlement rails")
    print("=" * 62)

    # Status-quo: settle $1.00 in USDC (processing fee + EVM gas).
    usdc = wallet.pay(to="0xMerchant...", token="USDC", amount=amount, memo="Invoice #1")
    print(f"\n  rail      : {usdc.rail}")
    print(f"  token     : {usdc.token}")
    print(f"  amount    : ${usdc.amount:.2f}")
    print(f"  memo      : {usdc.memo}")
    print(f"  fee       : ${usdc.fee_usd:.6f}")
    print(f"  finality  : {usdc.finality_s:.1f}s")
    print(f"  tx ref    : {usdc.tx_ref}")

    # Proposed: settle the SAME $1.00 in Nano (XNO) — feeless and sub-second.
    nano = wallet.pay(to="nano_...Merchant", token="XNO", amount=amount, memo="Invoice #1")
    print(f"\n  rail      : {nano.rail}")
    print(f"  token     : {nano.token}")
    print(f"  amount    : ${nano.amount:.2f}")
    print(f"  memo      : {nano.memo}")
    print(f"  fee       : ${nano.fee_usd:.6f}")
    print(f"  finality  : {nano.finality_s:.1f}s")
    print(f"  tx ref    : {nano.tx_ref}")

    assert nano.fee_usd == 0.0, "Nano rail must be feeless"
    assert nano.finality_s <= 1.0, "Nano rail must be sub-second"
    print("\n  Nano settled feeless and sub-second: no gas, no freezeable stablecoin.")
    print("  Additive to PayClaw's existing USDC path — a rail, not a fork.")


if __name__ == "__main__":
    main()
