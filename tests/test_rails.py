"""Tests for the multi-rail adapter: both rails, dispatch, fees."""

import sys

sys.path.insert(0, "src")
sys.path.insert(0, "examples")

from agent_wallet_multirail.rails import (
    NanoRail,
    PaymentRail,
    PaymanRail,
    Quote,
    SkyfireRail,
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


def test_third_rail_skyfire_is_fee_charging():
    q = SkyfireRail().quote(1.0)
    assert q.fee_usd > 0
    assert q.currency == "USD"
    r = settle("skyfire-usd", 1.0)
    assert r.rail == "skyfire-usd"
    assert r.tx_ref.startswith("skyfire-")


def test_fourth_rail_payman_is_fee_charging():
    q = PaymanRail().quote(1.0)
    assert q.fee_usd > 0
    assert q.currency == "USD"
    r = settle("payman-api", 1.0)
    assert r.rail == "payman-api"
    assert r.tx_ref.startswith("payman-")


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


def test_example_emits_stable_marker():
    """The <--all-rails> mode prints a stable SETTLED_ON marker per rail."""
    import os
    import subprocess as sp
    import sys as _sys

    # The subprocess inherits none of the sys.path this module set up for
    # itself, so it needs src on PYTHONPATH - otherwise the test only passes on
    # a machine where the package happens to be installed, and fails for anyone
    # running the suite in a fresh clone the way the README says to.
    env = dict(os.environ)
    src = os.path.abspath("src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")

    out = sp.run(
        [_sys.executable, "examples/pay_on_any_rail.py", "--all-rails"],
        capture_output=True,
        text=True,
        cwd=".",
        env=env,
    )
    assert out.returncode == 0, out.stderr
    assert "SETTLED_ON:nano-xno FEE_USD:0.000000" in out.stdout
    assert "SETTLED_ON:usdc-evm" in out.stdout
    assert out.stdout.strip().endswith("OK")


def test_a_node_error_is_not_a_settlement():
    """A real rpc answering with an error has settled nothing. Reading a missing
    `confirmed` field as success would report a payment that never happened."""
    rail = NanoRail(rpc=lambda req: {"error": "Fork"})

    result = rail.pay(rail.quote(1.0))

    assert result.settled is False
    assert "Fork" in str(result.meta.get("error", ""))


def test_a_reply_with_no_confirmation_is_not_a_settlement():
    rail = NanoRail(rpc=lambda req: {})

    assert rail.pay(rail.quote(1.0)).settled is False


def test_a_confirmation_with_no_block_is_not_a_settlement():
    """Nothing to show a payer or an auditor is nothing settled."""
    rail = NanoRail(rpc=lambda req: {"confirmed": True})

    result = rail.pay(rail.quote(1.0))

    assert result.settled is False
    assert result.tx_ref == ""


def test_a_string_true_confirmation_settles():
    """A Nano node reports `confirmed` as the string "true", not a bool."""
    rail = NanoRail(rpc=lambda req: {"block": "B2EC", "confirmed": "true"})

    result = rail.pay(rail.quote(1.0))

    assert result.settled is True
    assert result.tx_ref == "B2EC"


def test_a_reply_that_is_not_a_mapping_is_not_a_settlement():
    rail = NanoRail(rpc=lambda req: None)

    assert rail.pay(rail.quote(1.0)).settled is False
