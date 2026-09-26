"""Tests for the Hyperspace Wallet SDK -> feeless Nano settle rail example."""

from examples.hyperspace_nano_rail import (
    hyperspace_compare,
    hyperspace_pay,
    hyperspace_quote_nano,
    hyperspace_quote_rail,
)


def test_hyperspace_nano_is_feeless():
    """The Nano settle option should always carry fee = 0 and sub-second finality."""
    q = hyperspace_quote_nano(1.0)
    assert q["fee_usd"] == 0.0
    assert q["scheme"] == "exact"
    assert q["network"] == "nano:mainnet"
    assert q["asset"] == "XNO"
    assert q["finality_s"] <= 2.0


def test_hyperspace_other_rail_charges_a_fee():
    """The status-quo x402/ACP/MPP rails should charge a fee > 0."""
    q = hyperspace_quote_rail("x402-usdc", 1.0, fee_pct=0.02)
    assert q["fee_usd"] > 0.0
    assert q["finality_s"] >= 2.0


def test_hyperspace_pay_xno_confirmed():
    """A stub confirming the block should settle True with that block as tx_ref."""
    out = hyperspace_pay(
        hyperspace_quote_nano(1.0),
        nano_rpc=lambda req: {"block": "B01", "confirmed": "true"},
    )
    assert out["settled"] is True
    assert out["receipt"]["tx_ref"] == "B01"
    assert out["receipt"]["fee_usd"] == 0.0


def test_hyperspace_pay_xno_fails_closed():
    """An error / unconfirmed block must report settled=False, never a fake pass."""
    out = hyperspace_pay(
        hyperspace_quote_nano(1.0),
        nano_rpc=lambda req: {"error": "Block is invalid"},
    )
    assert out["settled"] is False
    assert "error" in out
    assert out["receipt"]["tx_ref"] == ""


def test_hyperspace_pay_xno_not_confirmed_is_false():
    """A block hash without a confirmation must not count as settled."""
    out = hyperspace_pay(
        hyperspace_quote_nano(1.0),
        nano_rpc=lambda req: {"block": "B02"},
    )
    assert out["settled"] is False


def test_hyperspace_compare_shows_savings():
    """Settling the same call in XNO should show a real fee saving over priced rails."""
    c = hyperspace_compare(1.0)
    assert c["savings_usd"] > 0.0
    assert c["cheapest_fee_usd"] == 0.0
    assert c["rails"]["x402-usdc"]["fee_usd"] > 0.0
    assert c["rails"]["nano-xno"]["fee_usd"] == 0.0
