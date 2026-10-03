# agent-wallet-multirail — code audit, 2026-10-02

Clone of `master` at `bcacb1f`. Baseline in a fresh venv, before any change:

```
$ pip install -e ".[dev]"   # succeeds
$ python -m pytest -q       # 89 passed
```

This run read the Nano leg end to end — `NanoRail`, the mandate seam it calls, and the
four examples the README publishes as commands — and then **ran every one of those
commands**, which is where the finding is. The USDC, Skyfire, Payman and Nevermined legs
were read only far enough to confirm nothing on the Nano path depends on them; they are
out of scope and untouched.

## Found and fixed

**A command the README publishes ran and printed nothing.** `README.md:57` lists, in the
`Run it` block a new reader works through:

```
python3 examples/gasless_x402_nano_rail.py   # 0xGasless-shaped: XNO settle rail for the x402 pay path
```

`examples/gasless_x402_nano_rail.py` defines `gasless_quote_nano`, `gasless_quote_usdc`,
`gasless_pay_xno`, `gasless_pay_usdc` and `gasless_compare` — and has no
`if __name__ == "__main__":` block. Run exactly as published:

```
$ python3 examples/gasless_x402_nano_rail.py
$ echo $?
0
```

Exit 0, no output, nothing to read. The three other examples in that block all print
(`pay_on_any_rail.py` → 44 lines, `payclaw_nano_rail.py` → 22, and `hyperspace_nano_rail.py`,
which is not in the block, → 3). This file was the only one of the five without an entry
point, so the one published command whose whole job is to demonstrate the **XNO settle
rail** to the SDK it is addressed at (0xGasless AgentKit, issue #38 — the audience named in
`README.md:149`) showed that reader nothing. To them it is indistinguishable from a broken
install, and `README.md:151` bills the exact numbers it was supposed to print: "$1.00 call
settles USDC at ~$0.06 in ~3s versus XNO at ~$0.00 in ~0.3s".

**Fixed** by giving it the entry point its siblings have, in the same shape as
`hyperspace_nano_rail.py:136-142`, calling only functions that already existed:

```
$ python3 examples/gasless_x402_nano_rail.py
QUOTE:nano-xno SCHEME:exact FEE:0.0 FINALITY:0.3s
SETTLED:TRUE ON:nano:mainnet REF:sim-xno-1790966970
COMPARE usdc_fee=0.06 xno_fee=0.0 savings=0.06
```

No payment logic changed: the quote, the pay and the comparison are the existing
functions, called with the existing offline stub.

### Failing then passing

```
# baseline on master
python -m pytest -q   ->  89 passed

# with the 2 new tests, fix reverted
FAILED tests/test_gasless_x402_nano_rail.py::test_the_example_the_readme_publishes_prints_the_xno_settle_rail
FAILED tests/test_gasless_x402_nano_rail.py::test_every_example_the_readme_publishes_prints_something
                      ->  2 failed, 6 passed

# with the fix
python -m pytest -q   ->  91 passed
```

The second test runs **all four** commands the README's `Run it` block publishes and fails
on any that exits 0 with empty stdout, so the next silent example is caught by the suite
rather than by a reader. Both follow the subprocess pattern already in
`tests/test_rails.py:111-137`, including putting `src` on `PYTHONPATH` so they pass from a
fresh clone.

## Checked, nothing to fix

- **`NanoRail.pay_to` is the Nano send path, and it fails closed correctly.**
  `rails.py:140-158`: `parse_raw` refuses a float, a bool, a non-ASCII digit string and a
  leading-zero string; `normalise_address` checksum-verifies the payee *even when no
  mandate is set*, so a payee that fails its checksum never reaches the rpc. Every error
  out of either is a `MandateRefused`, which `pay_to` catches and returns as
  `settled=False` with `meta["refusal"]` — driven directly: a float amount, `"0123"`,
  `"١"` (Arabic-Indic one), a payee one character short and a payee with a corrupted
  checksum all came back refused, with the rpc never called.
- **No float touches a raw amount.** `pay_to` carries `amount_raw` as an `int` and renders
  it with `str(amount)`; `Quote.amount_usd`/`Settlement.amount_usd` are floats but are
  *dollar* display figures for the rail comparison, never an XNO amount. `pay()` in USD is
  refused outright when a mandate is set (`rails.py:120-131`), with the right reason: a raw
  integer cap cannot be enforced against a float dollar amount.
- **`_settlement` (`rails.py:160-187`) does not read a missing confirmation as a payment.**
  An rpc reply carrying `error`, an empty `block`, or no `confirmed` all give
  `settled=False` with a reason in `meta["error"]`; `confirmed` is accepted both as the
  string `"true"` a node sends and as a JSON bool.
- **`mandate.py` was read but deliberately not touched.** It is vendored byte-for-byte into
  `nano-wallet-xno` and `openai-agents-nano-x402` and a test pins its bytes, so a change
  here alone would split the enforcement logic across three repositories. `spend`
  (`mandate.py:617-641`) reserves in the ledger *before* calling `send` and marks the entry
  `"unknown"` if `send` raises — correct: a cap that forgets a payment whose outcome is
  unknown can be overrun.
- All five examples and the full suite run from a clean clone with no network.

## Not verified here

No live XNO payment: this repository ships no seed and its rpc seam is a stub by design
(`README.md:155-165` says so plainly). The live proof lives in `openai-agents-nano-x402`.
The claim in `README.md:151` that a real 0xGasless USDC call costs ~$0.06 was not
re-measured against Avalanche gas; it is the repository's own illustrative figure and the
example now prints it rather than contradicting it.

## Secrets

Clean. No credential, key or seed in the tree. `scope-manifest.json`, `docs/` and the
examples carry Nano public addresses and simulated block references only.
