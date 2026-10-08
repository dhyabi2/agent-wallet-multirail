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

## Paying an XNO quote with a wallet that holds only USDC

pursekeeper.dev names this gap in its own words: *"the next bet is a
swap-in-the-payment-flow (an agent with USDC pays a Nano seller through a
Nanswap-style hop)"*, because *"Nobody in the x402 buyer population holds
Nano"*. A seller can advertise an XNO price all day; an agent whose wallet holds
USDC cannot pay it.

```python
from agent_wallet_multirail import NanoQuote, NanswapProvider, pay_nano_quote_from_usdc

quote = NanoQuote.from_x402_entry(seller_402["accepts"][0])   # payTo + exact raw

plan = pay_nano_quote_from_usdc(                 # execute=False by default:
    quote, my_own_nano_account, NanswapProvider(api_key=KEY),
    from_currency="USDC", from_network="BSC",
    from_amount="1", max_from_amount="2",        # the only bound on the spend
    order_key="invoice-7",                       # what makes a retry idempotent
)                                                # ...so this spends nothing
```

The hop is three legs, and **only the middle one is a swap**:

```
USDC  --(swap provider)-->  XNO in the agent's OWN account  --(send)-->  seller
```

The third leg is an ordinary feeless XNO send of the quote's **exact** raw
amount, made by `NanoRail.pay_to` under whatever operator mandate is already in
force. That split is the whole design, and `swap.py` refuses the shortcut that
collapses it: pointing the swap straight at the seller looks like it saves a
leg, and it breaks the payment three ways at once — the provider sends whatever
the swap *yielded* rather than the quote's exact raw, the block comes from the
provider's account so it is not bound to this agent's order, and a shortfall is
then discovered by the seller instead of refused before the USDC is gone.

```bash
python3 examples/pay_nano_quote_from_usdc.py          # the whole hop, offline
python3 examples/pay_nano_quote_from_usdc.py refuse   # the shortcut, refused
```

### What it refuses, and why each one costs money

| refusal | what it stops |
| --- | --- |
| `swap_destination_is_payee` | swapping straight to the seller: wrong amount, unbound block |
| `estimate_below_quote` | a swap whose estimated output is under the quote **plus headroom** — spending the USDC on it leaves the payment unmakeable and the USDC gone |
| `swap_not_received_yet` | sending before the XNO has actually arrived; a one-raw shortfall sends nothing |
| `exceeds_cap` | more USDC leaving than `max_from_amount`; a swap is custodial for the duration, and this cap is the only real bound |
| `no_order_log` / `order_key_reused` | buying the swap twice — a retry after a crash reads the recorded order back instead of creating a second |
| `order_destination_changed` | an order that came back paying out somewhere other than the account it was created for |
| `provider_amount_not_a_string` | an XNO amount that arrived as a JSON number: that is a float, which cannot hold 30 decimals, so it is already lossy |
| `provider_response_unrecognised` | a response shape this code does not know — refused, never defaulted |

Every amount crosses this module as an integer (raw, micro-USDC) or an exact
decimal string. `float` is refused everywhere, in both directions.

### Two honest limits

1. **No live call to a swap provider has been made.** The *requests*
   `NanswapProvider` builds are checked against the URLs, query parameters and
   header name of the published `nanswap` npm client 1.0.3 — the only shipped
   client (the PyPI package of the same name is an empty sdist that installs no
   module at all, and fails to build). The *responses* it parses are **not**
   verified against the live API, which was unreachable from the environment
   this was written in, so every field is validated and anything unrecognised is
   refused rather than guessed at. The first person who can reach
   `api.nanswap.com` should run one real quote and reconcile `_order_from`.
2. **A swap is custodial for the duration of the hop.** USDC leaves the agent's
   control and arrives as XNO only if the provider performs. Nothing here makes
   that leg trustless; `max_from_amount` is required, not optional.

There is also no reverse estimate for Nanswap's partner (cross-chain) routes —
it exists only for the native pairs — so there is no way to ask "what input
yields exactly this output" for a USDC hop. That is why the planner takes an
input amount and refuses one whose estimated output is short, rather than
solving for the input: the guard runs in the direction the API offers.

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
python3 examples/pay_on_any_rail.py          # settles on the feeless Nano rail
python3 examples/pay_on_any_rail.py usdc-evm # settle on the USDC rail instead
python3 examples/payclaw_nano_rail.py        # PayClaw-shaped: USDC vs Nano behind one pay()
python3 examples/gasless_x402_nano_rail.py   # 0xGasless-shaped: XNO settle rail for the x402 pay path
```

Tests — all passing from a fresh clone, no install step needed. `.github/workflows/test.yml`
runs the suite and an out-of-tree import on every push and pull request; the count is whatever
the suite reports rather than a number kept here, which is why none is printed:

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