"""Laws for the operator mandate. Offline: no node, no network, no real money.

Every expected value below comes from somewhere other than the code under test:
  * the Nano zero-seed vector (published in Nano's own docs and pinned by
    nano-wallet-xno) for key derivation with BLAKE2b,
  * RFC 8032 test 1 for the curve arithmetic with SHA-512,
  * a canonical JSON string written out BY HAND here, hashed with hashlib,
  * a signature produced by the independent C library `ed25519-blake2b` 1.4.1
    (the implementation Nano's Python tooling uses) over the same message.
"""
import datetime as dt
import hashlib
import json

import pytest

from agent_wallet_multirail import mandate as M

# Obviously synthetic keys: repeated bytes. Never a real seed.
OPERATOR_SEED = "11" * 32  # test-fixture
AGENT_SEED = "22" * 32  # test-fixture
PAYEE_SEED = "33" * 32  # test-fixture
OTHER_SEED = "44" * 32  # test-fixture

OPERATOR_KEY = M.private_key_from_seed(bytes.fromhex(OPERATOR_SEED), 0)
AGENT_KEY = M.private_key_from_seed(bytes.fromhex(AGENT_SEED), 0)
OPERATOR = "nano_1bwjtpipkzc7aj6hmuodncjmfsb4tou9word8bj9jxcm68cheipad54q66xe"
AGENT = "nano_3166w1xhtgg1b46izokwhxq9aist9wagha6eouuce7fy5fyrbb1xjgzwwm3c"
PAYEE = "nano_1p7cqqnfo91zwcnse54f3ucyfi6xwzsbnkt3ay14cd1g6epmiygnt7jtcoa5"
OTHER = M.address_from_public_key(M.public_key_from_private(M.private_key_from_seed(bytes.fromhex(OTHER_SEED))))

XNO = 10 ** 30
CAP = XNO // 2            # 0.5 XNO
PER = XNO // 100          # 0.01 XNO

# Written by hand: the canonical form is sorted keys, no whitespace, ASCII.
CANONICAL = (
    '{"agent":"nano_3166w1xhtgg1b46izokwhxq9aist9wagha6eouuce7fy5fyrbb1xjgzwwm3c",'
    '"allowed_payees":["nano_1p7cqqnfo91zwcnse54f3ucyfi6xwzsbnkt3ay14cd1g6epmiygnt7jtcoa5"],'
    '"expires_at":"2030-01-01T00:00:00Z","issued_at":"2026-09-27T00:00:00Z",'
    '"nonce":"00112233445566778899aabbccddeeff",'
    '"operator":"nano_1bwjtpipkzc7aj6hmuodncjmfsb4tou9word8bj9jxcm68cheipad54q66xe",'
    '"per_payment_max_raw":"10000000000000000000000000000",'
    '"purpose":"Buy web-search API calls for the research task",'
    '"total_cap_raw":"500000000000000000000000000000",'
    '"type":"nano-operator-mandate","version":1}'
)
GOLDEN_HASH = "3967D88A777758AF459E77D8C81DCFDA2E91A6841A58BD6FA7CFC5DBFFE1505F"
# ed25519_blake2b.SigningKey(OPERATOR_KEY).sign(b"nano-operator-mandate/v1:" + bytes.fromhex(GOLDEN_HASH))
GOLDEN_SIGNATURE = (
    "19A401D0CFD28D8EAB5D126EE314246021E40BEF107C7995A8515A86175D916F"
    "531EDE2C43C75444851AC82663D8E391FD1BFB7392E11AE5FF291FA8DA53220E"
)

NOW = dt.datetime(2026, 9, 28, tzinfo=dt.timezone.utc)


def fixture_mandate(**overrides):
    fields = dict(agent=AGENT, operator=OPERATOR, total_cap_raw=str(CAP), per_payment_max_raw=str(PER),
                  purpose="Buy web-search API calls for the research task",
                  expires_at="2030-01-01T00:00:00Z", allowed_payees=[PAYEE],
                  issued_at="2026-09-27T00:00:00Z", nonce="00112233445566778899aabbccddeeff")
    fields.update(overrides)
    return M.build_mandate(**fields)


@pytest.fixture(scope="module")
def signed():
    return M.sign_mandate(fixture_mandate(), OPERATOR_KEY)


def guard_for(signed_doc, tmp_path, when=NOW, agent=None):
    return M.MandateGuard(json.loads(json.dumps(signed_doc)), str(tmp_path / "ledger.json"),
                          agent=agent, clock=lambda: when)


# ---------------------------------------------------------------- crypto oracles

def test_zero_seed_vector_pins_nano_key_derivation():
    private = M.private_key_from_seed(bytes(32), 0)
    assert private.hex().upper() == "9F0E444C69F77A49BD0BE89DB92C38FE713E0963165CCA12FAF5712D7657120F"
    public = M.public_key_from_private(private)
    assert public.hex().upper() == "C008B814A7D269A1FA3C6528B19201A24D797912DB9996FF02A1FF356E45552B"
    assert M.address_from_public_key(public) == \
        "nano_3i1aq1cchnmbn9x5rsbap8b15akfh7wj7pwskuzi7ahz8oq6cobd99d4r3b7"


def test_rfc8032_vector_1_pins_sign_and_verify():
    secret = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    public = M.public_key_from_private(secret, M._sha512)
    assert public.hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    signature = M.sign(b"", secret, M._sha512)
    assert signature.hex() == (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
        "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    assert M.verify(signature, b"", public, M._sha512)
    assert not M.verify(signature, b"x", public, M._sha512)


def test_fixture_addresses_are_the_fixture_keys():
    assert M.address_from_public_key(M.public_key_from_private(OPERATOR_KEY)) == OPERATOR
    assert M.address_from_public_key(M.public_key_from_private(AGENT_KEY)) == AGENT


# ---------------------------------------------------------------- canonical form + hash

def test_canonical_serialisation_matches_the_hand_written_form():
    assert M.canonical_bytes(fixture_mandate()).decode("ascii") == CANONICAL


def test_mandate_hash_is_blake2b_over_domain_and_canonical_bytes_and_stable():
    expected = hashlib.blake2b(b"nano-operator-mandate/v1\n" + CANONICAL.encode(), digest_size=32)
    assert expected.hexdigest().upper() == GOLDEN_HASH
    mandate = fixture_mandate()
    assert M.mandate_hash(mandate) == GOLDEN_HASH
    shuffled = dict(reversed(list(mandate.items())))
    assert M.mandate_hash(shuffled) == GOLDEN_HASH
    assert M.mandate_hash(json.loads(json.dumps(mandate, indent=4))) == GOLDEN_HASH


def test_signature_matches_the_independent_c_library(signed):
    assert signed["hash"] == GOLDEN_HASH
    assert signed["signature"] == GOLDEN_SIGNATURE


def test_signature_round_trip(signed):
    view = M.verify_signed(signed, now=NOW, agent=AGENT)
    assert view["hash"] == GOLDEN_HASH
    assert view["total_cap_raw"] == CAP and view["per_payment_max_raw"] == PER


# ---------------------------------------------------------------- tampering

def test_tampered_cap_is_refused_by_the_hash(signed):
    doc = json.loads(json.dumps(signed))
    doc["mandate"]["total_cap_raw"] = str(CAP * 100)
    with pytest.raises(M.MandateRefused) as exc:
        M.verify_signed(doc, now=NOW)
    assert exc.value.reason == "hash_mismatch"


def test_tampered_cap_with_recomputed_hash_is_refused_by_the_signature(signed):
    doc = json.loads(json.dumps(signed))
    doc["mandate"]["total_cap_raw"] = str(CAP * 100)
    doc["hash"] = M.mandate_hash(doc["mandate"])
    with pytest.raises(M.MandateRefused) as exc:
        M.verify_signed(doc, now=NOW)
    assert exc.value.reason == "bad_signature"


def test_a_mandate_the_agent_signed_for_itself_is_refused():
    mandate = fixture_mandate()
    doc = {"mandate": mandate, "hash": M.mandate_hash(mandate),
           "signature": M.sign(M.signing_message(mandate), AGENT_KEY).hex().upper()}
    with pytest.raises(M.MandateRefused) as exc:
        M.verify_signed(doc, now=NOW)
    assert exc.value.reason == "bad_signature"


def test_signing_with_a_key_that_is_not_the_operator_is_refused():
    with pytest.raises(M.MandateRefused) as exc:
        M.sign_mandate(fixture_mandate(), AGENT_KEY)
    assert exc.value.reason == "wrong_key"


def test_signature_is_not_a_bare_hash_signature(signed):
    # The signed message carries a domain tag, so it can never double as a
    # signature over a 32-byte Nano block hash.
    op_pk = M.public_key_from_address(OPERATOR)
    assert not M.verify(bytes.fromhex(signed["signature"]), bytes.fromhex(GOLDEN_HASH), op_pk)


def test_unknown_and_missing_fields_are_refused(signed):
    doc = json.loads(json.dumps(signed))
    doc["mandate"]["unlimited"] = True
    with pytest.raises(M.MandateRefused) as exc:
        M.verify_signed(doc, now=NOW)
    assert exc.value.reason == "invalid_mandate"
    with pytest.raises(M.MandateRefused) as exc:
        fixture_mandate(purpose="   ")
    assert exc.value.reason == "missing_purpose"


def test_operator_and_agent_must_differ():
    with pytest.raises(M.MandateRefused):
        fixture_mandate(operator=AGENT)


def test_per_payment_max_above_the_cap_is_refused():
    with pytest.raises(M.MandateRefused):
        fixture_mandate(per_payment_max_raw=str(CAP + 1))


# ---------------------------------------------------------------- expiry + agent

def test_expired_mandate_is_refused(signed, tmp_path):
    at_expiry = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    with pytest.raises(M.MandateRefused) as exc:
        M.verify_signed(signed, now=at_expiry)
    assert exc.value.reason == "expired"
    guard = guard_for(signed, tmp_path)
    guard.clock = lambda: at_expiry
    calls = []
    with pytest.raises(M.MandateRefused) as exc:
        guard.spend(PAYEE, PER, lambda: calls.append(1))
    assert exc.value.reason == "expired" and calls == []


def test_not_yet_valid_mandate_is_refused(signed):
    with pytest.raises(M.MandateRefused) as exc:
        M.verify_signed(signed, now=dt.datetime(2026, 9, 26, tzinfo=dt.timezone.utc))
    assert exc.value.reason == "not_yet_valid"


def test_wrong_agent_is_refused(signed):
    with pytest.raises(M.MandateRefused) as exc:
        M.verify_signed(signed, now=NOW, agent=OTHER)
    assert exc.value.reason == "wrong_agent"


# ---------------------------------------------------------------- enforcement

def test_cap_exhaustion_is_refused_and_send_never_called(signed, tmp_path):
    guard = guard_for(signed, tmp_path)
    sent = []
    for _ in range(CAP // PER):  # 50 payments of 0.01 XNO exhaust 0.5 XNO exactly
        guard.spend(PAYEE, PER, lambda: sent.append(1) or "ok")
    assert len(sent) == 50
    assert guard.status()["remaining_raw"] == "0"
    with pytest.raises(M.MandateRefused) as exc:
        guard.spend(PAYEE, 1, lambda: sent.append(1))
    assert exc.value.reason == "cap_exhausted" and len(sent) == 50


def test_remaining_cap_is_exact_in_raw(signed, tmp_path):
    guard = guard_for(signed, tmp_path)
    guard.spend(PAYEE, PER - 1, lambda: None)
    status = guard.status()
    assert int(status["spent_raw"]) == PER - 1
    assert int(status["remaining_raw"]) == CAP - PER + 1


def test_per_payment_max_is_enforced(signed, tmp_path):
    guard = guard_for(signed, tmp_path)
    guard.spend(PAYEE, PER, lambda: None)  # exactly the max is allowed
    with pytest.raises(M.MandateRefused) as exc:
        guard.spend(PAYEE, PER + 1, lambda: pytest.fail("send must not run"))
    assert exc.value.reason == "over_per_payment_max"


def test_payee_not_on_the_allow_list_is_refused(signed, tmp_path):
    guard = guard_for(signed, tmp_path)
    with pytest.raises(M.MandateRefused) as exc:
        guard.spend(OTHER, 1, lambda: pytest.fail("send must not run"))
    assert exc.value.reason == "payee_not_allowed"
    xrb_alias = "xrb_" + PAYEE[len("nano_"):]
    guard.spend(xrb_alias, 1, lambda: None)  # same key under the legacy prefix
    with pytest.raises(M.MandateRefused) as exc:
        guard.spend(PAYEE[:-1] + ("1" if PAYEE[-1] != "1" else "3"), 1, lambda: None)
    assert exc.value.reason == "invalid_address"


def test_no_allow_list_means_any_valid_payee(tmp_path):
    doc = M.sign_mandate(fixture_mandate(allowed_payees=None), OPERATOR_KEY)
    guard_for(doc, tmp_path).spend(OTHER, 1, lambda: None)


@pytest.mark.parametrize("amount", [0.01, 1e28, True, "1.5", "01", "-5", "0", 0, -1, "", None, 2 ** 128])
def test_amounts_are_positive_raw_integers_only(signed, tmp_path, amount):
    guard = guard_for(signed, tmp_path)
    with pytest.raises(M.MandateRefused) as exc:
        guard.spend(PAYEE, amount, lambda: pytest.fail("send must not run"))
    assert exc.value.reason == "invalid_amount"


def test_int_and_integer_string_are_the_same_amount(signed, tmp_path):
    guard = guard_for(signed, tmp_path)
    guard.spend(PAYEE, 7, lambda: None)
    guard.spend(PAYEE, "7", lambda: None)
    assert guard.status()["spent_raw"] == "14"


def test_xno_conversion_is_exact():
    assert M.xno_to_raw("0.000001") == 10 ** 24
    assert M.xno_to_raw("1") == XNO
    assert M.xno_to_raw("0.000000000000000000000000000001") == 1
    assert M.raw_to_xno(CAP) == "0.5"
    with pytest.raises(M.MandateRefused):
        M.xno_to_raw("0.0000000000000000000000000000001")  # 31 decimals


def test_a_float_in_the_mandate_file_is_refused(signed, tmp_path):
    text = json.dumps(signed).replace('"version": 1', '"version": 1.0')
    path = tmp_path / "m.json"
    path.write_text(text)
    with pytest.raises(M.MandateRefused) as exc:
        M.load_signed(str(path))
    assert exc.value.reason == "invalid_amount"


def test_amounts_in_the_document_must_be_strings(signed):
    doc = json.loads(json.dumps(signed))
    doc["mandate"]["total_cap_raw"] = CAP
    with pytest.raises(M.MandateRefused) as exc:
        M.verify_signed(doc, now=NOW)
    assert exc.value.reason == "invalid_amount"


# ---------------------------------------------------------------- the ledger fails closed

def test_a_send_that_raises_stays_counted(signed, tmp_path):
    guard = guard_for(signed, tmp_path)

    def boom():
        raise TimeoutError("node did not answer")

    with pytest.raises(TimeoutError):
        guard.spend(PAYEE, PER, boom)
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["payments"][0]["status"] == "unknown"
    assert guard.status()["spent_raw"] == str(PER)


def test_a_corrupt_ledger_refuses(signed, tmp_path):
    guard = guard_for(signed, tmp_path)
    (tmp_path / "ledger.json").write_text("{not json")
    with pytest.raises(M.MandateRefused) as exc:
        guard.spend(PAYEE, 1, lambda: pytest.fail("send must not run"))
    assert exc.value.reason == "ledger_unreadable"


def test_an_edited_ledger_total_refuses(signed, tmp_path):
    guard = guard_for(signed, tmp_path)
    guard.spend(PAYEE, PER, lambda: None)
    data = json.loads((tmp_path / "ledger.json").read_text())
    data["spent_raw"] = "0"
    (tmp_path / "ledger.json").write_text(json.dumps(data))
    with pytest.raises(M.MandateRefused) as exc:
        guard.spend(PAYEE, 1, lambda: None)
    assert exc.value.reason == "ledger_corrupt"


def test_a_ledger_of_another_mandate_refuses(signed, tmp_path):
    other = M.sign_mandate(fixture_mandate(nonce="ffeeddccbbaa99887766554433221100"), OPERATOR_KEY)
    guard_for(other, tmp_path).spend(PAYEE, 1, lambda: None)
    with pytest.raises(M.MandateRefused) as exc:
        guard_for(signed, tmp_path).spend(PAYEE, 1, lambda: None)
    assert exc.value.reason == "ledger_mismatch"


def test_check_is_a_dry_run(signed, tmp_path):
    guard = guard_for(signed, tmp_path)
    assert guard.check(PAYEE, PER)["remaining_after_raw"] == str(CAP - PER)
    assert guard.status()["spent_raw"] == "0"


# ---------------------------------------------------------------- CLI

def test_cli_round_trip(tmp_path, capsys):
    key = tmp_path / "operator.key"
    assert M.main(["keygen", "--out", str(key)]) == 0
    operator = json.loads(capsys.readouterr().out)["address"]
    assert oct(key.stat().st_mode & 0o777) == "0o600"
    out = tmp_path / "mandate.json"
    assert M.main(["create", "--operator-key", str(key), "--agent", AGENT, "--total-cap-xno", "0.5",
                   "--per-payment-max-xno", "0.01", "--purpose", "API calls", "--days", "30",
                   "--payee", PAYEE, "--out", str(out)]) == 0
    capsys.readouterr()
    assert M.main(["verify", str(out), "--agent", AGENT]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["operator"] == operator and verified["total_cap_raw"] == str(CAP)
    assert M.main(["check", str(out), "--payee", PAYEE, "--amount-raw", str(PER)]) == 0
    capsys.readouterr()
    assert M.main(["check", str(out), "--payee", PAYEE, "--amount-raw", str(PER + 1)]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "over_per_payment_max"
    assert M.main(["status", str(out)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["remaining_raw"] == str(CAP) and status["remaining_xno"] == "0.5"
    doc = json.loads(out.read_text())
    doc["mandate"]["purpose"] = "anything at all"
    out.write_text(json.dumps(doc))
    assert M.main(["verify", str(out)]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "hash_mismatch"


def test_cli_two_step_unsigned_then_sign(tmp_path, capsys):
    key = tmp_path / "operator.key"
    M.main(["keygen", "--out", str(key)])
    operator = json.loads(capsys.readouterr().out)["address"]
    unsigned = tmp_path / "unsigned.json"
    assert M.main(["create", "--operator", operator, "--agent", AGENT, "--total-cap-raw", "1000",
                   "--per-payment-max-raw", "10", "--purpose", "API calls",
                   "--expires", "2030-01-01T00:00:00Z", "--out", str(unsigned)]) == 0
    capsys.readouterr()
    assert M.main(["verify", str(unsigned)]) == 1  # unsigned is not a mandate
    capsys.readouterr()
    signed_path = tmp_path / "signed.json"
    assert M.main(["sign", str(unsigned), "--operator-key", str(key), "--out", str(signed_path)]) == 0
    capsys.readouterr()
    assert M.main(["verify", str(signed_path)]) == 0
