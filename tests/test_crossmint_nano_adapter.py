"""Tests for the Crossmint Nano adapter example."""

from examples.crossmint_nano_adapter import (
    crossmint_quote_nano,
    crossmint_quote_usdc,
    crossmint_verify_receipt,
)


def test_crossmint_nano_is_feeless():
    """The Nano settle option should always have fee = 0."""
    q = crossmint_quote_nano(1.0)
    assert q["fee_usd"] == 0.0
    assert q["scheme"] == "exact"
    assert q["network"] == "nano:mainnet"
    assert q["asset"] == "XNO"
    assert q["finality_s"] <= 2.0


def test_crossmint_usdc_charges_a_fee():
    """The USDC settle option should charge > 0 fee."""
    q = crossmint_quote_usdc(1.0)
    assert q["fee_usd"] > 0.0
    assert q["scheme"] == "onchain-proof"
    assert q["network"] == "base"
    assert q["asset"] == "USDC"


def test_crossmint_nano_verify_valid_hash():
    """Verify a receipt for a hash that ends in 'dead' returns True."""
    assert crossmint_verify_receipt("block_hash_dead", "nano_xxx", 100) is True


def test_crossmint_nano_verify_invalid_hash():
    """Verify a receipt for an arbitrary hash returns False."""
    assert crossmint_verify_receipt("abc123def", "nano_xxx", 100) is False


def test_crossmint_nano_verify_empty_hash():
    """Verify a receipt for an empty hash returns False."""
    assert crossmint_verify_receipt("", "nano_xxx", 100) is False


def test_crossmint_quotes_have_expected_keys():
    """Both quote functions return all expected fields."""
    for func in (crossmint_quote_nano, crossmint_quote_usdc):
        q = func(0.05)
        for key in ("scheme", "network", "asset", "amount_usd", "fee_usd", "finality_s"):
            assert key in q, f"missing key {key} in {func.__name__}"