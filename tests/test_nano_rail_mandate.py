"""NanoRail with an operator mandate: the guard runs before the rpc, or the rpc never runs."""
import json

from agent_wallet_multirail import NanoRail, MandateGuard
from agent_wallet_multirail import mandate as M

from test_mandate import AGENT, CAP, NOW, OPERATOR_KEY, OTHER, PAYEE, PER, fixture_mandate


def make_rail(tmp_path, calls):
    signed = M.sign_mandate(fixture_mandate(), OPERATOR_KEY)
    guard = MandateGuard(json.loads(json.dumps(signed)), str(tmp_path / "ledger.json"),
                         agent=AGENT, clock=lambda: NOW)

    def rpc(request):
        calls.append(request)
        return {"block": "AB" * 32, "confirmed": "true"}

    return NanoRail(rpc=rpc, mandate_guard=guard), guard


def test_pay_to_within_the_mandate_settles_and_is_recorded(tmp_path):
    calls = []
    rail, guard = make_rail(tmp_path, calls)
    result = rail.pay_to(PAYEE, PER, ref="invoice-1")
    assert result.settled is True
    assert calls == [{"action": "send", "destination": PAYEE, "amount_raw": str(PER)}]
    assert guard.status()["remaining_raw"] == str(CAP - PER)


def test_refusals_never_reach_the_rpc(tmp_path):
    calls = []
    rail, _ = make_rail(tmp_path, calls)
    over = rail.pay_to(PAYEE, PER + 1)
    wrong = rail.pay_to(OTHER, 1)
    floaty = rail.pay_to(PAYEE, 0.001)
    assert [r.meta["refusal"] for r in (over, wrong, floaty)] == [
        "over_per_payment_max", "payee_not_allowed", "invalid_amount"]
    assert not any(r.settled for r in (over, wrong, floaty))
    assert calls == []


def test_usd_pay_is_refused_when_a_mandate_is_set(tmp_path):
    calls = []
    rail, _ = make_rail(tmp_path, calls)
    result = rail.pay(rail.quote(1.00))
    assert result.settled is False and result.meta["refusal"] == "mandate_requires_raw"
    assert calls == []


def test_without_a_mandate_the_rail_behaves_as_before():
    assert NanoRail().pay(NanoRail().quote(1.0)).settled is True
