# agent-wallet-multirail

A **runnable, documented multi-rail payment adapter** for agent wallets: one
`PaymentRail` interface, five concrete rails, and a tested example that settles
the *same* payment on any of them. This is the exact "documented adapter with a
working example" shape that agent-wallet SDKs (Coinbase AgentKit, Crossmint,
Skyfire, Payman, Nevermined, 0xgasless, Trust Wallet) are asked to add for a
Nano (XNO) settlement rail.

Built by an AI agent (PANDeveloper001). Scope approved by `rai-scope`; see
`scope-manifest.json`.

## Install

One line, pinned to the v0.1.0 tag, run in a clean venv (`pip show` reports
`agent-wallet-multirail 0.1.0`; `import agent_wallet_multirail` and the
`mandate` command both work). No runtime dependencies:

```bash
pip install "agent-wallet-multirail @ git+https://github.com/dhyabi2/agent-wallet-multirail@v0.1.0"
```

To run the examples and tests, clone the repo and `pip install -e .` instead
(see [Run it](#run-it)).

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
    from_currency="USDC", from_network="BASE",   # the ticker sent is USDC-BASE
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
pip install -e .                                      # the examples import the package
python3 examples/pay_nano_quote_from_usdc.py          # the whole hop, offline
python3 examples/pay_nano_quote_from_usdc.py refuse   # the shortcut, refused (exits 1 by design)
```

### What it refuses, and why each one costs money

| refusal | what it stops |
| --- | --- |
| `swap_destination_is_payee` | swapping straight to the seller: wrong amount, unbound block |
| `estimate_below_quote` | a swap whose estimated output is under the quote **plus headroom** — spending the USDC on it leaves the payment unmakeable and the USDC gone |
| `swap_not_received_yet` | sending before the XNO has actually arrived; a one-raw shortfall sends nothing |
| `exceeds_cap` | more USDC leaving than `max_from_amount`; a swap is custodial for the duration, and this cap is the only real bound |
| `no_order_log` / `order_key_reused` | buying the swap twice — a retry after a crash reads the recorded order back instead of creating a second. The key is recorded as pending *before* the create-order request is sent (an entry with `"order": None`, `"pending": True` and a `refused` record whose reason is `order_unconfirmed`; it is overwritten once create-order answers, or removed when the request provably never left), and executing calls on one key are serialised within a process, so neither a crash mid-request nor two threads on one key can create two orders |
| `order_destination_changed` | an order that came back paying out somewhere other than the account it was created for, or to a string that is not a Nano account at all |
| `order_terms_changed` | an order that asks for more input than the hop was planned on, or commits to less XNO than the quote. Checked on any provider's order (a `SwapOrder`, any object with its attributes, or a mapping with its keys), and again on read-back from `order_log`. A refused order (or one whose reply cannot be read after `create_order` sent it) is still recorded under the `order_key`, marked refused, because `create_order` may be the call that funds: a retry under that key raises the same refusal and never creates a second order. The provider's own order object is what is recorded and returned |
| `provider_amount_not_a_string` | an XNO amount that arrived as a JSON number, or an order's expected output given as a `float`: a float cannot hold 30 decimals, so it is already lossy. An order's expected output may be an exact decimal XNO string or a finite `Decimal`; a plain `int` on an order object is refused as `provider_response_unrecognised`, because a bare int amount is the smallest unit everywhere else in this package. (`NanswapProvider` itself reads a JSON integer on the wire — `2` — as its exact digits, since a JSON integer is exact; it is the float form that is lossy) |
| `provider_response_unrecognised` | a response shape this code does not know — refused, never defaulted. For an order this means one that cannot be verified: a field missing, or an expected output, payout address or pay-in address that is missing, empty or unparseable, or an input that is not a positive integer of micro-USDC. That is distinct from `order_terms_changed` / `order_destination_changed`, which mean the order was read and its terms differ |
| `invalid_swap_pair` | a hop with no network (`from_network=""`), or a currency that already carries one (`"USDC-BASE"`). Refused before any request. 0.1.0 forwarded both to Nanswap's partner endpoints, which took the network as a separate field; the endpoints now used take only a ticker that names the chain (`USDC-BASE`), so forwarding either would send a ticker that names no chain, and guessing the chain of someone's USDC is how it is lost |
| `provider_refused` | the provider's own "no": a 4xx, or a reply whose body is an error (`{"error": ...}`), with the provider's words in the message. Nothing was created and nothing is recorded, so a retry may ask again — except an error reply to create-order that also carries an order `id`, which is `order_unconfirmed` |
| `provider_unreachable` | a request that provably never left the machine: connection refused, a host name that did not resolve, a proxy that refused the tunnel. Nothing is recorded and a retry may POST. A timeout, a reset or a reply cut short is *not* this — the request may have arrived — and on create-order is `order_unconfirmed` |
| `order_unconfirmed` | a second order after a create-order whose outcome is unknown: a 3xx (redirects are never followed, and the API key is never sent to another host), a 5xx, a timeout or dropped connection, an unreadable 2xx reply, an error reply carrying an order id (at any status, 4xx included; the id and the reply are kept in the record), an exception from a custom transport or provider that cannot be classified, or a process that stopped mid-request. The key is recorded and a retry under it raises this again and POSTs nothing; look the order up with the provider before creating another. Once the provider shows no order, `release_pending_order_key(order_log, order_key)` frees the key and the next call plans afresh |
| `invalid_api_key` / `invalid_request` | a request that cannot be sent as HTTP: an API key with whitespace in it (a trailing newline read from a file or an environment variable), or a header or URL that `http.client` would refuse mid-request. Refused before anything is opened, so nothing is recorded and the `order_key` stays free; the key is refused, never trimmed, and never repeated in any message or `order_log` entry |
| `order_key_not_releasable` | `release_pending_order_key` on a key that holds a created order (read or refused) or a send: freeing it would buy the swap, or pay the seller, a second time |
| `order_network_unconfirmed` | funding an order whose reply names a ticker other than the planned one (`from: "USDC-BASE"` on a `USDC-BSC` plan): its pay-in address may be on another chain, and USDC sent on the wrong chain does not come back. A reply with no `from` is read — the request already named the chain |

Two bars, on purpose: the swap's *estimate* must clear the quote plus headroom,
but a created order's *committed* output is held to the quote itself, inclusive.
The send-time check is `received >= quote`, so that is the bar an order must
be able to meet; an order whose committed output sits exactly at the quote has
no margin left, and a floating-rate delivery that lands below its commitment
then waits as `swap_not_received_yet` rather than being sent short.

A log written by an older version (entries without `order_checked`) is read back
as it was written, so an order it accepted can still complete: the payout is still
the agent's own account and arrival is still checked against the quote. A key that
already sent always answers `send_already_attempted`, naming the block, first.

Every amount crosses this module as an integer (raw, micro-USDC) or an exact
decimal string. `float` is refused everywhere, in both directions.

### Upgrading from 0.1.0

- **The default transport raises `SwapRefused`, not urllib's errors.** With no
  `transport=`, `estimate`, `limits`, `order` and `create_order` used to let
  `urllib.error.HTTPError` / `URLError` through. They now raise `SwapRefused`
  with a stable `reason` (`provider_refused`, `provider_unreachable`, ...).
  Each one is *also* a `urllib.error.URLError` (so an `OSError`), so an
  existing `except urllib.error.URLError:` fallback still catches it; it is
  not an `HTTPError`, so code reading `exc.code` should read `exc.reason`
  instead. That covers `order_unconfirmed` from `create_order` (and from
  the hop call that made the request) when an HTTP failure caused it.
  Refusals this module raises on its own (`no_api_key`, `invalid_api_key`,
  `invalid_swap_pair`, a refused order's terms, a refusal read back from
  `order_log`) are plain `SwapRefused`. So are two that come from a reply
  that *was* read: `provider_refused` for an error body that came with
  HTTP 200 (`{"error": true, "message": ...}`; the same reason for an HTTP
  4xx/5xx status *is* a `URLError`), and `provider_response_unrecognised`
  for a JSON reply missing a field or carrying the wrong type (0.1.0 also
  raised a plain `SwapRefused` for those). A custom `transport` is unchanged on
  the read path: what it raises is classified, not wrapped. On
  `create_order` it is wrapped: an exception a custom transport raises
  there becomes `order_unconfirmed` (or `provider_unreachable` when it
  proves nothing was sent), and the original is the `__cause__`.
- **The exception 0.1.0 let through is still in the refusal's type.** 0.1.0
  let a read `TimeoutError` (`socket.timeout`), a `ConnectionResetError`,
  `http.client.HTTPException` (`IncompleteRead`, `RemoteDisconnected`),
  `json.JSONDecodeError` (a reply that is not JSON) and `UnicodeDecodeError`
  escape the default transport. Each is now a `SwapRefused` (and a
  `URLError`) that is *also* an instance of that original class (for
  `UnicodeDecodeError`, of `ValueError`), so `except TimeoutError`, `except
  ValueError` and `except http.client.HTTPException` still catch it, and
  the original is the `__cause__`. That includes `order_unconfirmed` from
  `create_order` when one of these caused it.
- **Amounts on the wire keep their exact text.** The default transport
  parses JSON with `parse_float=str`, so a JSON number such as
  `15.458333333333334` arrives as that string, never as a float.
  `SwapOrder.raw` (and the `raw` kept in `order_log`) therefore holds such
  numbers as strings where 0.1.0 held floats; JSON integers stay `int`.
- **Patching `urllib.request.urlopen` still intercepts the default
  transport.** `urlopen` is looked up on every request, and a replaced one
  is called instead of the network, so a test suite that mocked it for
  0.1.0 still never reaches `api.nanswap.com`. An opener installed with
  `urllib.request.install_opener` (a fake `https_open` handler, a custom CA,
  a proxy, an auth handler) is used as 0.1.0 used it: its handlers carry the
  request, with the redirect handler replaced so no redirect is followed,
  and the installed opener itself is not modified.
  `agent_wallet_multirail.swap._open` is the narrower patch point. The
  unpatched path never follows a redirect.
- **An order reply naming another chain is refused
  (`order_network_unconfirmed`).** New: a create-order reply whose `from`
  names a ticker other than the planned one is never funded, and the
  order is recorded under the `order_key` so a retry creates no second one.
- **An amount too long to be one is refused.** A decimal amount string past
  Python's 4300-digit `int()` limit (in `usdc_to_micro`, `xno_to_raw`,
  `parse_raw` or an order reply) is refused `invalid_amount` /
  `provider_response_unrecognised` instead of escaping as a `ValueError`; in
  an order reply the order is recorded under the `order_key`.
- **An API key with whitespace is refused (`invalid_api_key`).** 0.1.0 let
  `http.client` raise a `ValueError` quoting the key. Nothing is sent and
  the `order_key` stays free; strip the key where it is read.
- **`nanswap_ticker` refuses a currency or network that is not
  alphanumeric** (`invalid_swap_pair`), before any request.
- **A key left `order_unconfirmed` stays that way until released.** A
  create-order whose outcome is unknown -- including an exception a custom
  provider raises that cannot be classified (a `ValueError`, a requests-style
  `ConnectionError`) -- leaves the `order_key` recorded, and every retry
  under it raises `order_unconfirmed` and creates nothing. 0.1.0 created the
  order on retry. Look the order up with the provider; if there is none, call
  `release_pending_order_key(order_log, order_key)` and retry. A provider that
  can tell a never-sent failure apart should raise `ConnectionRefusedError` /
  `socket.gaierror` (or a `URLError` wrapping one), which frees the key itself.
- **`NANSWAP_*_PARTNER` no longer name the partner endpoints.** They still
  import, but each is now the plain path (`NANSWAP_CREATE_ORDER_PARTNER ==
  "/create-order"`). Code that built its own partner request from them --
  `from: "USDC"` plus a separate network field -- now posts that body to
  `/create-order`, which wants a ticker naming the chain (`USDC-BASE`). Use
  `NanswapProvider`, or build the ticker with `nanswap_ticker`.
- **`from_network` is joined into the ticker; `to_network` is not sent.**
  `estimate` and `limits` accept `to_network` for 0.1.0 callers and echo it on
  the `SwapEstimate`, but it is dropped from the request: the output is always
  XNO on Nano mainnet and the plain endpoints have no field for it.

### Two honest limits

1. **The quote half was run against the live API; the order half was not.**
   On 2026-11-12 `limits` and `estimate` were run against `api.nanswap.com` for
   `USDC` on `BASE` and `BSC`, and a real seller's 402 entry was planned end to
   end with `execute=False`. That first contact found the provider refused every
   real quote (Nanswap sends amounts as JSON numbers; urllib's default
   User-Agent is answered 403). Both are fixed and the real replies are pinned
   in `tests/test_swap.py` (`NanswapAsItAnsweredLive`). **Creating an order
   needs a Nanswap API key (the API answers 401 without one) and none was
   available, so no order has been created and no USDC has been swapped with
   this code.** The order reply is parsed field by field, anything unrecognised
   is refused, and an order whose reply names a ticker other than the planned
   one (`USDC-BASE`) is refused as `order_network_unconfirmed` and never
   funded (a reply that names none is read: the request already named it). The first person with a key should create one small order and
   reconcile `_order_from`.
2. **A swap is custodial for the duration of the hop.** USDC leaves the agent's
   control and arrives as XNO only if the provider performs. Nothing here makes
   that leg trustless; `max_from_amount` is required, not optional.

There is also no reverse estimate for a USDC route (`get-estimate-reverse`
answers "from ticker invalid" for `USDC-BASE`), so there is no way to ask "what
input yields exactly this output". That is why the planner takes an
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
python3 -m venv .venv && . .venv/bin/activate && pip install "agent-wallet-multirail @ git+https://github.com/dhyabi2/agent-wallet-multirail@v0.1.0"
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