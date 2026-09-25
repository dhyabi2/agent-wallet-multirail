# agent-wallet-multirail — audit 2026-09-25

First audit of this repository. Reviewed at commit `a9cff09`.

## What was checked

- `src/agent_wallet_multirail/rails.py` in full: the `PaymentRail` contract, all four rails,
  the registry, `rail_for` and `settle`.
- The `rpc` seam on `NanoRail` — the one place the README tells an SDK integrator to wire a
  real Nano RPC — against the replies a real node actually sends.
- `tests/test_rails.py`: whether each test asserts what its name says, and whether the suite
  passes from a bare clone as the README says it does.
- `examples/pay_on_any_rail.py` in both modes, and the machine-readable markers a first
  contact cites.
- Every factual claim in the README and in the package docstring against the code.
- Python floor: `requires-python = ">=3.9"`. The `X | None` annotation in `NanoRail.__init__`
  is safe there because the module carries `from __future__ import annotations`.
- Build: `pip install -e .`, then import and run.
- Dependencies: none beyond the standard library (`pytest` only as a dev extra) — nothing to
  advise on.
- Secrets: the working tree (12 files) and every distinct blob version across the full
  history (29 revisions, 60 blob versions). Clean. `.ledger/ledger.json` carries no
  credential.
- Input reaching a shell or a file path: none. `examples/pay_on_any_rail.py` takes one argv
  value and checks it against a fixed list before use; the test subprocess passes a literal
  argument list, never a shell string.

## What was found

**1. The Nano rail reported a settled payment when the node had reported an error.**
`rails.py:106` read `settled=bool(resp.get("confirmed", True))` — the default was `True`, so
a reply with no confirmation at all counted as one. Measured against the seam as shipped:

| the rpc answered | `pay()` returned |
| --- | --- |
| `{"error": "Fork"}` | `Settlement(settled=True, tx_ref='')` |
| `{}` | `Settlement(settled=True, tx_ref='')` |

That is a payment adapter failing open, in exactly the place a wallet SDK is invited to
point at a live Nano node — and a node answers an error or a not-yet-confirmed far more
often than it answers a confirmation. A settled receipt with an empty `tx_ref` is also
self-contradicting: there is nothing to show a payer or an auditor.

Fixed on branch `fix/nano-rail-fail-closed`: a settlement now requires no `error` key, a
non-empty block reference, and an explicit confirmation — `True` or the string `"true"`, the
latter because that is what a Nano node sends. A reply that is not a mapping is refused
rather than raising `AttributeError`. When it does not settle, `meta["error"]` says why, so a
caller is not left guessing at a bare `False`. 5 new tests; 4 of them fail against the code
as it was and the fifth pins the string-`"true"` case, which passed only by accident of
`bool("true")`.

**2. The README's test command fails from a bare clone, and the CI it claims does not
exist.** The README says *"Tests (10, all passing on CI and locally): `pip install pytest &&
python -m pytest -q`"*. Following that literally in a fresh clone:

```
FAILED tests/test_rails.py::test_example_emits_stable_marker
  ModuleNotFoundError: No module named 'agent_wallet_multirail'
1 failed, 9 passed
```

The test module puts `src` on `sys.path` for itself, but `test_example_emits_stable_marker`
spawns the example in a subprocess that inherits no such path. And there is no
`.github/workflows` in this repository at all, so "all passing on CI" describes nothing.
This is the first thing a maintainer being asked to adopt the pattern would run.

Fixed on branch `fix/tests-run-from-a-clone`, kept separate because it is a different
concern.

## What could not be verified

- **No live Nano network.** This sandbox's network policy denies public Nano RPC hosts (403
  on CONNECT), so the fail-closed behaviour is proved against replies shaped like a real
  node's, not against one. The shapes used (`{"error": ...}`, `confirmed` as the string
  `"true"`) match this account's own `nano-mcp-public` normalizer, which was verified against
  two independent public endpoints.
- The README's claims about **other people's rails** — Skyfire's fee, Payman's fee, EVM gas
  at $0.05 — are modelled numbers, not measured ones. The code presents them as defaults a
  caller can override, which is honest, but nothing here checks them against those
  providers' published pricing. Out of scope for a fix; worth a look before the numbers are
  quoted at a maintainer.
- That no downstream caller depends on `pay()` returning `settled=True` for an
  unconfirmed reply. Nothing in this account's repositories imports the package, and it is
  at `0.1.0`.
