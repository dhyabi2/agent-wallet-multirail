# agent-wallet-multirail — audit 2026-10-13

The **Nano leg only**, as Tier 0 requires. The USDC, Skyfire, Payman and
Nevermined rails were read only where the XNO path runs through them, and
nothing on them was changed or extended. Previous audit 2026-10-11 (at
`7f7f2a7`); audited here at `e0590a0` (`master` after #11).

Lens: can an agent pay, or get paid, in XNO with this code today without being
hurt — paying the wrong amount, paying twice, paying somebody else, being told
it paid when it did not, or being unable to get started.

Suite from a clean checkout: **197 passed** (`python3.13 -m pytest -q`); 199
with the law added below. Note the environment detail the 10-11 audit recorded
is unchanged and is not a repository defect: `/usr/local/bin/python3` here is
3.11 while pytest is installed under 3.13, so plain `python3 -m pytest` reports
"No module named pytest". `python3.13 -m pytest` is the one that runs.

## Found and fixed

- **The README's first runnable command could not run.** (LOW-MEDIUM, the first
  step a new agent takes)
  `README.md:86`, in the swap-hop section, opened with

      python3 examples/pay_nano_quote_from_usdc.py          # the whole hop, offline

  That is the **first** runnable command in the document, and the first
  `pip install -e .` is at line 131, in "Run it", 45 lines below it. This is a
  `src/` layout, so three of the six shipped examples — the three that import
  `agent_wallet_multirail` — cannot start from a fresh clone with no install.
  Measured this run, from the clone as it stands:

      examples/pay_nano_quote_from_usdc.py   ModuleNotFoundError: No module named 'agent_wallet_multirail'
      examples/pay_on_any_rail.py            ModuleNotFoundError
      examples/payclaw_nano_rail.py          ModuleNotFoundError

  A reader working top-down — which is what an agent told to "follow the
  README" does — got that traceback as its first contact with the repository.
  The install line is now named in that block too, and the `refuse` variant on
  the next line is marked as exiting 1 by design, because it demonstrates a
  refusal and an agent seeing a non-zero exit would otherwise read it as a
  crash.

  **The law**, `tests/test_readme_runnable_order.py`: for every
  `python3 examples/<name>.py` the README shows, if that example imports the
  package then a `pip install` must appear earlier in the file. It reads the
  examples' own imports rather than a list, so an example rewritten to be
  self-contained, or a new one that is not, is covered without editing the
  test. A parser guard fails if the command shape stops matching, and also
  asserts every example the README names exists on disk. Against the README as
  on `master` the law fails at line 86; with the fix it passes.

## Checked and found correct — no change made

Three things that looked like defects and are not. Recording them so a later
run does not re-open them:

- **Both examples the 10-11 audit reported green really are green.** All six
  exit 0 once the package is importable (`PYTHONPATH=src`), including
  `pay_on_any_rail.py usdc-evm`. #11 broke nothing. The three
  `ModuleNotFoundError`s above are the missing install, not a regression.
- **`MandateGuard._check` cannot be fooled by an address prefix**
  (`mandate.py:733`). It compares `public_key_from_address(payee)` — the
  decoded 32-byte key, checksum-verified — against `view["payee_keys"]`, so
  `xrb_X` and `nano_X` are one payee on the allow-list and neither spelling can
  slip past it or be wrongly refused. `NanoRail.pay_to` passing the raw string
  to the guard and the normalised one to the rpc is therefore safe; both reduce
  to the same key.
- **`NanoRail._settlement`'s `block = str(resp.get("block") or "")`
  (`rails.py:150`) accepts a non-string `block`**, so a reply like
  `{"block": {"x": 1}, "confirmed": True}` would report `settled=True` with
  `tx_ref="{'x': 1}"` — a reference nobody can look up on the ledger. **Left
  alone deliberately.** The rpc here is the operator's own documented seam, not
  anything a payer or a merchant reaches, and a real node answers `send` with a
  64-hex hash or an `error`. More to the point, tightening it is not free: the
  repository's own tests settle on the stub values `"block-abc"` and `"B2EC"`
  (`tests/test_rails.py:97,168`), which are deliberately short because this
  rail is specified to run offline against stubs, so a hash-shaped check would
  mean rewriting the repo's fixtures — a redesign, not a fix. Refusing merely a
  non-*string* block would be safe but buys nothing a real node can produce.
  If a real integration ever lands behind this seam, that is the moment to
  check the block's shape, and the amount and destination with it.

## What I checked, end to end

- **`rails.py`, the whole Nano leg:** `NanoRail.quote`; `pay`'s fail-closed
  refusal to `mandate_requires_raw` whenever a guard is set, because a float
  dollar amount cannot be checked against a raw-integer cap; `pay_to`'s
  `parse_raw` → `normalise_address` → guard-or-rpc order; and `_settlement`'s
  fail-closed read — an `error` key, an empty block, or a `confirmed` that is
  neither `True` nor the string `"true"` all give `settled=False` with a
  reason in `meta["error"]`. `confirmed: 1` does not settle.
- **`mandate.py`'s money arithmetic and guard order:** `parse_raw` (floats,
  bools, non-ASCII digits, leading zeros and anything outside `1..2**128-1`
  refused), `xno_to_raw`'s exact integer placement, `public_key_from_address`'s
  length/alphabet/checksum checks, `_check`'s three refusals, and `spend`'s
  reserve-before-send: the ledger entry and the cap debit are written and
  `_write` is `fsync`-ed under an `flock` *before* `send()` is called, and a
  `send()` that raises leaves the entry `status: "unknown"` rather than
  releasing the reservation — a cap cannot be overrun by a crash.
- **The README's refusal table against the code**, name by name. All eight
  (`estimate_below_quote`, `exceeds_cap`, `no_order_log`,
  `order_destination_changed`, `provider_amount_not_a_string`,
  `provider_response_unrecognised`, `swap_destination_is_payee`,
  `swap_not_received_yet`) are emitted by `master`'s `src/`. No README claim
  outruns the code.
- **No float on any amount** on this leg: every XNO figure is an integer of raw
  or a digit string. `amount_usd` is a float by design on the USD-denominated
  comparison interface, which is exactly why `pay()` refuses under a mandate.

## Not touched, on purpose

- **`swap.py` beyond reading it.** Open pull request **#12** rewrites the
  order-against-plan checks across 849 lines of it, and a change of mine there
  would conflict with work already in review. #12 is also not merged by this
  run: its first bullet relaxes the created order's bar from quote + slippage
  headroom to the quote inclusive, which **widens** what is accepted on a money
  path, so it falls outside the "only adds a refusal" rule even though the rest
  of it narrows. It is listed for the owner instead.
- **The USDC, Skyfire, Payman and Nevermined rails.** Read where the XNO path
  crosses them; not extended, not "improved".

## Could not verify

- **No live payment and no live swap.** No XNO and no USDC moved; every case is
  measured against the module's own transport seam and stubs. The Nanswap
  endpoints were not called.
