"""A `payments` the ledger cannot count is a spend total it cannot vouch for.

`MandateGuard._read` is the only thing standing between a damaged ledger file and
a cap the guard believes. It checked the arithmetic before the shape:

    spent = int(data["spent_raw"]) if str(data["spent_raw"]).isdigit() else None
    if spent is None or sum(int(p["amount_raw"]) for p in data["payments"]) != spent:
        raise MandateRefused("ledger_corrupt", ...)

An EMPTY dict or string iterates to nothing, so that sum is 0 and agrees with a
`"spent_raw": "0"`. A ledger of `{"spent_raw": "0", "payments": {}}` was therefore
read as a healthy ledger with nothing spent: `check()` and `status()` reported the
whole cap intact, and `spend()` - the path that pays - then died on
`payments.append` with an **AttributeError**, not a `MandateRefused`. A caller
following the documented surface (`except MandateRefused`, as the README's snippet
and `NanoRail.pay_to` both do) saw an unhandled crash instead of a refusal.
A non-EMPTY dict happened to be refused, because iterating it yields its keys and
`"some key"["amount_raw"]` raises - which is why this looked covered.

The second half is the same hole with a float in it. The mandate is read with
`parse_float=_refuse_float`, but the ledger was read with a plain `json.load`, and
the total is an `int()` sum - so `{"amount_raw": 1.9}` beside `"spent_raw": "1"`
truncated to 1, agreed with the total, and was accepted. Money is an integer count
of raw end to end (1 XNO = 10**30 raw), and that includes the file recording how
much of the cap is gone.

Both refusals only narrow what is accepted. A ledger this module wrote is
unaffected: `spend()` writes `payments` as a list and each `amount_raw` as
`str(amount_raw)`, which the controls below pin.
"""
import json
import os
import tempfile
import unittest

from agent_wallet_multirail import mandate
from agent_wallet_multirail.mandate import MandateGuard, MandateRefused


def _operator_key():
    return mandate.private_key_from_seed(bytes(range(32)), 0)


def _address(seed_byte: int):
    key = mandate.private_key_from_seed(bytes(range(seed_byte, seed_byte + 32)), 0)
    return mandate.address_from_public_key(mandate.public_key_from_private(key))


class LedgerShape(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        operator_key = _operator_key()
        self.operator = mandate.address_from_public_key(
            mandate.public_key_from_private(operator_key)
        )
        self.agent = _address(1)
        self.payee = _address(2)
        doc = mandate.build_mandate(
            agent=self.agent,
            operator=self.operator,
            total_cap_raw="500000000000000000000000000000",
            per_payment_max_raw="10000000000000000000000000000",
            purpose="probing the ledger's integrity check",
            expires_at="2099-01-01T00:00:00Z",
        )
        self.signed = mandate.sign_mandate(doc, operator_key)
        self.hash = mandate.mandate_hash(doc)
        self.mandate_path = os.path.join(self.dir, "mandate.json")
        with open(self.mandate_path, "w", encoding="utf-8") as fh:
            json.dump(self.signed, fh)
        self.ledger_path = self.mandate_path + mandate.LEDGER_SUFFIX

    def _write_ledger(self, obj):
        with open(self.ledger_path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)

    def _guard(self):
        return MandateGuard.from_file(self.mandate_path)

    def _send(self):
        return {"block": "SIM", "confirmed": True}

    # ------------------------------------------------ a payments it cannot count

    def test_an_empty_dict_payments_is_refused_not_read_as_no_payments(self):
        self._write_ledger({"mandate_hash": self.hash, "spent_raw": "0", "payments": {}})
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertEqual(caught.exception.reason, "ledger_corrupt")

    def test_an_empty_string_payments_is_refused(self):
        self._write_ledger({"mandate_hash": self.hash, "spent_raw": "0", "payments": ""})
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertEqual(caught.exception.reason, "ledger_corrupt")

    def test_check_does_not_report_a_full_cap_on_a_malformed_payments(self):
        """The reported remaining cap was the whole cap, from a file that records
        nothing countable.

        Only the EMPTY dict and string were accepted before this fix. A `0`, or a
        non-empty dict, already refused - iterating them raises, which the generic
        handler turned into `ledger_unreadable`. Those are in
        `test_an_uncountable_payments_now_names_the_ledger_as_corrupt` below, kept
        apart so this test's failure means what it says.
        """
        for payments in ({}, ""):
            with self.subTest(payments=payments):
                self._write_ledger(
                    {"mandate_hash": self.hash, "spent_raw": "0", "payments": payments}
                )
                with self.assertRaises(MandateRefused) as caught:
                    self._guard().check(self.payee, 10 ** 27)
                self.assertEqual(caught.exception.reason, "ledger_corrupt")

    def test_spend_refuses_rather_than_raising_an_attribute_error(self):
        """The documented surface is MandateRefused. `.append` on a dict is not."""
        for payments in ({}, ""):
            with self.subTest(payments=payments):
                self._write_ledger(
                    {"mandate_hash": self.hash, "spent_raw": "0", "payments": payments}
                )
                guard = self._guard()
                try:
                    guard.spend(self.payee, 10 ** 27, self._send)
                except MandateRefused as refused:
                    self.assertEqual(refused.reason, "ledger_corrupt")
                except Exception as other:  # pragma: no cover - the defect
                    self.fail(
                        "spend() raised %s (%s) instead of MandateRefused; a caller "
                        "catching MandateRefused sees an unhandled crash on the path "
                        "that pays" % (type(other).__name__, other)
                    )
                else:
                    self.fail("spend() went ahead on a ledger it could not count")

    def test_status_refuses_a_malformed_payments(self):
        self._write_ledger({"mandate_hash": self.hash, "spent_raw": "0", "payments": {}})
        with self.assertRaises(MandateRefused) as caught:
            self._guard().status()
        self.assertEqual(caught.exception.reason, "ledger_corrupt")

    def test_an_uncountable_payments_now_names_the_ledger_as_corrupt(self):
        """Already refused before the fix, but as `ledger_unreadable` - the reason
        reserved for a file that could not be read at all. It was read fine; it
        was the shape that was wrong. Recorded so this change is not mistaken for
        closing a hole that was open.
        """
        for payments in (0, {"nano_1": "5"}):
            with self.subTest(payments=payments):
                self._write_ledger(
                    {"mandate_hash": self.hash, "spent_raw": "0", "payments": payments}
                )
                with self.assertRaises(MandateRefused) as caught:
                    self._guard()._read(self.hash)
                self.assertEqual(caught.exception.reason, "ledger_corrupt")

    def test_a_payment_entry_that_is_not_an_object_is_refused(self):
        self._write_ledger(
            {"mandate_hash": self.hash, "spent_raw": "5", "payments": ["5"]}
        )
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertEqual(caught.exception.reason, "ledger_corrupt")

    # ------------------------------------------------------- a float in the file

    def test_a_float_amount_raw_is_refused_not_truncated(self):
        """`int(1.9)` is 1, which agreed with `spent_raw` and was accepted."""
        self._write_ledger(
            {"mandate_hash": self.hash, "spent_raw": "1", "payments": [{"amount_raw": 1.9}]}
        )
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertEqual(caught.exception.reason, "ledger_corrupt")

    def test_a_float_spent_raw_is_refused(self):
        self._write_ledger(
            {"mandate_hash": self.hash, "spent_raw": 1.0, "payments": [{"amount_raw": "1"}]}
        )
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertEqual(caught.exception.reason, "ledger_corrupt")

    def test_an_integer_amount_raw_is_refused_as_not_a_decimal_string(self):
        """The ledger this module writes holds strings; a bare JSON integer loses
        precision above 2**53, which is below one XNO."""
        self._write_ledger(
            {"mandate_hash": self.hash, "spent_raw": "1", "payments": [{"amount_raw": 1}]}
        )
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertEqual(caught.exception.reason, "ledger_corrupt")

    def test_a_non_ascii_digit_total_is_refused(self):
        """`"١".isdigit()` is True and `int()` reads it as 1."""
        self._write_ledger(
            {"mandate_hash": self.hash, "spent_raw": "١", "payments": [{"amount_raw": "1"}]}
        )
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertEqual(caught.exception.reason, "ledger_corrupt")

    def test_a_ledger_that_is_not_an_object_is_refused(self):
        self._write_ledger([{"amount_raw": "1"}])
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertIn(caught.exception.reason, ("ledger_corrupt", "ledger_unreadable"))

    # ------------------------------------------------------------- the controls

    def test_an_empty_list_payments_is_still_a_healthy_ledger(self):
        self._write_ledger({"mandate_hash": self.hash, "spent_raw": "0", "payments": []})
        data = self._guard()._read(self.hash)
        self.assertEqual(data["spent_raw"], "0")
        self.assertEqual(
            self._guard().check(self.payee, 10 ** 27)["amount_raw"],
            "1000000000000000000000000000",
        )

    def test_a_ledger_this_module_wrote_still_reads_and_spends(self):
        """The whole point: nothing changes for a real ledger."""
        guard = self._guard()
        guard.spend(self.payee, 10 ** 27, self._send)
        guard.spend(self.payee, 2 * 10 ** 27, self._send)
        with open(self.ledger_path, encoding="utf-8") as fh:
            written = json.load(fh)
        self.assertEqual(written["spent_raw"], "3000000000000000000000000000")
        self.assertEqual(len(written["payments"]), 2)
        # and a fresh guard reads it back without complaint
        status = self._guard().status()
        self.assertEqual(status["spent_raw"], "3000000000000000000000000000")
        self.assertEqual(status["payments"], 2)
        self.assertTrue(status["valid"])

    def test_a_mismatched_total_is_still_refused(self):
        self._write_ledger(
            {"mandate_hash": self.hash, "spent_raw": "9", "payments": [{"amount_raw": "1"}]}
        )
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertEqual(caught.exception.reason, "ledger_corrupt")

    def test_another_mandates_ledger_is_still_refused_with_its_own_reason(self):
        self._write_ledger({"mandate_hash": "00" * 32, "spent_raw": "0", "payments": []})
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertEqual(caught.exception.reason, "ledger_mismatch")

    def test_an_unreadable_ledger_is_still_ledger_unreadable(self):
        with open(self.ledger_path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with self.assertRaises(MandateRefused) as caught:
            self._guard()._read(self.hash)
        self.assertEqual(caught.exception.reason, "ledger_unreadable")

    def test_no_ledger_file_is_still_a_fresh_ledger(self):
        guard = self._guard()
        self.assertFalse(os.path.exists(self.ledger_path))
        self.assertEqual(guard._read(self.hash), {
            "mandate_hash": self.hash, "spent_raw": "0", "payments": [],
        })


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
