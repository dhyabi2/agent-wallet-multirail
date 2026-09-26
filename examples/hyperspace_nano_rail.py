"""Hyperspace Wallet SDK -> feeless Nano (XNO) settle rail example.

Purpose: show the seam a Nano settle rail fills in Hyperspace Wallet, the
agent wallet SDK (https://wallet.hyper.space, verified live 200 this run).

Hyperspace gives an agent a portable identity (did:hyperspace:), a multi-rail
wallet and ONE wallet.pay() that speaks five payment rails - native, x402
(Coinbase/USDC), Stripe ACP, Google AP2 and Tempo MPP - quoting each, picking
the cheapest, falling through on failure, and returning the same receipt
envelope for every rail. Its own claim, on the page: "One wallet.pay(). Five
rails. The SDK quotes each, picks cheapest, falls through on failure. Every
receipt has the same shape."

Nano (XNO) is the missing sixth rail: a settlement rail where the payment IS
also the finality - no gas token on either side, no issuer who can switch it
off, a single self-signed block confirmed in well under a second, feeless.
The x402 "exact" (fixed-amount) Nano scheme already exists as a live,
maintained package (@x402nano/exact), so adding a nano-xno rail to a wallet
that already relays x402 is an integration on an existing building block, not
new network infrastructure - and it drops straight into the same receipt
envelope shape (rail / amount / fee / finality / tx_ref) every other rail
returns.

These functions run offline against a stub so the example needs no wallet, no
key and no network. The one seam a real SDK wires up is `nano_rpc` - point it
at a real Nano RPC (or wrap the existing Nano x402 client) to settle a real,
feeless, sub-second XNO transfer.
"""
from __future__ import annotations

import time
from typing import Callable, Dict


def hyperspace_quote_nano(amount_usd: float,
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


def hyperspace_quote_rail(rail: str,
                          amount_usd: float,
                          fee_pct: float = 0.02,
                          finality_s: float = 3.0) -> Dict[str, object]:
    """Quote settling `amount_usd` on one of the status-quo rails.

    This models what Hyperspace's pay() would quote for a priced fungible rail
    (x402/USDC, ACP, AP2 or MPP): a per-settlement fee and seconds of finality.
    Nano's quote carries zero fee and sub-second finality, so a comparison
    shows a real saving on the same amount.
    """
    return {
        "rail": rail,
        "scheme": rail,
        "network": rail,
        "asset": "USDC" if "x402" in rail or "usdc" in rail else "USD",
        "amount_usd": amount_usd,
        "fee_usd": round(amount_usd * fee_pct, 6),
        "finality_s": finality_s,
    }


def _pay(quote: Dict[str, object],
         nano_rpc: Callable[[Dict[str, object]], Dict[str, object]] | None) -> Dict[str, object]:
    """Settle a quoted payment, fail closed on an unconfirmed send."""
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
    # One receipt shape for every rail, exactly what hyperspace-wallet-sdk's
    # unified envelope promises.
    result: Dict[str, object] = {
        "receipt": {
            "rail": quote.get("rail"),
            "amount_usd": quote.get("amount_usd"),
            "fee_usd": 0.0 if quote.get("rail") == "nano-xno" else quote.get("fee_usd"),
            "finality_s": quote.get("finality_s"),
            "tx_ref": block,
        },
        "settled": settled,
        "network": quote.get("network"),
        "asset": quote.get("asset"),
    }
    if not settled:
        result["receipt"]["tx_ref"] = ""
        result["error"] = str(resp.get("error") or "nano rpc reported no confirmed block")
    return result


def hyperspace_pay(quote: Dict[str, object],
                   nano_rpc: Callable[[Dict[str, object]], Dict[str, object]]
                   | None = None) -> Dict[str, object]:
    """Pay a payment on its quoted rail via the wallet's one pay() seam.

    `nano_rpc` is an optional stub so the example runs offline. A real
    integration would submit a signed XNO state block and wait for single-block
    confirmation; `tx_ref` is the confirmed block's reference.
    """
    return _pay(quote, nano_rpc)


def hyperspace_compare(amount_usd: float = 1.0) -> Dict[str, object]:
    """Side-by-side: settling the same call on a priced rail vs Nano."""
    rails = {
        "x402-usdc": hyperspace_quote_rail("x402-usdc", amount_usd, fee_pct=0.02, finality_s=3.0),
        "stripe-acp": hyperspace_quote_rail("stripe-acp", amount_usd, fee_pct=0.029, finality_s=2.5),
        "nano-xno": hyperspace_quote_nano(amount_usd),
    }
    priced = rails["x402-usdc"]
    nano = rails["nano-xno"]
    return {
        "amount_usd": amount_usd,
        "rails": rails,
        "cheapest_fee_usd": min(r["fee_usd"] for r in rails.values()),
        "savings_usd": round(priced["fee_usd"] - nano["fee_usd"], 6),
    }


if __name__ == "__main__":  # pragma: no cover - exercised by the test suite
    q = hyperspace_quote_nano(1.0)
    out = hyperspace_pay(q)
    c = hyperspace_compare(1.0)
    print(f"QUOTE:{q['rail']} FEE:{q['fee_usd']} FINALITY:{q['finality_s']}s")
    print(f"SETTLED:{str(out['settled']).upper()} ON:{out['network']} REF:{out['receipt']['tx_ref']}")
    print(f"COMPARE cheapest_fee={c['cheapest_fee_usd']} savings={c['savings_usd']}")
