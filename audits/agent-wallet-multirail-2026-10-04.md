# agent-wallet-multirail — audit 2026-10-04

Lens: can an agent pay, or get paid, in XNO with this today without being hurt? Tier 0 lists this
repository as **the Nano leg only** — the USDC, Skyfire, Payman and Nevermined legs are read to
understand the Nano path and are never extended.

Baseline on `master` (`e397e66`): `python3 -m pytest -q` → **175 passed**. After this branch: **180
passed**. `python3 -m compileall src tests` clean both ways.

## Checked

- `swap.py` end to end — the newest Nano code in the repository (`#7`, "Pay an XNO quote from a
  wallet that holds only USDC"): amount parsing, the `nano:mainnet` canonicalisation, the
  provider-response refusals, `plan_swap_hop`'s eight guards, and `pay_nano_quote_from_usdc`'s
  three legs including the retry path.
- `rails.py` — `NanoRail.quote`, `pay`, `pay_to`, `_settlement`'s fail-closed confirmation read.
- `mandate.py` — the ed25519-blake2b sign/verify pair, address decode and checksum, `parse_raw`,
  `xno_to_raw`/`raw_to_xno`, `validate_fields`, `verify_signed`, the revocation path and
  `MandateGuard`'s reserve-then-send ledger.
- Every command the README prints. All six examples run offline; `pay_nano_quote_from_usdc.py
  refuse` exits 1 **by design** (`examples/pay_nano_quote_from_usdc.py:94`) to show the refusal.
- Secret scan of the tree: no key, seed, token or API-key **value**. `NANSWAP_API_KEY_HEADER` is a
  header name; `api_key` is a constructor parameter that is never defaulted or logged.
- Float scan on the money path: the only `float` left in `src/` is `mandate._refuse_float`, the
  JSON hook that refuses one. Amounts are integers or exact decimal strings throughout.

## Found and fixed — a retry paid the seller twice

`pay_nano_quote_from_usdc` (`swap.py:758-779` on `master`) made the **swap** leg idempotent and left
the **send** leg — the leg that pays the seller — with no record at all. The function's own docstring
tells a caller that retry *is* calling it again with the same `order_key`.

The hop is deliberately planned to **over-deliver** (`DEFAULT_SLIPPAGE_BPS = 100`, and nothing caps
how far above the quote an estimate may land). So after a successful send the agent's own account
still holds a surplus, and `received = after - before` on the retry reads that surplus as a swap
that has only just arrived. Measured on `master`:

```
call 1 refused: swap_not_received_yet
call 2 sent: 1000000000000000000000000000000 raw -> settled True
call 3 sent: 1000000000000000000000000000000 raw -> settled True

sends to the seller:  2
total raw sent:       2000000000000000000000000000000
the quote was:        1000000000000000000000000000000
swap orders bought:   1
```

**2 XNO out of the agent's account for a 1 XNO quote**, on one swap order, from the retry the
documentation asks for. Nothing downstream catches it: `MandateGuard.spend` records a `ref` but never
checks one for a duplicate, so the second send is counted against the cap rather than refused, and
`NanoRail.pay_to` has no idempotency of its own.

**The fix only adds a refusal.** The send is recorded in `order_log[key]["send_attempted"]` *before*
`rail.pay_to` is called — the same reserve-then-spend order `mandate.py`'s ledger already uses, for
the same reason it gives ("under-counting is how a cap gets overrun") — and any later call under that
key is refused `send_already_attempted`. No amount, destination, rounding or key path changes.

A send that **raised** is refused on retry too, and recorded `outcome: "unknown"`: the money may have
moved, and this is not the place to guess. The honest limit is stated in the code: a retry of the
*send* cannot be made safe here, because a balance that still covers the quote is exactly what a
completed hop looks like.

Four new tests fail on `master` and pass here; a fifth is a control that passes both ways, so the
refusal cannot cost a hop its one legitimate send. Mutating the guard to `if False and ...` fails
three of them, so it is live.

## Read and found clean

- `_settlement` (`rails.py:152`) fails closed on a missing or non-"true" `confirmed`, and names why.
- `parse_raw` refuses bool, float, non-ASCII digits, leading zeros, `<= 0` and `> 2**128-1`.
- `_required_with_headroom` ceils in integers and refuses a result above the 128-bit ceiling.
- `public_key_from_address` drops exactly the four padding bits (`rest[0] in "13"` keeps the 52-char
  body under 2**256) and verifies the blake2b-5 checksum before returning.
- `NanoQuote.from_x402_entry` refuses an entry carrying two **different** prices rather than picking
  one, and refuses a bare `nano`/`xno` network rather than assuming mainnet.
- `_exact_decimal` refuses a JSON number for an XNO amount, because `json.loads` has already made it
  a float by then.
- `NanswapProvider.create_order` re-checks the payout address the order came back with against the
  one it was created for.
- `MandateGuard.__init__` recovers the mandate path from the ledger path so the revocation file it
  reads is the one `mandate revoke` writes (the bug its own comment records).

## Could not verify

- No live Nanswap call: `api.nanswap.com` is denied by this environment's network policy, same as
  when the module was written. Every provider response in the tests is a literal, and the module
  refuses an unrecognised shape rather than guessing — which is what makes that acceptable.
- No live Nano node, so `NanoRail`'s `rpc` seam is exercised only against stubs. The confirmation
  read is checked both ways (bool `True` and the string `"true"`) against the documented RPC shape.
- History was not scanned commit by commit for secrets; the tree is clean and this clone is shallow
  (`--depth 50`).
