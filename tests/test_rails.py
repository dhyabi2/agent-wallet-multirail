"""Tests for the multi-rail adapter: both rails, dispatch, fees."""

import sys

sys.path.insert(0, "src")
sys.path.insert(0, "examples")

from agent_wallet_multirail.rails import (
    NanoRail,
    PaymentRail,
    Quote,
    UsdcRail,
    rail_for,
    settle,
)


def test_both_rails_implement_interface():
    nano, usdc = NanoRail(), UsdcRail()
    for rail in (nano, usdc):
        assert isinstance(rail, PaymentRail)
        assert callable(rail.quote)
        assert callable(rail.pay)
        assert isinstance(rail.name, str)
        assert isinstance(rail.quote(1.0), Quote)


def test_nano_is_feeless_and_sub_second():
    q = NanoRail().quote(1.0)
    assert q.fee_usd == 0
    assert q.finality_s < 1
    assert q.currency == "XNO"


def test_usdc_charges_a_fee():
    q = UsdcRail().quote(1.0)
    assert q.fee_usd > 0
    assert q.finality_s >= 1
    assert q.currency == "USDC"


def test_settle_dispatches_to_the_chosen_rail():
    nano = settle("nano-xno", 1.0)
    assert nano.rail == "nano-xno"
    assert nano.settled is True
    assert nano.fee_usd == 0
    assert nano.tx_ref

    usdc = settle("usdc-evm", 1.0)
    assert usdc.rail == "usdc-evm"
    assert usdc.settled is True


def test_settle_refuses_unknown_rail():
    import pytest

    with pytest.raises(KeyError):
        settle("no-such-rail", 1.0)


def test_nano_rpc_seam_is_honest(monkeypatch):
    """NanoRail pays through a pluggable rpc; the example uses a local stub."""
    calls = {}

    def fake_rpc(req):
        calls.update(req)
        return {"block": "block-abc", "confirmed": True}

    rail = NanoRail(rpc=fake_rpc)
    result = rail.pay(rail.quote(0.01))
    assert result.tx_ref == "block-abc"
    assert result.settled is True
    assert calls.get("action") == "send"


def test_rail_for_returns_registered_rails():
    assert rail_for("nano-xno").name == "nano-xno"
    assert rail_for("usdc-evm").name == "usdc-evm"
