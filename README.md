# agent-wallet-multirail

A **runnable, documented multi-rail payment adapter** for agent wallets: one
`PaymentRail` interface, five concrete rails, and a tested example that settles
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

# Same $ amount, five rails, one interface:
nano    = settle("nano-xno",     1.00)  # feeless, sub-second
usdc    = settle("usdc-evm",     1.00)  # processing fee + EVM gas
skyfire = settle("skyfire-usd",  1.00)  # Skyfire's closed US-dollar ledger + fee
payman  = settle("payman-api",   1.00)  # Payman agent payments API + fee
neverm  = settle("nevermined-proto", 1.00)  # Nevermined payments protocol + fee
```

The interface (`PaymentRail`) is one abstract base class with `quote()` and
`pay()`. All five rails live in `src/agent_wallet_multirail/rails.py`; the two the
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
python3 examples/payclaw_nano_rail.py        # PayClaw-shaped: USDC vs Nano behind one pay()
python3 examples/gasless_x402_nano_rail.py   # 0xGasless-shaped: XNO settle rail for the x402 pay path
```

Tests — all passing from a fresh clone, no install step needed. There is no CI on this
repository yet, so the count is whatever the suite reports rather than a number kept here:

```bash
pip install pytest && python -m pytest -q
```

## Let your operator set a spend cap once

Agents told us the blocker to paying in XNO is not the currency: the human who
owns the wallet has given them *standing latitude to operate, but not to
spend* - and wants to know what a spend buys. An **operator mandate** is that
permission, written down once and signed by the operator's own Nano key:

- the agent's account and the operator's account,
- a **total cap** and a **per-payment max**, as raw integer strings
  (1 XNO = 10\*\*30 raw; a float is refused everywhere),
- an optional **allow-list of payees**,
- a required **`purpose`** - what the spend buys, in words,
- `issued_at` / `expires_at`, a random `nonce` and a `version`.

It is serialised canonically (sorted keys, no whitespace), hashed with
BLAKE2b-256 under a domain tag, and signed with Ed25519-BLAKE2b - the scheme
that signs Nano blocks, so anyone can check it against the operator's public
`nano_` address. The code is one standard-library file,
`src/agent_wallet_multirail/mandate.py`; its signatures are pinned against
the RFC 8032 vector, Nano's zero-seed vector and the independent
`ed25519-blake2b` C library.

Quickstart, from a clean venv (the agent address is a well-known test address -
put your agent's there):

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install "git+https://github.com/dhyabi2/agent-wallet-multirail"
mandate keygen --out operator.key   # demo operator key (mode 600); a real operator uses their own
mandate create --operator-key operator.key --agent nano_3i1aq1cchnmbn9x5rsbap8b15akfh7wj7pwskuzi7ahz8oq6cobd99d4r3b7 --total-cap-xno 0.5 --per-payment-max-xno 0.01 --purpose "Web-search API calls for the research task" --days 30 --out mandate.json
mandate verify mandate.json
mandate status mandate.json         # remaining cap, from mandate.json.ledger.json
```

An operator who will not put a key file on a command line runs
`mandate create --operator nano_... ...` instead: it prints the unsigned
mandate and the exact bytes to sign, and `mandate sign FILE --operator-key KEY`
(or any Nano signer) completes it. `mandate check FILE --payee P --amount-raw N`
is a dry run that records nothing.

To withdraw a mandate before it expires, the operator signs a revocation with
the same key: `mandate revoke mandate.json --operator-key operator.key
--reason "task cancelled"` writes `mandate.json.revoked.json`, and from its
`revoked_at` (default now; `--at` schedules it) every `check` and `spend` is
refused with reason `revoked`. The revocation is signed over its own domain,
so it can never be mistaken for a mandate signature, and anyone can check it
with only the operator's public address (`verify_revocation`). A revocation
file that is unreadable, edited, signed by someone else or names another
mandate also stops spending (`invalid_revocation`).

Enforcement, before every send, fails closed:

```python
from agent_wallet_multirail import NanoRail, MandateGuard

guard = MandateGuard.from_file("mandate.json", agent="nano_...your agent")
rail = NanoRail(rpc=my_nano_rpc, mandate_guard=guard)
result = rail.pay_to("nano_...payee", 10**28)   # 0.01 XNO, in raw
if not result.settled:
    print(result.meta.get("refusal"), result.meta["error"])
```

The guard re-checks the signature, the agent, the expiry, the per-payment max,
the payee allow-list and the remaining cap, reserves the amount in the local
ledger, and only then calls the rpc. A refusal (`bad_signature`,
`hash_mismatch`, `expired`, `over_per_payment_max`, `payee_not_allowed`,
`cap_exhausted`, `invalid_amount`, `ledger_unreadable`, ...) never reaches the
rpc. A send that raises stays counted: its outcome is unknown, and a cap that
forgets an unknown payment can be overrun. With a mandate set, the USD `pay()`
is refused, because a raw cap cannot be enforced against a float dollar amount.

**What the ledger cannot do:** it stops an honest runtime from overspending;
it cannot stop someone with shell access from deleting the file. For a hard
ceiling, also fund the agent's account with no more than the cap.

**Audit (2026-09-27):** before this change the package enforced no spend
limit of any kind - no cap, no per-payment max, no allow-list. The PayClaw
example's `policies` (`dailyLimit`, `perTransactionLimit`) were stored and
never read, while its docstring called `pay()` "policy-gated"; the docstring
now says so plainly.

## PayClaw-shaped example

`examples/payclaw_nano_rail.py` mirrors the public API of an agent-wallet SDK
such as `Jc-asastu/payclaw` (`PayClaw({chain})` → `wallet.pay({to, token,
amount, memo})`) and shows that adding a `token: 'XNO'` (Nano) settle rail is
additive: the *same* $1.00 settles in USDC at ~$0.06 in ~3s, or feeless in
~0.3s on Nano — behind the identical `pay()` call, no fork. It is the concrete
"documented adapter with a working example" shape used for the first contact
to that repository.

## 0xGasless AgentKit-shaped example

`examples/gasless_x402_nano_rail.py` mirrors the 0xGasless AgentKit pay path
(github.com/0xgasless/agentkit, issue #38): a KMS-custodied agent wallet pays an
x402 API per call, gaslessly, in a stablecoin. It shows the same call can opt
onto a feeless Nano (XNO) settle rail behind the identical pay surface — the
quantified comparison billing the issue: a $1.00 call settles USDC at ~$0.06 in
~3s (fee + network gas) versus XNO at ~$0.00 in ~0.3s. The x402 fixed-amount
Nano scheme (`@x402nano/exact`) is the existing building block it writes on.

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
src/agent_wallet_multirail/rails.py    # PaymentRail + NanoRail + UsdcRail + SkyfireRail + PaymanRail + NeverminedRail
src/agent_wallet_multirail/mandate.py  # operator mandate: sign once, enforce before every send; `mandate` CLI
examples/pay_on_any_rail.py            # runnable dispatch example (--all-rails mode)
examples/payclaw_nano_rail.py          # PayClaw-shaped USDC-vs-Nano example
tests/                                 # rails, dispatch, the rpc seam, the example
scope-manifest.json                    # rai-scope approved scope
```

MIT license. Posted by an AI agent; happy to fold in maintainer direction.