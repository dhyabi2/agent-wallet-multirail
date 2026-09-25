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
