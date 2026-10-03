"""An XNO amount string that names no amount is not the number zero.

``xno_to_raw("")`` returned ``0``: the empty string partitions to a whole part
of ``""``, which the function defaulted to ``"0"``. Its only caller in this
package wraps it in ``parse_raw``, which refuses a non-positive amount, so the
CLI was never wrong - but any new caller that compares the result against a
required amount would read "no amount given" as "zero XNO".
"""
import unittest

from agent_wallet_multirail import mandate


class EmptyXnoAmounts(unittest.TestCase):
    def test_an_empty_amount_is_refused_not_read_as_zero(self):
        for text in ("", " ", "\t", "\n", "   "):
            with self.assertRaises(mandate.MandateRefused, msg=repr(text)) as caught:
                mandate.xno_to_raw(text)
            self.assertEqual(caught.exception.reason, "invalid_amount", repr(text))

    def test_a_real_zero_still_parses_to_zero(self):
        # "0" names an amount, and refusing it here would move where the CLI's
        # own refusal comes from. parse_raw is what rejects a non-positive one.
        self.assertEqual(mandate.xno_to_raw("0"), 0)
        self.assertEqual(mandate.xno_to_raw("0.0"), 0)

    def test_the_cli_amount_helper_still_refuses_both(self):
        for text in ("", "0"):
            with self.assertRaises(mandate.MandateRefused, msg=repr(text)):
                mandate._amount_arg(None, text, "cap")

    def test_ordinary_amounts_are_untouched(self):
        self.assertEqual(mandate.xno_to_raw("1"), 10 ** 30)
        self.assertEqual(mandate.xno_to_raw("0.000000000000000000000000000001"), 1)
