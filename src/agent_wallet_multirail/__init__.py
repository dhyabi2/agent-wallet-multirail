"""Multi-rail agent-payment adapter (heath territory).

One ``PaymentRail`` interface abstracts a settlement rail so an agent-wallet
SDK can let an agent settle the same x402-priced payment on any rail it ships.
This package ships five concrete rails:

* ``NanoRail``    - the Nano (XNO) rail: feeless per transfer, sub-second
  finality, self-custodial (no freezeable stablecoin, no per-tx gas).
* ``UsdcRail``    - the status-quo stablecoin rail on EVM/Base: charged a fee
  and network gas for every transfer.
* ``SkyfireRail`` - Skyfire's closed US-dollar ledger, charged a fee.
* ``PaymanRail``  - the Payman agent-payments API, charged a fee.
* ``NeverminedRail`` - the Nevermined payments protocol, charged a fee.

The adapter rebuilds no payment logic on either rail; it wraps an existing
client per rail behind one interface (see ``scope-manifest.json`` for the
reused Nano tools). Payments in the shipped example are simulated against a
local stub so the repository is runnable with no wallet and no keys; the seams
to point ``NanoRail`` at a real Nano RPC / Nano x402 client are documented in
``README.md``.
"""
from .rails import (
    PaymentRail,
    NanoRail,
    UsdcRail,
    SkyfireRail,
    PaymanRail,
    NeverminedRail,
    rail_for,
    settle,
)

__all__ = [
    "PaymentRail",
    "NanoRail",
    "UsdcRail",
    "SkyfireRail",
    "PaymanRail",
    "NeverminedRail",
    "rail_for",
    "settle",
]
__version__ = "0.1.0"
