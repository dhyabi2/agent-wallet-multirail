"""0xGasless AgentKit -> feeless Nano (XNO) settle rail example.

Purpose: show the seam a Nano settle rail fills in 0xGasless AgentKit
(github.com/0xgasless/agentkit, issue #38). 0xGasless gives an agent a
KMS-custodied wallet, a server spending policy, gasless stablecoin (USDC/XSGD)
payments and x402 pay-per-call against any HTTP 402 endpoint. Its pay path
always settles through a priced fungible rail (USDC on Avalanche) - even with
the facilitator paying the gas, the settlement leg carries a network / path fee.

Nano (XNO) is the same story one step further: a settlement rail with no gas
token on EITHER side, no issuer to freeze a balance, sub-second single-block
finality. An agent opts a call to settle in XNO behind the same pay surface
instead of USDC. The x402 "exact" (fixed-amount) scheme for Nano already exists
as a live, maintained package (@x402nano/exact), so this is an integration on
an existing building block, not new network infrastructure.

These functions run offline against a stub so the example needs no wallet, no
key, and no network. The one seam a real SDK wires up is `nano_rpc` - point it
at a real Nano RPC to settle a real, feeless, sub-second XNO transfer, or wrap
the existing Nano x402 client.
"""
from __future__ import annotations

import time
from typing import Callable, Dict


def gasless_quote_nano(amount_usd: float,
                       finality_s: float = 0.3) -> Dict[str, object]:
    """Quote settling `amount_usd` on the Nano rail (feeless, sub-second)."""
    return {
        "rail": "nano-xno",
        "scheme": "exact",          # the x402 fixed-amount Nano scheme
        "network": "nano:mainnet",
        "asset": "XNO",
        "amount_usd": amount_usd,
        "fee_usd": 0.0,             # no gas, no per-transfer fee, no facilitator fee
        "finality_s": finality_s,
    }


def gasless_quote_usdc(amount_usd: float,
                       fee_pct: float = 0.01,
                       gas_usd: float = 0.05) -> Dict[str, object]:
    """Quote settling `amount_usd` on the 0xGasless stablecoin rail (USDC)."""
    return {
        "rail": "usdc-avalanche",
        "scheme": "x402-stablecoin",
        "network": "avalanche-fuji",
        "asset": "USDC",
        "amount_usd": amount_usd,
        "fee_usd": round(amount_usd * fee_pct + gas_usd, 6),
        "finality_s": 3.0,
    }


def gasless_pay_xno(quote: Dict[str, object],
                    nano_rpc: Callable[[Dict[str, object]], Dict[str, object]]
                    | None = None) -> Dict[str, object]:
    """Pay an x402 call in XNO, feeless, and fail closed on an unconfirmed send.

    `nano_rpc` is an optional stub callable so the example runs offline. A real
    integration would submit a signed XNO state block and wait for single-block
    confirmation; `block` is the confirmed block's reference. A Nano node answers
    an error or a missing confirmation far more often than it answers one, so a
    missing confirmation is never read as a payment that happened.
    """
    rpc = nano_rpc or (
        lambda req: {"block": f"sim-xno-{int(time.time())}", "confirmed": True}
    )
    resp = rpc({"action": "send", "amount_raw": quote.get("amount_usd")})
    if not isinstance(resp, dict):
        resp = {"error": "nano rpc returned no reply object"}
    block = str(resp.get("block") or "")
    confirmed = resp.get("confirmed")
    settled = (
        "error" not in resp
        and bool(block)
        and (confirmed is True or str(confirmed).strip().lower() == "true")
    )
    result: Dict[str, object] = {
        "settled": settled,
        "fee_usd": 0.0,
        "tx_ref": block,
        "network": "nano:mainnet",
    }
    if not settled:
        result["error"] = str(resp.get("error") or "nano rpc reported no confirmed block")
    return result


def gasless_pay_usdc(quote: Dict[str, object]) -> Dict[str, object]:
    """Pay an x402 call in USDC on the 0xGasless stablecoin rail (simulated)."""
    return {
        "settled": True,
        "fee_usd": quote.get("fee_usd", 0.0),
        "tx_ref": f"0xsim-usdc-{int(time.time())}",
        "network": "avalanche-fuji",
    }


def gasless_compare(amount_usd: float = 1.0) -> Dict[str, object]:
    """Side-by-side: settling the same call in USDC vs XNO on 0xGasless AgentKit."""
    usdc = gasless_quote_usdc(amount_usd)
    xno = gasless_quote_nano(amount_usd)
    return {
        "amount_usd": amount_usd,
        "usdc": {"fee_usd": usdc["fee_usd"], "finality_s": usdc["finality_s"]},
        "xno": {"fee_usd": xno["fee_usd"], "finality_s": xno["finality_s"]},
        "savings_usd": round(usdc["fee_usd"] - xno["fee_usd"], 6),
    }
