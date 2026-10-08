# agent-wallet-multirail — audit 2026-10-08

Lens: can an agent pay, or get paid, in XNO with this today without being hurt? Tier 0 lists this
repository as **the Nano leg only** — the USDC, Skyfire, Payman and Nevermined legs are read to
understand the Nano path and are never extended.

Baseline on `master` (`40527bb`): `python3 -m pytest -q` → **180 passed**. After this branch:
**182 passed**. `python3 -m compileall src tests examples` clean both ways. All six `examples/`
scripts exit 0 (`pay_nano_quote_from_usdc.py refuse` exits 1 by design, `examples/…:94`).

Five prior audits read `swap.py`, `rails.py` and `mandate.py` line by line. This run went at the
part no audit had read: **the `examples/` files and the `docs/` page, which are what a maintainer of
another SDK is told to copy.** Nothing in `src/` changes here.

## Found and fixed — the published seam asks for the wrong amount

**1. The settle seam put a USD float in a field named `amount_raw`.**
`examples/gasless_x402_nano_rail.py:71` and `examples/hyperspace_nano_rail.py:77`, the same line:

```python
resp = rpc({"action": "send", "amount_raw": quote.get("amount_usd")})
```

Both docstrings say `nano_rpc` is "the one seam a real SDK wires up — point it at a real Nano RPC to
settle a real, feeless, sub-second XNO transfer". Measured, spying on that seam:

```
gasless_pay_xno  -> {'action': 'send', 'amount_raw': 1.0}
   amount_raw type=float value=1.0   as XNO = 9.999999999999999e-31
```

**1.0 "raw" is 10⁻³⁰ XNO, not $1.00 of XNO**, and the request carries no destination. `README.md`'s
"`float` is refused everywhere, in both directions" says the opposite. The in-package rail is
correct and was the model: `rails.py:123`'s `pay()` sends `amount_usd`, and the raw-denominated send
is `NanoRail.pay_to` (`rails.py:138-139`), which carries a destination and `str(int)` raw. So the
fix is to name the field for what it carries — `amount_usd` — not to invent a conversion the example
never had.

**2. The `accepts[]` entry in the round-trip doc asked a payer for 100× the price it named.**
`examples/crossmint_nano_adapter.py:107` published

```
"amount": "5000000000000000000000000000000",  # raw XNO for $0.05
```

which is **5 XNO**. Nothing in the file computes it, so no test could see it drift, and a maintainer
copying the entry would challenge a payer for a hundred times a $0.05 purchase. It is now
`50000000000000000000000000000` with the rate stated beside it, and a test derives the figure from
the price the file itself quotes.

**3. The round trip presented a stub that verifies nothing as the gate that fulfils the order.**
`crossmint_verify_receipt` (`examples/crossmint_nano_adapter.py:76-96`) takes `pay_to` and
`amount_raw` and **reads neither**; it answers `block_hash.strip().lower().endswith("dead")` — from
the hash, which is the payer's to choose. Its own docstring is honest that it is a stub. Step 5 of
`_NANO_ROUNDTRIP` was not: it said "Crossmint-side handler verifies the receipt:
`verify_receipt(block_hash, pay_to, amount_raw) => bool`" and step 6 "If verified, the
checkout/fulfilment flow proceeds unchanged". A maintainer reading the round trip, which is what the
file is for, is told that call is the gate. **Fulfilling on it fulfils for free.** Step 5 now says
what a real gate reads and that this helper is not one. There is no receive-side verifier anywhere in
`src/` (`grep -rn "verify_receipt\|block_info" src` → nothing), so this stub is the whole of the
"get paid in XNO" direction in the repository.

**4. And a green test asserted the forgery was a verification.**
`tests/test_crossmint_nano_adapter.py` had

```python
def test_crossmint_nano_verify_valid_hash():
    """Verify a receipt for a hash that ends in 'dead' returns True."""
    assert crossmint_verify_receipt("block_hash_dead", "nano_xxx", 100) is True
```

`block_hash_dead` is payer-chosen and `nano_xxx` is not a well-formed Nano address — the name and the
docstring read as the gate working. The behaviour is unchanged, deliberately: the stub documents the
seam. What is asserted is now **the hazard** — the same hash "verifies" against a payee it never paid
and against a thousand times the quoted amount — so the day someone wires it to a fulfilment flow the
test says why they must not.

**5. Three stale claims the code does not support.** `README.md:138` said "There is no CI on this
repository yet"; `.github/workflows/test.yml` landed in `e397e66`, **the commit before HEAD**, in the
same commit that wrote the sentence. `docs/building-agent-pays-x402-nano.md:65` said "Tests (10, all
passing)" against a suite of 180. The same page's Links pointed at
`github.com/PANDeveloper001/agent-wallet-multirail` — an account that no longer exists, while
`README.md:171` installs from `dhyabi2` — and offered "`openai-agents-nano-x402` on PyPI", which
answers 404 on `pypi.org/pypi/openai-agents-nano-x402/json` (as does `openai-agents-nano`, the name
its `pyproject.toml` actually declares).

### Failing, then passing

Two new tests, with `examples/` **alone** reverted to `master` and the tests kept:

```
FAILED tests/test_gasless_x402_nano_rail.py::test_the_settle_seam_does_not_put_a_usd_float_in_a_raw_field
  AssertionError: gasless_pay_xno sends 1.0 in a field named amount_raw; that is a USD amount,
  and 1.0 raw is 9.999999999999999e-31 XNO
  assert 'amount_raw' not in {'action': 'send', 'amount_raw': 1.0}
FAILED tests/test_crossmint_nano_adapter.py::test_the_published_accepts_entry_asks_for_the_price_it_names
2 failed, 180 passed
```

Restored: **182 passed**. The rewritten crossmint test asserts four properties of the stub rather
than one, so it cannot pass by accident if the stub is quietly changed.

## Found, NOT fixed, and the one that matters most — needs the owner

**The swap hop's arrival check is an account-wide balance delta, so XNO that is not the swap's
satisfies it.** `src/agent_wallet_multirail/swap.py:771-775`:

```python
after = _integer_balance(balance_raw, "after the swap")
received = after - before
if received < plan.quote.amount_raw:
    raise SwapRefused("swap_not_received_yet", ...)
```

`received` is the agent account's total balance delta between two reads. **Nothing ties it to
`order.order_id`.** So any XNO credited to that account in the interval — an unrelated payment *to*
the agent, or another hop's swap — passes the guard `README.md:96` says stops "sending before the XNO
has actually arrived", and the seller is paid out of that money while the USDC is gone to a provider
that never performed. `swap.py:759` tells the caller `balance_raw()` is "to read what the swap
actually delivered"; its signature is `Callable[[], int]` and it cannot. `NanswapProvider.order(order_id)`
exists at `swap.py:631-633` and returns the order with its `status`; the hop never calls it.

Measured, every seam injected, the provider never delivering:

```
balance before anything: 0 raw
call 1 refused: swap_not_received_yet
USDC spent on the swap order: 1200000 micro

the provider still says about ord-1: status='waiting'
an UNRELATED 2 XNO payment arrives for the agent (nothing to do with the swap)

call 2 SENT: True -> 1000000000000000000000000000000 raw to nano_11131a3ia3a81w61k4i...
received_raw the hop believed the swap delivered: 2000000000000000000000000000000

sends to the seller      : 1
XNO the swap delivered   : 0
XNO sent to the seller   : 1000000000000000000000000000000
```

1.20 USDC gone, **0 XNO delivered**, and 1 XNO of the agent's own unrelated income paid the seller.
Single-threaded; no race needed. The same shape lets two hops sharing an `order_log` cross-satisfy:
hop A's swap lands, hop B — whose provider never delivered — spends it, and A is then refused.

`tests/test_swap.py:527` (`test_the_received_amount_is_measured_as_a_delta_not_the_balance`) pins the
half of the guard that works: a *pre-existing* balance is not counted. The complementary case — a
*new* credit that is not this order's — has no test and is not refused.

**Why no fix is attempted here.** This is the money-send path, and every candidate changes more than
a refusal:
- *Ask the provider*: requires `provider.order()` on every provider (the suite's own fakes have none)
  and a judgement about which `status` strings mean "paid out" — guessing a provider's vocabulary is
  exactly what this module refuses to do elsewhere.
- *Attribute exclusively between keys*: fixable (give earlier un-sent keys first claim on a credit, so
  the later hop is refused) and genuinely refusal-only, but it introduces head-of-line blocking — one
  dead order starves every later hop under the same log.
- Neither closes the foreign-income case above, which is not attributable from inside the hop at all.

So the question is the owner's, in one sentence: **should the hop require a provider that can report
a per-order payout, and refuse to execute without one?** Everything else is a narrower patch over a
guard that is measuring the wrong thing.

## Read and found clean

- **The `decimal` precision hazard is not present.** `grep -rn "decimal"` finds no `decimal` import
  anywhere; `xno_to_raw` is `int(whole)*10**30 + int(frac.ljust(30,"0"))`. All amounts are integers.
- **No float on any amount in `src/`** — the only `float` left is `mandate._refuse_float`, the JSON
  hook that refuses one, plus USD *display* fields.
- **Secrets clean.** No key, seed, token or API-key value in the tree, `.ledger/ledger.json` included.
  `mandate keygen` writes `0o600` (verified `-rw-------`).
- **No shell and no path sink**: no `os.system`, `subprocess`, `shell=True`, `eval`, `exec` or
  `pickle` in `src/` or `examples/`; nothing a payer submits reaches an `open()`.
- `MandateGuard._check` compares the payee as a **public key**, so an `xrb_`/`nano_` spelling cannot
  make the guarded payee and the rpc's payee diverge.
- `#8`'s send-idempotency fix (`swap.py:790-806`) holds on re-reading: `recorded` is read before
  `order_log[key]` is set, so the first call cannot refuse itself.

## Could not verify

- **No live Nanswap and no live Nano node** — `api.nanswap.com` is denied by this environment's
  network policy. The swap finding is therefore proved against the module's own injected seams, which
  is where the defect lives.
- **`pip install "git+https://github.com/dhyabi2/agent-wallet-multirail"`** (`README.md:171`) was not
  run; `pip install -e .` and `pip install .` from the clone both work.
- **CI's older Python legs.** 3.11 → 182 passed; 3.13 was green on the pre-branch tree. The full
  matrix is unproven from here.
- Two further small things found and left alone as out of scope for this branch, recorded so the next
  run need not re-find them: `mandate sign FILE` never writes back to `FILE` (and `--out FILE` is
  refused `file_exists`), so `README.md:178-181`'s "completes it" flow does not complete; and
  `mandate sign` is the only subcommand whose `json.load`/`doc["mandate"]` sit outside `main`'s
  `except`, so a malformed file gives a traceback where every sibling gives clean refusal JSON. No
  money either way.
