# agent-wallet-multirail — code audit, 2026-10-09 (Nano leg only)

Previous audit 2026-10-08 (`87a4c27`). Scope is the **Nano (XNO) leg** only: the USDC→XNO swap
hop exists to fund an XNO payment, so it is read as the Nano leg's funding path. The USDC,
Skyfire, Payman and Nevermined rails are out of scope and were not touched.

HEAD audited: `origin/master` at `87a4c27`. Python 3.11.17.

Baseline before any change, as `.github/workflows/test.yml` runs it:

```
$ python3 -m pytest -q                        # 182 passed
$ python3 -m compileall -q src tests examples  # clean
$ python3 -m pip install .                     # agent-wallet-multirail-0.1.0
$ for e in examples/*.py; do python3 $e; done  # all exit 0
```

## Found and fixed — a retry after a paid send was told nothing was sent

`pay_nano_quote_from_usdc` checked the two refusals in the wrong order
(`src/agent_wallet_multirail/swap.py:773` and `:790` on `master`):

```python
after = _integer_balance(balance_raw, "after the swap")
received = after - before
if received < plan.quote.amount_raw:
    raise SwapRefused("swap_not_received_yet", "... Nothing was sent. Call again with
                       order_key %r once it has settled ...")
...
attempted = recorded.get("send_attempted") if recorded is not None else None
if attempted is not None:
    raise SwapRefused("send_already_attempted", "... Check the account's history for that
                       block before sending anything else")
```

A send that happened takes the quote back out of the account, so all the balance still holds is
the headroom the hop planned to leave — at `DEFAULT_SLIPPAGE_BPS = 100` (`swap.py:83`) that is
**1% of the quote**, which is less than the quote. The arrival check therefore fires first and
`send_already_attempted` is **unreachable at the module's own default slippage**.

Measured on `master`, one hop, default slippage, provider delivering exactly the 1.01 XNO the
plan requires for a 1 XNO quote, and a rail whose balance falls by what it sends:

```
call 1 (the pay) : SENT, settled=True, orders=1
                   balance after the send = 10000000000000000000000000000 raw (the 1% headroom)
call 2 (a retry) : refused 'swap_not_received_yet'
  >>> the swap has delivered 10000000000000000000000000000 raw of the
      1000000000000000000000000000000 the quote needs (order ord-1). Nothing was sent.
      Call again with order_key 'invoice-7' once it has settled ...
sends actually made: 1
but the log one line away records: {'pay_to': 'nano_3t6k…', 'amount_raw':
      '1000000000000000000000000000000', 'outcome': 'settled', 'tx_ref': 'BLOCK1'}
```

So the operator is told their payment never happened, and instructed to keep calling, on an
invoice that is **already paid and settled**. A caller that loops on `swap_not_received_yet` —
which that message tells it to do — loops for ever and concludes the seller was never paid. The
one sentence #8 added to stop a second out-of-band payment ("Check the account's history for
that block") is the sentence nobody ever sees.

**Fixed** by checking `send_attempted` before the arrival check. Both branches refuse and
neither sends, so **no money moves differently** — only what the operator is told. The refusal
that knows a send happened now gets to speak first, and names the block:

```
retry now refuses: 'send_already_attempted'
  >>> order_key 'invoice-7' has already sent (or attempted) 1000000000000000000000000000000
      raw to nano_3t6k… Check the account's history for that block …
sends made: 1
```

**Why the existing tests could not see it.** All three tests that pin `send_already_attempted`
(`tests/test_swap.py:462`, `:484`, `:497`) use `RecordingProvider(to_amount="3")` — a 3 XNO
delivery for a 1 XNO quote, 200% over the module's own default headroom — together with a
*constant* balance callable (`state = {"balance": 0}`; `balance = lambda: state["balance"]`)
that is set to `3 * RAW` and **left there after `pay_to` has sent**. Both together are what let
those tests reach the refusal, and neither can happen with a real `balance_raw()` at
`DEFAULT_SLIPPAGE_BPS`. The new tests add a `DebitingRail` whose account balance actually falls
by what it sends, which is the thing the suite had no stand-in for.

Eleven tests added. **Four fail with `swap.py` alone reverted to `master`** and pass with the
fix; the rest are controls, including that a swap which genuinely has not landed is still told
so, that a partial delivery is still refused before any send, and that the first send still
happens:

```
test_a_retry_after_a_settled_send_says_a_send_already_happened
test_a_send_that_did_not_settle_is_also_reported_as_attempted
test_the_retry_is_never_told_to_call_again_on_a_paid_invoice
test_the_retry_names_the_block_that_paid_so_it_can_be_checked
```

After the fix: **191 passed** (182 before), `compileall` clean, all six examples exit 0.

## Found, NOT fixed — the order's own amounts are never checked against the plan

`NanswapProvider.create_order` (`swap.py:646-655`) makes exactly one check on the order that
comes back, and it is the destination:

```python
order = self._order_from(payload, "create-order %s" % plan.order_key)
if normalise_address(order.to_address) != plan.own_address:
    raise SwapRefused("order_destination_changed", ...)
return order
```

`_order_from` (`swap.py:657-670`) also parses `expectedAmountTo` into
`SwapOrder.expected_to_amount` and `expectedAmountFrom` into `SwapOrder.from_amount_micro`.
**Neither is ever compared to anything** — `grep -rn "expected_to_amount" src/` finds only the
dataclass field and its assignment. The two guards the README describes (`estimate_below_quote`
and the `max_from_amount` bound) run in `plan_swap_hop` against the **estimate**, the
non-binding pre-order quote, and nothing re-runs them against the **order**, which is the
binding thing and the thing the agent then pays. So an order promising far less XNO than the
estimate the guard passed, or demanding far more USDC than `max_from_amount` allows, is created
and committed without a refusal — which is exactly the loss `estimate_below_quote` was written
to prevent, moved one step later to where nothing looks.

**Not fixed in this run, and this is a judgement rather than a shortage of time.** The fix is
refusal-only in shape (compare the order against the plan, refuse on divergence), but it needs
a tolerance decided: a provider legitimately re-quotes between estimate and order, so the
question is how much divergence is normal and how much is the loss. Picking that number is the
owner's, not a routine's — and getting it wrong refuses hops that should settle. Listed for
the owner. The same blind spot one step later is the 2026-10-08 audit's still-open item below.

## Previously reported — still open

- **`swap.py:773-775`, the 2026-10-08 "found, NOT fixed" item, unchanged.** The arrival check is
  an account-wide balance delta with nothing tying it to `order.order_id`, so XNO that is not
  the swap's satisfies it. `NanswapProvider.order(order_id)` (`swap.py:631-633`) exists and the
  hop still never calls it. That audit's owner question — should the hop require a provider that
  can report a per-order payout, and refuse to execute without one? — is still unanswered. My
  reorder above does not touch it: it changes which refusal speaks, not what the arrival check
  measures.
- **Two minor CLI items, unchanged.** `mandate sign FILE --operator-key KEY` prints to stdout
  and does not write back, and `--out <same file>` is refused `file_exists`, so README:179-182's
  "completes it" does not complete the file. `mandate sign` on malformed JSON gives a raw
  `JSONDecodeError` traceback where `verify` and `status` both print clean refusal JSON.

## Checked and clean

- **No `decimal` and no float on any amount.** `grep -rn "decimal\|Decimal" src/ examples/`
  finds only prose in docstrings — no `import decimal` and no `Decimal(...)`, so none of the
  process-global-context rounding found in the sibling repositories can be present here.
  `xno_to_raw` is `int(whole) * 10**30 + int(frac.ljust(30, "0"))`; `_required_with_headroom`
  (`swap.py:350`) is an integer ceiling; `usdc_to_micro`/`micro_to_usdc` are integer. The only
  `float` in `src/` is `mandate._refuse_float` (`mandate.py:625`), the `json.loads` hook that
  refuses one.
- **No shell and no path sink.** `grep -rn "os.system\|subprocess\|shell=True\|eval(\|exec(\|
  pickle\|__import__" src/ examples/` finds nothing. Every `open()` in `src/` takes a
  CLI-supplied or constructor-supplied path; nothing a payer or a provider submits reaches one.
- **Verification trusts nothing the payer submits.** `verify_signed` (`mandate.py:490-518`)
  recomputes the hash before comparing it and checks the signature against the operator address
  *in the document*, with the agent pinned separately. `MandateGuard._check`
  (`mandate.py:731-744`) compares the payee as a 32-byte public key, so an `xrb_`/`nano_`
  spelling cannot make the guarded payee and the RPC's payee diverge. `_settlement`
  (`rails.py:152-178`) fails closed on a missing or non-`"true"` `confirmed`.
- **No committed secret, tree or history.** 37 distinct paths across all 57 commits; nothing
  matching `*.key`, `*.pem`, `.env`, `seed`, `secret` or `credential` with a value. The only
  `seed`/`private_key` occurrences are the `load_private_key` docstring and `keygen`'s writer
  (`mandate.py:816-823`, `:905`). The hex-64 blobs in history are mandate hashes, signatures
  and the RFC 8032 / Nano zero-seed test vectors. `NANSWAP_API_KEY_HEADER` is a header *name*;
  `api_key` is a never-defaulted, never-logged constructor parameter. `mandate keygen --out`
  writes `0o600`, verified `-rw-------`.
- **The README quickstart runs.** `pip install "git+https://github.com/dhyabi2/agent-wallet-multirail"`
  works in a fresh venv, and the full mandate flow (README:173-176 — `keygen` → `create
  --total-cap-xno 0.5` → `verify` → `status`) runs clean, exit 0, `remaining_xno: "0.5"`. This
  closes a "could not verify" from the 2026-10-08 audit.

## Could not verify

- **No live Nanswap and no live Nano node.** `api.nanswap.com` is unreachable under this
  environment's network policy, so both findings are proved against the module's own injected
  `transport` seam — which is where the defect lives: the module never checks the response,
  whoever produces it. Whether the live API ever returns an order whose amounts differ from the
  create request is still the open question README:108-116 puts to the first person who can
  reach it.
- **CI's other Python legs.** Only 3.11.17 was run. 3.9, 3.10, 3.12 and 3.13 are unproven from
  here; `from __future__ import annotations` at the top of every module using `X | None` means
  the 3.9 leg should be fine, but it was not executed.
- **Three third-party repositories the docs cite** (`michardnicolas/feeless402`,
  `0xgasless/agentkit`, `Jc-asastu/payclaw`) return 403 through this session's GitHub proxy —
  not in this session's repository scope — so a real 404 cannot be told from a policy block.
  Not reported as dead links in either direction.
- **The receive side.** `grep -rn "verify_receipt\|block_info" src/` finds nothing, so the
  "get paid in XNO" direction remains documentation only. Noted, not a defect in what ships.
