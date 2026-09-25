#!/usr/bin/env python3
"""Runnable multi-rail example: one agent, one payment, four settlement rails.

Demonstrates that an agent can settle the SAME amount on any rail through
the same ``PaymentRail`` interface - the shape a wallet-SDK would expose when
it adds a Nano (XNO) entry next to an EVM/USDC one.

Run (no wallet, no keys; payments are simulated against a local stub):

    python3 examples/pay_on_any_rail.py

By default it settles on the Nano rail (feeless) and prints a comparison.
Pass a rail name to settle there instead (usdc-evm, skyfire-usd, payman-api):

    python3 examples/pay_on_any_rail.py usdc-evm
"""
from __future__ import annotations

import sys

from agent_wallet_multirail import settle, rail_for


def main() -> None:
    # The rails an agent-wallet SDK could expose behind one interface.
    rails = ["nano-xno", "usdc-evm", "skyfire-usd", "payman-api", "nevermined-proto"]

    # Which rail to settle on this run (default: the feeless one).
    pick = sys.argv[1] if len(sys.argv) > 1 else "nano-xno"
    if pick == "--all-rails":
        return _all_rails()
    if pick not in rails:
        raise SystemExit(f"unknown rail '{pick}'; choose from {rails}")

    amount_usd = 1.00

    print("=" * 62)
    print(f"Agent settles $1.00 of an x402-priced call on {len(rails)} rails")
    print("=" * 62)
    for name in rails:
        q = rail_for(name).quote(amount_usd)
        print(f"\n  rail      : {name}")
        print(f"  currency  : {q.currency}")
        print(f"  amount    : ${q.amount_usd:.2f}")
        print(f"  fee       : ${q.fee_usd:.6f}")
        print(f"  finality  : {q.finality_s:.1f}s")

    print("\n-- settling on the chosen rail --")
    result = settle(pick, amount_usd)
    # invariant: the helper settles on exactly the rail the agent chose.
    if result.rail != pick:
        raise SystemExit(f"rail mismatch: chose {pick}, settled {result.rail}")
    print(f"  rail      : {result.rail}")
    print(f"  settled   : {result.settled}")
    print(f"  total fee : ${result.fee_usd:.6f}")
    print(f"  tx ref    : {result.tx_ref}")
    print(f"  finality  : {result.meta['finality_s']}s")
    # machine-readable markers (stable for automation / first-contact citations)
    print(f"SETTLED_ON:{result.rail} FEE_USD:{result.fee_usd:.6f}")
    print(f"SETTLED:{result.settled} ON:{result.rail}")
    if result.fee_usd == 0:
        print("\n  Nano rail settled feeless and sub-second (no gas, no freezeable stablecoin).")
    else:
        print("\n  USDC rail settled with a processing fee + EVM gas.")


def _all_rails() -> None:
    """Settle the same amount on every rail and report each result."""
    rails = ["nano-xno", "usdc-evm", "skyfire-usd", "payman-api", "nevermined-proto"]
    amount_usd = 1.00
    print("-- settling $1.00 on every rail --")
    for name in rails:
        q = rail_for(name).quote(amount_usd)
        r = settle(name, q.amount_usd)
        print(f"SETTLED_ON:{r.rail} FEE_USD:{r.fee_usd:.6f} FINALITY_S:{q.finality_s}")
    print("OK")


if __name__ == "__main__":
    main()
