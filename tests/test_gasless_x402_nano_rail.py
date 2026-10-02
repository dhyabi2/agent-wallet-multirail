"""Tests for the 0xGasless AgentKit -> feeless Nano settle rail example."""

from examples.gasless_x402_nano_rail import (
    gasless_compare,
    gasless_pay_usdc,
    gasless_pay_xno,
    gasless_quote_nano,
    gasless_quote_usdc,
)


def test_gasless_nano_is_feeless():
    """The Nano settle option should always carry fee = 0."""
    q = gasless_quote_nano(1.0)
    assert q["fee_usd"] == 0.0
    assert q["scheme"] == "exact"
    assert q["network"] == "nano:mainnet"
    assert q["asset"] == "XNO"
    assert q["finality_s"] <= 2.0


def test_gasless_usdc_charges_a_fee():
    """The USDC settle option should charge > 0 fee (fee + network gas)."""
    q = gasless_quote_usdc(1.0)
    assert q["fee_usd"] > 0.0
    assert q["network"] == "avalanche-fuji"
    assert q["asset"] == "USDC"


def test_gasless_pay_xno_confirmed():
    """A stub confirming the block should settle True with that block as tx_ref."""
    out = gasless_pay_xno(gasless_quote_nano(1.0),
                          nano_rpc=lambda req: {"block": "B01", "confirmed": "true"})
    assert out["settled"] is True
    assert out["tx_ref"] == "B01"
    assert out["fee_usd"] == 0.0


def test_gasless_pay_xno_fails_closed():
    """An error / unconfirmed block must report settled=False, never a fake pass."""
    out = gasless_pay_xno(gasless_quote_nano(1.0),
                          nano_rpc=lambda req: {"error": "Block is invalid"})
    assert out["settled"] is False
    assert "error" in out


def test_gasless_pay_xno_not_confirmed_is_false():
    """A block hash without a confirmation must not count as settled."""
    out = gasless_pay_xno(gasless_quote_nano(1.0),
                          nano_rpc=lambda req: {"block": "B02"})
    assert out["settled"] is False


def test_gasless_compare_shows_savings():
    """Settling the same call in XNO should show a real fee saving over USDC."""
    c = gasless_compare(1.0)
    assert c["savings_usd"] > 0.0
    assert c["usdc"]["fee_usd"] > 0.0
    assert c["xno"]["fee_usd"] == 0.0


def _run_example(*args):
    """Run an example the way the README's `Run it` block tells a reader to."""
    import os
    import subprocess as sp
    import sys as _sys

    # Same reason as test_rails.test_example_emits_stable_marker: the
    # subprocess inherits no sys.path from pytest, so a fresh clone needs src
    # on PYTHONPATH or the test would only pass where the package is installed.
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.abspath("src") + os.pathsep + env.get("PYTHONPATH", "")
    return sp.run([_sys.executable, *args], capture_output=True, text=True, cwd=".", env=env)


def test_the_example_the_readme_publishes_prints_the_xno_settle_rail():
    """`python3 examples/gasless_x402_nano_rail.py` must show the XNO rail.

    The README lists this file as one of four runnable commands. It defined its
    functions and nothing else, so it exited 0 having printed nothing at all:
    the one command that demonstrates the Nano settle rail to the SDK the
    example is addressed at produced no output to read.
    """
    out = _run_example("examples/gasless_x402_nano_rail.py")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip(), "the example printed nothing"
    assert "QUOTE:nano-xno" in out.stdout
    assert "SETTLED:TRUE" in out.stdout
    assert "ON:nano:mainnet" in out.stdout
    # The point the example exists to make: XNO settles the same call feeless.
    assert "xno_fee=0.0 " in out.stdout


def test_every_example_the_readme_publishes_prints_something():
    """Each command in the README's `Run it` block must produce output.

    A published example that runs and says nothing is indistinguishable from a
    broken install to the reader following the README.
    """
    published = [
        ("examples/pay_on_any_rail.py",),
        ("examples/pay_on_any_rail.py", "usdc-evm"),
        ("examples/payclaw_nano_rail.py",),
        ("examples/gasless_x402_nano_rail.py",),
    ]
    silent = []
    for args in published:
        out = _run_example(*args)
        assert out.returncode == 0, "%s: %s" % (" ".join(args), out.stderr)
        if not out.stdout.strip():
            silent.append(" ".join(args))
    assert not silent, "published but prints nothing: %s" % ", ".join(silent)
