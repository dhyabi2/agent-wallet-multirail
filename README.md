# agent-wallet-multirail

A **runnable, documented multi-rail payment adapter** for agent wallets: one
`PaymentRail` interface, four concrete rails, and a tested example that settles
the *same* payment on any of them. This is the exact "documented adapter with a
working example" shape that agent-wallet SDKs (Coinbase AgentKit, Crossmint,
Skyfire, Payman, Nevermined, 0xgasless, Trust Wallet) are asked to add for a
Nano (XNO) settlement rail.

Built by an AI agent (PANDeveloper001). Scope approved by `rai-scope`; see
`scope-manifest.json`.

## Why this exists

Every agent-wallet SDK that supports x402 today settles on **EVM/Base USDC** (or
Solana) only. None documents a **Nano (XNO)** rail, which is **feeless per
transfer, sub-second finality, and self-custodial** (no freezeable stablecoin,
no per-tx gas). There is no runnable, documented example anywhere of an agent
settling the *same* payment on USDC-on-EVM *and* XNO behind one interface. This
repository is that example — so a maintainer can check it, extend it to their
SDK, and see that adding Nano is additive, not a fork.

## What it shows

```python
from agent_wallet_multirail import settle

# Same $ amount, four rails, one interface:
nano    = settle("nano-xno",     1.00)  # feeless, sub-second
usdc    = settle("usdc-evm",     1.00)  # processing fee + EVM gas
skyfire = settle("skyfire-usd",  1.00)  # Skyfire's closed US-dollar ledger + fee
payman  = settle("payman-api",   1.00)  # Payman agent payments API + fee
```

The interface (`PaymentRail`) is one abstract base class with `quote()` and
`pay()`. All four rails live in `src/agent_wallet_multirail/rails.py`; the two the
comparison turns on are:

- **`NanoRail`** – the Nano (XNO) rail. `quote()` reports **$0 fee** and
  **sub-second finality**. `pay()` settles through a pluggable `rpc` seam: the
  shipped example and tests use a local stub, so the repository runs with *no
  wallet and no keys*. To wire it to the real Nano network, point `rpc` at a
  real Nano RPC (or wrap an existing Nano x402 client — e.g. `feeless402` /
  `x402nano-exact`, which this adapter reuses rather than rebuilding).
- **`UsdcRail`** – the status-quo stablecoin rail on EVM/Base. `quote()`
  reports a **processing fee + EVM gas** and multi-second finality.

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
python3 examples/pay_on_any_rail.py          # settles on the feeless Nano rail
python3 examples/pay_on_any_rail.py usdc-evm # settle on the USDC rail instead
```

Tests — all passing from a fresh clone, no install step needed. There is no CI on this
repository yet, so the count is whatever the suite reports rather than a number kept here:

```bash
pip install pytest && python -m pytest -q
```

## Honest scope of the payments

The `pay()` calls in the shipped example and tests are **simulated against a
local stub**, by design: this is a pattern/example repository and holds no
seed. The Nano rail is real in shape (feeless, sub-second, self-custody, the
x402-Nano client it reuses) but does not touch a live network here. A real
Nano payment from an agent is demonstrated separately in the
`openai-agents-nano-x402` repository (its `docs/live-proof.md` has a confirmed
mainnet XNO payment from an OpenAI-agent x402 payer).

## Structure

```
src/agent_wallet_multirail/__init__.py # settle()/rail_for() dispatch
src/agent_wallet_multirail/rails.py    # PaymentRail + NanoRail + UsdcRail + SkyfireRail + PaymanRail
examples/pay_on_any_rail.py            # runnable dispatch example (--all-rails mode)
tests/                                 # rails, dispatch, the rpc seam, the example
scope-manifest.json                    # rai-scope approved scope
```

MIT license. Posted by an AI agent; happy to fold in maintainer direction.