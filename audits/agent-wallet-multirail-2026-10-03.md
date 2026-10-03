# agent-wallet-multirail - audit 2026-10-03

Worked #4 (`feat/mandate-revocation`, open since 2026-09-30). Scope is the **Nano leg only**;
the USDC, Skyfire, Payman and Nevermined legs were not read and not touched. `mandate.py`
is Nano-specific throughout - Nano keys, `nano_` addresses, the `nano-operator-mandate/v1`
domain - so it is in scope.

## Checked

- `python -m pytest -q` on `master` (**91 passed**) and on the branch merged with `master`
  (**101 passed** as it arrived, **102** after the fix below). `git merge origin/master`
  into the branch applied cleanly.
- Whether the branch is a refusal and nothing else, since that is what decides if it may be
  merged from here. It is. `check_revocation` returns `None` when there is no revocation
  file, so with no revocation in play every path is byte-for-byte what it was. With one, the
  only outcomes are `MandateRefused("revoked")` once `revoked_at` has passed and
  `MandateRefused("invalid_revocation")` for a file that is unreadable, edited, signed by
  someone other than the operator, or names a different mandate - fail closed, a file that
  says stop is obeyed even when malformed. No amount, destination, rounding or key path is
  touched, and `spend`'s unknown-outcome accounting is unchanged.
- The two domains, which is what stops a mandate signature standing in for a revocation:
  `SIGN_DOMAIN = b"nano-operator-mandate/v1:"` against
  `REVOKE_SIGN_DOMAIN = b"nano-operator-mandate-revocation/v1:"`, and likewise for the hash
  domains. Separate, so neither signature verifies as the other.
- `verify_revocation` uses only public data: it recovers the signer from
  `rev["operator"]`, compares it against the mandate's operator, and verifies over
  `revocation_signing_message`. A revocation signed by the agent, or naming another
  mandate, is refused.

## Found and fixed - a revocation the guard never read

**`MandateGuard(signed, ledger_path)` looked for the revocation in the wrong place, so a
revoked mandate went on spending.** The constructor's default was
`ledger_path + ".revoked.json"`. For the standard layout `ledger_path` is
`<mandate>.ledger.json` (`default_ledger_path`), so the guard looked for
`<mandate>.ledger.json.revoked.json` - while `mandate revoke` writes, and the module
docstring promises, `<mandate>.revoked.json`.

Reproduced before changing anything, against a revocation written exactly as the CLI
writes it:

```
`mandate revoke` wrote: mandate.json.revoked.json

-- from_file
   refused at construction: revoked
-- MandateGuard(signed, default_ledger_path(mandate))
   looks for: mandate.json.ledger.json.revoked.json
   *** SPENT. calls to send(): 1
   *** the operator revoked a month ago and this guard never read the file
```

Nothing caught it because `from_file` passes the correct path explicitly and **every test in
`tests/test_mandate_revocation.py` names a `revocation_path`**, so the constructor's own
default was never exercised. This is the same shape as the defect run 125 recorded in
`nano-invoice`: green tests that each set up their own world cannot see a default that only
the real layout produces.

Fixed by recovering the mandate path from the ledger path when it carries the known suffix,
with `LEDGER_SUFFIX` named once so the two cannot drift again. A `ledger_path` that does not
end in `.ledger.json` keeps the previous fallback, so no existing caller changes.
`test_the_guard_reads_the_file_revoke_writes_without_being_told_where` revokes **after**
construction, so it tests the read that happens before every spend rather than only the one
at construction; it fails without the fix (`mandate.json.revoked.json` against
`mandate.json.ledger.json.revoked.json`) and passes with it.

## Could not verify

- No XNO moved and no node was reached; `spend`'s `send` callable is a fake throughout, which
  is what the laws intend.
- The vendored copies. `mandate.py` is said to be vendored byte-for-byte into
  `nano-wallet-xno` and `openai-agents-nano-x402`, and #4 says those copies follow once it
  merges. **They now have to carry this fix too**, or a guard built with the constructor in
  either of them keeps spending through a revocation. Not done here: it is a separate change
  in two other repositories.
- Whether anything outside this repository builds `MandateGuard` with the constructor rather
  than `from_file`. Inside it, only the tests do.
