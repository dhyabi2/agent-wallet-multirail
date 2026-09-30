"""Laws for revoking an operator mandate before it expires. Offline, no money.

A signature proves who signed; it does not prove the permission is still
live. An operator who changes their mind mid-window needs a way to say so
that the agent's runtime obeys and that a stranger can check with the same
public key: a revocation, signed with the operator's own Nano key over a
different domain from the mandate, so neither signature can stand in for
the other.
"""
import datetime as dt
import json

import pytest

from agent_wallet_multirail import mandate as M
from test_mandate import (AGENT, NOW, OPERATOR, OPERATOR_KEY, AGENT_KEY, PAYEE, PER,
                          fixture_mandate)

LATER = NOW + dt.timedelta(hours=1)


@pytest.fixture(scope="module")
def signed():
    return M.sign_mandate(fixture_mandate(), OPERATOR_KEY)


def _guard(signed_doc, tmp_path, when=NOW):
    return M.MandateGuard(json.loads(json.dumps(signed_doc)), str(tmp_path / "ledger.json"),
                          clock=lambda: when, revocation_path=str(tmp_path / "revoked.json"))


def _write(tmp_path, doc):
    (tmp_path / "revoked.json").write_text(json.dumps(doc))


def test_a_signed_revocation_stops_the_next_spend(signed, tmp_path):
    guard = _guard(signed, tmp_path)
    sent = []
    guard.spend(PAYEE, PER, lambda: sent.append(1))
    _write(tmp_path, M.sign_revocation(signed["hash"], OPERATOR_KEY, revoked_at="2026-09-28T00:00:00Z",
                                       reason="task cancelled"))
    with pytest.raises(M.MandateRefused) as exc:
        guard.spend(PAYEE, PER, lambda: sent.append(1))
    assert exc.value.reason == "revoked" and sent == [1]
    with pytest.raises(M.MandateRefused) as exc:
        guard.check(PAYEE, PER)
    assert exc.value.reason == "revoked"
    status = guard.status()
    assert status["valid"] is False and status["refusal"] == "revoked"
    assert status["revoked_at"] == "2026-09-28T00:00:00Z"


def test_a_revocation_dated_in_the_future_takes_effect_at_its_time(signed, tmp_path):
    _write(tmp_path, M.sign_revocation(signed["hash"], OPERATOR_KEY, revoked_at="2026-09-28T00:30:00Z"))
    guard = _guard(signed, tmp_path)
    guard.spend(PAYEE, PER, lambda: "ok")
    guard.clock = lambda: LATER
    with pytest.raises(M.MandateRefused) as exc:
        guard.spend(PAYEE, PER, lambda: "ok")
    assert exc.value.reason == "revoked"


def test_a_revocation_not_signed_by_the_operator_fails_closed(signed, tmp_path):
    _write(tmp_path, M.sign_revocation(signed["hash"], AGENT_KEY, revoked_at="2026-09-28T00:00:00Z",
                                       operator=AGENT))
    with pytest.raises(M.MandateRefused) as exc:  # refused already when the guard is built
        _guard(signed, tmp_path).spend(PAYEE, PER, lambda: "ok")
    assert exc.value.reason == "invalid_revocation"


def test_a_revocation_of_another_mandate_fails_closed(signed, tmp_path):
    other = M.sign_mandate(fixture_mandate(nonce="ff" * 16), OPERATOR_KEY)
    _write(tmp_path, M.sign_revocation(other["hash"], OPERATOR_KEY, revoked_at="2026-09-28T00:00:00Z"))
    with pytest.raises(M.MandateRefused) as exc:
        _guard(signed, tmp_path).spend(PAYEE, PER, lambda: "ok")
    assert exc.value.reason == "invalid_revocation"


def test_an_edited_revocation_fails_closed(signed, tmp_path):
    doc = M.sign_revocation(signed["hash"], OPERATOR_KEY, revoked_at="2026-09-28T00:00:00Z")
    doc["revocation"]["revoked_at"] = "2099-01-01T00:00:00Z"  # try to push the revocation out of reach
    _write(tmp_path, doc)
    with pytest.raises(M.MandateRefused) as exc:
        _guard(signed, tmp_path).spend(PAYEE, PER, lambda: "ok")
    assert exc.value.reason == "invalid_revocation"


def test_an_unreadable_revocation_file_fails_closed(signed, tmp_path):
    (tmp_path / "revoked.json").write_text("{not json")
    with pytest.raises(M.MandateRefused) as exc:
        _guard(signed, tmp_path).spend(PAYEE, PER, lambda: "ok")
    assert exc.value.reason == "invalid_revocation"


def test_a_mandate_signature_is_not_a_revocation_signature(signed, tmp_path):
    doc = M.sign_revocation(signed["hash"], OPERATOR_KEY, revoked_at="2026-09-28T00:00:00Z")
    doc["signature"] = signed["signature"]
    _write(tmp_path, doc)
    with pytest.raises(M.MandateRefused) as exc:
        _guard(signed, tmp_path).spend(PAYEE, PER, lambda: "ok")
    assert exc.value.reason == "invalid_revocation"
    assert M.revocation_signing_message(doc["revocation"]) != M.signing_message(signed["mandate"])


def test_a_stranger_can_verify_a_revocation_with_only_public_data(signed):
    doc = M.sign_revocation(signed["hash"], OPERATOR_KEY, revoked_at="2026-09-28T00:00:00Z")
    public = json.loads(json.dumps(doc))
    view = M.verify_revocation(public, mandate_hash_hex=signed["hash"], operator=OPERATOR)
    assert view["revoked_at"] == "2026-09-28T00:00:00Z" and view["operator"] == OPERATOR


def test_no_revocation_file_changes_nothing(signed, tmp_path):
    guard = _guard(signed, tmp_path)
    assert guard.spend(PAYEE, PER, lambda: "sent") == "sent"
    assert guard.status()["valid"] is True and guard.status()["revoked_at"] is None


def test_cli_revoke_then_check_and_status_refuse(tmp_path, capsys):
    key = tmp_path / "operator.key"
    assert M.main(["keygen", "--out", str(key)]) == 0
    out = tmp_path / "mandate.json"
    assert M.main(["create", "--operator-key", str(key), "--agent", AGENT, "--total-cap-xno", "0.5",
                   "--per-payment-max-xno", "0.01", "--purpose", "API calls", "--days", "30",
                   "--out", str(out)]) == 0
    capsys.readouterr()
    assert M.main(["check", str(out), "--payee", PAYEE, "--amount-raw", str(PER)]) == 0
    capsys.readouterr()
    assert M.main(["revoke", str(out), "--operator-key", str(key), "--reason", "done"]) == 0
    written = json.loads(capsys.readouterr().out)
    assert written["written"] == str(out) + ".revoked.json"
    assert M.main(["check", str(out), "--payee", PAYEE, "--amount-raw", str(PER)]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "revoked"
    assert M.main(["status", str(out)]) == 1
    assert json.loads(capsys.readouterr().out)["refusal"] == "revoked"
    assert M.main(["verify", str(out)]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "revoked"
