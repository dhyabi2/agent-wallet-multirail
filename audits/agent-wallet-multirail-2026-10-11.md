# agent-wallet-multirail — audit 2026-10-11

The Nano leg only, as Tier 0 requires. The USDC, Skyfire, Payman and Nevermined
rails were read only where the Nano path runs through them, and nothing on them
was changed. The lens: can an agent pay, or get paid, in XNO with this code
today without being hurt?

## What I checked

- Fast-forwarded to `master` (`7f7f2a7`) and ran the suite from a clean
  checkout: **191 passed** on 3.13. Note that `python3` in this environment is
  3.11 while `pip` targets 3.13, so `python3 -m pytest` reports "No module named
  pytest" even though pytest is installed; `/usr/bin/python3 -m pytest` is the
  one that runs. That is an environment detail, not a repository defect.
- `src/agent_wallet_multirail/rails.py` end to end: `NanoRail.quote`,
  `pay` (which fails closed to `mandate_requires_raw` whenever a guard is set,
  because a float dollar amount cannot be checked against a raw-integer cap),
  `pay_to`, and `_settlement`'s fail-closed read of the node's reply — an
  `error` key, an empty block, or a `confirmed` that is neither `True` nor the
  string `"true"` all give `settled=False` with a reason.
- `mandate.py`'s money arithmetic: `parse_raw` refuses floats, bools, non-ASCII
  digits, leading zeros and anything outside 1..2**128-1; `xno_to_raw` is exact
  integer placement with a 30-decimal bound and refuses an empty string rather
  than reading it as zero; `raw_to_xno` round-trips. No float appears on any
  amount anywhere on this path.
- The guard's reserve-before-send order in `MandateGuard.spend`: the ledger
  entry is written and the cap debited *before* `send()` is called, and a
  `send()` that raises leaves the entry `status: "unknown"` rather than
  releasing the reservation, so a cap cannot be overrun by a crash. `_read`
  refuses a ledger whose totals do not add up, one belonging to another
  mandate, and one it cannot parse. `_write` is atomic (`mkstemp` + `fsync` +
  `os.replace`) under an `flock`.
- Signature, hash, expiry, not-yet-valid, agent binding, payee allow-list,
  per-payment max, unknown-field rejection, and the revocation path including
  the `<mandate>.revoked.json` location the CLI actually writes.
- The README quickstart, run verbatim in a clean directory: `keygen`, `create
  --total-cap-xno 0.5 --per-payment-max-xno 0.01 --days 30`, `verify`, `status`.
  All four exit 0 and the caps come back as exact raw integers
  (`500000000000000000000000000000` and `10000000000000000000000000000`).
  The `## What it shows` snippet runs as written across all five rails.
- Every shipped example: `crossmint_nano_adapter`, `gasless_x402_nano_rail`,
  `hyperspace_nano_rail`, `pay_nano_quote_from_usdc`, `payclaw_nano_rail`,
  `pay_on_any_rail`. All exit 0 offline.
- `swap.py` in full — the USDC → XNO → seller hop, which is the newest and most
  money-critical code on this leg: `usdc_to_micro`/`micro_to_usdc` (exact
  integer micro-USDC), `_required_with_headroom` (ceiling in integers, bounded
  by `MAX_RAW`), `plan_swap_hop`'s refusals, `pay_nano_quote_from_usdc`'s
  order-log idempotency on the swap leg and `send_attempted` on the send leg,
  and `NanswapProvider`'s request shapes and response parsing.

## What I found

**One defect, on the swap leg of the XNO payment path, in two parts that share
one line of code and one cause: `NanswapProvider.create_order` checked the
payout *address* the provider returned but neither of the two *amounts*.**

`create_order` tells the provider three things — pay out to `plan.own_address`,
take `plan.from_amount` in, and (via the plan) deliver at least
`plan.required_to_amount_raw`. It then verified only the first on the way back
out. Its own comment states the principle it was not applying to the rest:
*"A payout address that is not the one asked for is the whole loss, so it is
refused here rather than noticed later."*

Reproduced against the real code with the module's own transport seam, on a
plan built by `plan_swap_hop` for a 1 XNO quote, 2 USDC in, `max_from_amount`
of 5 USDC (`src/agent_wallet_multirail/swap.py:636-657` on `7f7f2a7`):

- **The input the order asks for was unchecked.** An order coming back with
  `expectedAmountFrom: "500"` was **accepted**, returning
  `from_amount_micro = 500000000` and a `pay_in_address` to fund. The operator's
  `max_from_amount` cap — which this repository's own module docstring calls
  *"the only real protection"* and the README calls *"the only bound on the
  spend"* — is enforced by `plan_swap_hop` against the **estimate's** input
  only. It is the **order** the caller funds: both the address and the amount to
  send come from `SwapOrder`. So a provider that quotes 2 and invoices 500 took
  the pay-in straight past the one bound the hop has.
- **The output the order commits to was unchecked.** An order coming back with
  `expectedAmountTo: "0.000001"` against a 1 XNO quote was **accepted**.
  `plan_swap_hop` refuses `estimate_below_quote` precisely so the USDC is not
  spent on a swap that cannot cover the quote, but the order's own committed
  output never faced that bar. Funding it buys a swap that cannot pay the
  seller, and the shortfall is then discovered by
  `swap_not_received_yet` — after the USDC is gone. That is the failure the
  module's docstring says it exists to refuse.
- **A third part, same line: the refusal leaked the wrong exception type.**
  `payoutAddress: "not-an-address"` is a string, so `_field` and
  `_exact_decimal` pass it through, and `normalise_address` then raised
  `MandateRefused` out of `create_order`. Every other refusal on this path is a
  `SwapRefused`, and the README documents that surface, so a caller that
  catches the documented exception took this as an unhandled crash at the spend
  leg.

## What I fixed

`fix/order-terms-checked-against-the-plan` — the created order's three fields
are now all checked against the plan that asked for them, in the place the
address was already checked:

- `order.from_amount_micro > plan.from_amount_micro` → `order_terms_changed`.
  Only *more* is refused; an order asking for **less** is still allowed, since
  that costs the agent nothing. There is a test for each direction.
- `xno_to_raw(order.expected_to_amount) < plan.required_to_amount_raw` →
  `order_terms_changed`. The bar is the same one the estimate had to clear, and
  it is inclusive — exactly `required_to_amount_raw` passes, with a test.
  Refusing here is free: the order is simply never funded.
- A non-numeric `expectedAmountTo`, and a `payoutAddress` that is not an
  account, are now `SwapRefused` rather than an escaping `MandateRefused`.

The change adds only `raise` statements and one local variable. It narrows what
is accepted and widens nothing; it changes no amount, no destination, no
rounding and no key path.

**Evidence.** Six tests added. With `swap.py` reverted to `master` and the new
tests alone run, **4 fail** (`order_asking_for_more_input`,
`committing_to_less_xno`, `expected_output_is_not_a_number`,
`paying_out_to_a_non_account`) and the **2 controls pass** — those two assert
that an order asking for less input, and one committing to exactly the required
output, are still *allowed*, so they pass both before and after and prove the
fix does not over-refuse. With the fix: **197 passed** (was 191) on the branch
merged with `master`, `py_compile` clean, and all six examples still exit 0.

## What I could not verify

- **Any of this against the live Nanswap API.** `api.nanswap.com` answers 403 to
  CONNECT under this environment's network policy, so the response shapes
  remain as the repository already documents them: checked against the published
  `nanswap` npm client 1.0.3, not against a live reply. My fix reads only
  `expectedAmountFrom` and `expectedAmountTo`, the two fields `_order_from`
  already parsed, so it adds no new assumption about the provider's shape — but
  whether a real order ever legitimately comes back below
  `required_to_amount_raw` while still covering the quote is not something I
  can observe from here. If it does, the refusal is conservative by one
  headroom's width, and the alternative bar (`plan.quote.amount_raw`) is one
  line away.
- **Whether a real XNO send settles.** Every rail here runs against the
  documented `rpc` stub seam; no block was signed or broadcast, and no wallet or
  key was used.
- **The USDC pay-in leg.** This module never moves USDC — the caller funds
  `pay_in_address` out of band — so the cap this audit found unenforced is
  enforced on a number the caller reads, not on a transfer this code makes.
