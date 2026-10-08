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


def test_the_stub_verifier_ignores_the_payee_and_the_amount():
    """The stub answers from the payer's own hash, so it cannot gate fulfilment.

    This used to be ``test_crossmint_nano_verify_valid_hash``, asserting that
    ``crossmint_verify_receipt("block_hash_dead", "nano_xxx", 100) is True`` was
    a receipt being *verified*. It is not: ``block_hash_dead`` is a string the
    payer chooses, ``nano_xxx`` is not even a well-formed Nano address, and the
    stub reads neither the payee nor the amount. A green test named "verify
    valid hash" reads as the gate working.

    The behaviour is unchanged and deliberately so -- the stub documents the
    seam. What is asserted is the hazard, so the day someone wires this to a
    fulfilment flow, the test says why they must not.
    """
    # The same hash "verifies" against a payee it never paid...
    assert crossmint_verify_receipt("block_hash_dead", "nano_xxx", 100) is True
    assert crossmint_verify_receipt("block_hash_dead", "nano_someone_else", 100) is True
    # ...and against an amount a thousand times the one quoted.
    assert crossmint_verify_receipt("block_hash_dead", "nano_xxx", 100_000) is True
    # It is the hash alone, which is the payer's to pick.
    assert crossmint_verify_receipt("not_a_real_block_but_ends_in_dead", "", 0) is True


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

def test_the_published_accepts_entry_asks_for_the_price_it_names():
    """The ``accepts[]`` block a maintainer copies must not ask for 100x the price.

    The round-trip doc published ``"amount": "5000000000000000000000000000000"``
    against the comment ``raw XNO for $0.05``. That is 5 XNO. Nothing in this
    file computes it, so no test could catch it drifting; a payer who copied the
    entry and paid it would send a hundred times the stated price for a $0.05
    purchase. The figure is now derived from the price the file itself quotes,
    at the rate the comment states.
    """
    import re

    from examples.crossmint_nano_adapter import _NANO_ROUNDTRIP, crossmint_quote_nano

    match = re.search(r'"amount":\s*"(\d+)"', _NANO_ROUNDTRIP)
    assert match is not None, "the round trip no longer publishes an accepts[] amount"
    published = int(match.group(1))

    # The price the file quotes for this round trip, and the rate its comment states.
    price_usd = crossmint_quote_nano(0.05)["amount_usd"]
    assert price_usd == 0.05
    xno_per_usd = 1  # "at 1 XNO = $1.00", stated beside the figure
    # 0.05 XNO in raw, in integers: never 0.05 * 10**30 as a float.
    expected = 5 * 10 ** 28 * xno_per_usd
    assert published == expected, (
        "the published accepts[] amount is %s raw (%s XNO); $%s at 1 XNO = $1.00 is %s raw"
        % (published, published / 10 ** 30, price_usd, expected))
    assert published != 5 * 10 ** 30, "this is the 5 XNO figure the entry used to publish"
