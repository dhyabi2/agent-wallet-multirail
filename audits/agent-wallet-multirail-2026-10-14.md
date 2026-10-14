# agent-wallet-multirail — audit 2026-10-14

The Nano leg only: the USDC, Skyfire, Payman and Nevermined rails were read only where
the Nano path passes through them, and nothing on them was changed or "improved". The
USDC->XNO swap is in scope as the bridge into XNO.

**No code was changed. This is not a clean pass: three findings are open for the owner.**
`create_order` sends no `fromNetwork`/`toNetwork` (`swap.py:640-644`); the mandate ledger
reads a `{}` or `""` `payments` as no payments and truncates a float `amount_raw`
(`mandate.py:702-707`); and `NanoRail.pay()` without a mandate sends a float
`amount_usd` (`rails.py:123`). Details below.

## What I checked

- `src/agent_wallet_multirail/rails.py`: `NanoRail.quote`, `pay`, `pay_to` and
  `_settlement` — every path by which a settlement is reported settled or refused.
- `src/agent_wallet_multirail/mandate.py` (995 lines), the money-decision core:
  `parse_raw`, `xno_to_raw`, `raw_to_xno`, `public_key_from_address`,
  `normalise_address`, `validate_fields`, `verify_signed`, `verify`/`sign`,
  `check_revocation`, `verify_revocation`, and `MandateGuard._read` / `_check` /
  `check` / `spend` / `status`.
- `src/agent_wallet_multirail/swap.py` (907 lines): `usdc_to_micro`,
  `_canonical_nano_network`, `NanoQuote.__post_init__` / `from_x402_entry`,
  `_required_with_headroom`, `plan_swap_hop`, `NanswapProvider.estimate` / `limits` /
  `create_order` / `_order_from`, and `pay_nano_quote_from_usdc`'s retry and
  send-already-attempted paths.
- **The README quickstart, run as written** from a clean directory, not read: `mandate
  keygen`, `create`, `verify`, `status`, `check`, `revoke`, then `check` again. All six
  commands succeed and the revocation takes effect:
  `{"ok": false, "reason": "revoked", "message": "the operator revoked this mandate at
  2026-10-14T12:45:53Z: task cancelled"}`.
- **All six shipped examples, run**: `crossmint_nano_adapter`,
  `gasless_x402_nano_rail`, `hyperspace_nano_rail`, `pay_nano_quote_from_usdc`,
  `pay_on_any_rail`, `payclaw_nano_rail`. Every one exits 0 after `pip install -e .`.
- The suite: **199 passed** (`python3 -m pytest -q`), before and after — nothing was
  touched.

## What I probed

- **Amounts.** Once a mandate is set, no float reaches an amount on the Nano path. Without
  one it does: `NanoRail.pay()` sends `{"action": "send", "amount_usd": quote.amount_usd}`
  to the rpc (`rails.py:123`), a dollar float (open finding, below). `parse_raw` refuses
  `bool`, `float`, a leading zero, a non-ASCII digit, a non-positive value and anything
  over `2**128-1`; `xno_to_raw` refuses an empty string (so `""` cannot partition to
  `0`), more than 30 decimals and non-ASCII digits; `_required_with_headroom` computes
  `ceil(amount * (10000 + bps) / 10000)` in integers and refuses a result over the
  128-bit ceiling. `NanoRail.pay()` in USD is refused outright once a mandate is set,
  because a raw cap cannot be checked against a dollar float.
- **The allow-list is compared on public keys, not strings** (`_check`, `mandate.py:737`:
  `payee_pk not in view["payee_keys"]`, with `payee_pk = public_key_from_address(payee)`), so the `nano_` and `xrb_`
  spellings of one allowed payee both pass — the failure mode its siblings had.
- **The signature check is strict.** `verify` rejects a signature or key of the wrong
  length, a point that is not on the curve, and `s >= L`; the signed message is a domain
  tag plus the mandate hash, so a mandate signature cannot double as a Nano block
  signature, and the revocation has its own domain.
- **The ledger mostly fails closed, but not fully.** A total that does not add up, a
  ledger belonging to another mandate, an unreadable file and a non-digit `spent_raw` are
  each a refusal, and a send that raises stays counted as spent (`status: "unknown"`).
  A non-list `payments` is *not* reliably refused: `MandateGuard._read`
  (`mandate.py:697-714`) refuses only when iterating `payments` raises, so `{}` and `""`
  read as no payments (open finding, below). `load_signed` reads the mandate with
  `parse_float=_refuse_float`, but the ledger is read with plain `json.load`
  (`mandate.py:702`), so a float there is truncated, not refused.
- **The swap hop refuses the shortcut it exists to refuse**: a swap pointed straight at
  the seller's `payTo`, an estimate for the wrong output currency, an estimate below the
  quote plus headroom, an order that comes back paying out elsewhere, asking for more
  input than the cap, or committing to less output than the quote needs. The send leg is
  recorded before it is made, so a retry after a send is refused
  (`send_already_attempted`) rather than paying the seller twice — and that check now
  runs before the arrival check, which is the right order.

## Found, NOT fixed — for the owner

**The swap order is created without the network the estimate and the limits were
checked on.** `NanswapProvider.estimate` and `limits` both send `fromNetwork` and
`toNetwork` (`swap.py:599-605`, `:618-621`). `create_order` — the leg that spends —
sends only `from`, `to`, `amount`, `fromAddress`, `toAddress` (`swap.py:640-644`). The
plan carries `from_network` and it is not used in that body.

USDC exists on many chains. The estimate and the provider's minimum/maximum are
obtained for USDC on a named network (the shipped example's path is a cross-chain
"partner" route), and the order that is actually funded does not name one, so the
pay-in address the provider returns is for whatever network it defaults to. An agent
that funds it on the planned chain has sent USDC to an address on another.

The code is a faithful copy of its stated source, which is where this gets interesting.
I fetched the published client (`npm pack nanswap@1.0.3`) and read it:

```
package/index.js:174
  function createOrderPartner(apiKey, from, to, amount, fromAddress, toAddress) {
    ... body: { from, to, amount, fromAddress, toAddress }     # no networks

package/README.md:130
  ### `createOrderPartner(from, fromNetwork, to, toNetwork, amount, toAddress)`
  nanswap.createOrderPartner('USDT', 'BSC', 'XNO', '', 10, 'nano_3rks...');
```

The client's own README documents the two network parameters; its implementation drops
them. `swap.py`'s comment says the body keys were "read off its source, not guessed",
and they were — the source is the half that is wrong.

**Why I did not patch it.** The fix is to add `fromNetwork`/`toNetwork` to a POST on the
send path, and I cannot test it: no API key, and this container's proxy denies egress to
`api.nanswap.com`. If the endpoint rejects unknown body keys, adding them breaks the
spend leg outright; if it ignores them, the hop is still created on a default network and
the real fix is different. Either way it changes an outgoing spend-path request on the
strength of a README rather than a response, which is a decision about what this hop
does, not a correction. It needs one live call with a key to settle, and then it is a
two-line change.

Until then the exposure is bounded by `max_from_amount`, which the module already calls
"the only bound a swap hop has" — the loss is capped at one planned swap's input, not
the wallet.

**The ledger accepts a malformed `payments` and a float amount.** (MEDIUM.)
`MandateGuard._read` (`mandate.py:697-714`) checks
`sum(int(p["amount_raw"]) for p in data["payments"]) != spent` and refuses only if that
raises or does not match. A ledger with `"spent_raw": "0", "payments": {}` or
`"payments": ""` sums to 0 and is accepted, so `check()` and `status()` report it as a
healthy ledger with nothing spent; `spend()` then fails on `.append` with an
`AttributeError` rather than a `MandateRefused`. Because the ledger is read with plain
`json.load` (`mandate.py:702`), an entry `"amount_raw": 1.9` with `"spent_raw": "1"` is
also accepted: `int(1.9)` is `1`. Both were confirmed by calling `_read` on such files.
The fix is to require `payments` to be a list and each `amount_raw` to be a digit string
(or to read the ledger with `parse_float=_refuse_float`), refusing anything else as
`ledger_corrupt`.

**`NanoRail.pay()` without a mandate sends a float.** (MEDIUM.) The fail-closed refusal
in `pay()` applies only when a guard is set (`rails.py:113`). Otherwise it calls the rpc
with `{"action": "send", "amount_usd": quote.amount_usd}` (`rails.py:123`), a dollar
float, so the integer-raw guarantees above hold only on the `pay_to` path and on the
mandated path. A real rail behind this would have to convert a float to raw itself.

## Could not verify

- No live network call on any rail. The Nano rails are simulated against the injected
  `rpc` stub by design; `api.nanswap.com` is denied from this container, so every
  provider reply exercised is the shipped transport stub.
- The USDC, Skyfire, Payman and Nevermined legs were not audited — out of scope for
  this pass, and deliberately left alone.
