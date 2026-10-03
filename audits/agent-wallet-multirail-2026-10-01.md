# agent-wallet-multirail — audit 2026-10-01

Second audit, of **the Nano leg only** (per Tier 0: never extend or review the USDC,
Skyfire, Payman, Nevermined or Crossmint legs). Reviewed at commit `c15448b`, which adds
`mandate.py` — the operator spend cap — since the 2026-09-25 audit. That file and the Nano
path through `rails.py` are the substance of this pass.

## What was checked

- `pip install -e . && python -m pytest -q` from a clean virtualenv: **89 passed**.
- `src/agent_wallet_multirail/mandate.py` (828 lines) line by line:
  - the ed25519-blake2b arithmetic, including `_decode_point`'s rejection of a `y >= q`
    encoding and of `x == 0` with the sign bit set, and `verify`'s `s >= L` check;
  - `public_key_from_address` — the `nano_`/`xrb_` prefix, the 60-character length, the
    `1`/`3` first character that bounds the value below 2**256, the alphabet, and the
    blake2b-40 checksum, all of which it actually checks;
  - `parse_raw` and `xno_to_raw` for floats: both refuse a `float` and a `bool` outright,
    `parse_raw` refuses a leading zero and bounds the value to 2**128-1, and `xno_to_raw`
    is `int(whole) * 10**30 + int(frac.ljust(30, "0"))` — exact integer arithmetic with no
    float anywhere on it;
  - `load_signed`'s `parse_float=_refuse_float`, so a non-integer number anywhere in a
    mandate file is refused rather than rounded;
  - `canonical_bytes` / `mandate_hash` / `signing_message` — sorted keys, no spaces,
    `ensure_ascii`, `allow_nan=False`, and a domain tag that keeps a mandate signature from
    doubling as a Nano block signature;
  - `validate_fields` — unknown fields refused rather than ignored, `per_payment_max_raw`
    bounded by `total_cap_raw`, operator and agent required to differ, both times parsed
    strictly, expiry after issue;
  - `verify_signed` — exact key set, hash recomputed from the content, signature checked
    against the operator's own public key, `not_yet_valid` and `expired`;
  - `MandateGuard._read` / `_check` / `spend` — the ledger's `mandate_hash` binding, the
    "totals do not add up" integrity check, the per-payment max, the payee allow-list, the
    remaining cap, the `flock`, and the atomic `mkstemp` + `fsync` + `os.replace` write.
- `rails.py`'s Nano leg only: `NanoRail.pay` (which fails closed with
  `mandate_requires_raw` rather than check a raw cap against a USD float), `pay_to`, and
  `_settlement`'s fail-closed reading of a node reply.
- Secrets: the working tree and every blob version across the full history (100 blob
  versions). Clean. The 64-hex strings in `tests/test_mandate.py` are the published RFC 8032
  Ed25519 vectors (`9d61b19d…`, `d75a9801…`) and the repository's own golden mandate hashes;
  the 189 in `.ledger/ledger.json` are hashes, not keys.

## What was found

Nothing worth changing on the Nano leg. Two things are worth recording because they look
like defects and are not:

- **`MandateGuard.spend` consumes the cap even when the rpc returns a reply that reports no
  confirmation.** The amount is reserved in the ledger *before* `send()` is called, and on a
  non-exception return it is marked `returned` and stays counted. For a spend cap that is
  the right direction — a cap that forgets a payment whose outcome it does not know can be
  overrun — and `spend`'s own docstring says so for the exception case. It does mean a
  caller that retries a failed rpc burns cap; that is the conservative trade, not a bug.
- **`pay_to` reports `amount_usd=0.0`** on the Nano path. That is a USD display field on a
  rail denominated in raw, not an amount anything is computed from: the raw amount goes out
  as `meta["amount_raw"]`, a string, and `parse_raw` has already refused anything that was
  not an exact integer.

## What could not be verified

- **The vendored-copy claim.** `mandate.py`'s module docstring says "This file is
  self-contained on purpose so the same bytes can be vendored into nano-wallet-xno and
  openai-agents-nano-x402; the golden vectors in each repo's tests pin that the copies
  agree." Only this repository's own golden vectors were run. Whether `nano-wallet-xno` and
  `openai-agents-nano-x402` currently carry a copy, and whether it is the same bytes, was
  not checked in this pass — it needs all three repositories read together, and a drift
  there would mean an operator mandate signed by one and refused by another. Worth its own
  pass; recorded here so it is not lost.
- **No live Nano node and no real wallet.** `NanoRail`'s `rpc` is a stub by design, so the
  whole Nano leg — including `MandateGuard.spend` wrapped around a real send — has never
  been exercised against a node. The signing arithmetic is pinned by the RFC 8032 vectors,
  so what is unverified is the seam, not the cryptography.
- **Concurrency.** `_Locked` uses a POSIX advisory `flock` and falls back to no lock at all
  on Windows (`_fcntl = None`). Two agent processes sharing one mandate ledger on Windows
  could therefore both pass the cap check. Not reachable from here to test, and not a defect
  on a POSIX host; noted for anyone who ships this on Windows.
