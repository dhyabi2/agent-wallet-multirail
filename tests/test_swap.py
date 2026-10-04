"""The USDC -> XNO -> seller hop: pursekeeper.dev's rank 3.

Nothing here touches the network. The provider's one seam is a transport
callable, so every request this module would make is asserted against the URLs
and parameters of the published ``nanswap`` npm client 1.0.3, and every response
it would parse is handed over as a literal.
"""
import json
import unittest

from agent_wallet_multirail import mandate
from agent_wallet_multirail.swap import (
    CANONICAL_NANO_NETWORK,
    DEFAULT_SLIPPAGE_BPS,
    MICRO_PER_USDC,
    NANSWAP_API_KEY_HEADER,
    NanoQuote,
    NanswapProvider,
    SwapEstimate,
    SwapHopResult,
    SwapLimits,
    SwapOrder,
    SwapPlan,
    SwapRefused,
    micro_to_usdc,
    pay_nano_quote_from_usdc,
    plan_swap_hop,
    usdc_to_micro,
)

RAW = 10 ** 30

# Two distinct, checksum-valid mainnet accounts.
SELLER = "nano_1111111111111111111111111111111111111111111111111111hifc8npp"
AGENT = "nano_3t6k35gi95xu6tergt6p69ck76ogmitsa8mnijtpxm9fkcm736xtoncuohr3"


def seed_address(index: int) -> str:
    key = mandate.private_key_from_seed(bytes([index]) * 32, 0)
    return mandate.address_from_public_key(mandate.public_key_from_private(key))


class FakeRail:
    """Stands in for NanoRail.pay_to and records exactly what it was asked."""

    def __init__(self, settled=True):
        self.calls = []
        self._settled = settled

    def pay_to(self, payee, amount_raw, ref=""):
        self.calls.append({"payee": payee, "amount_raw": amount_raw, "ref": ref})
        return type("S", (), {"settled": self._settled, "tx_ref": "block-1"})()


class RecordingProvider:
    """A provider whose answers are literals, so no network is involved."""

    def __init__(self, to_amount="1.5", limits=None, order=None, fail_create=None):
        self.to_amount = to_amount
        self._limits = limits
        self._order = order
        self.fail_create = fail_create
        self.created = []
        self.estimates = []

    def estimate(self, *, from_currency, from_network, from_amount_micro,
                 to_currency="XNO", to_network=""):
        self.estimates.append((from_currency, from_network, from_amount_micro))
        return SwapEstimate(from_currency=from_currency, from_network=from_network,
                            to_currency=to_currency, to_network=to_network,
                            from_amount_micro=from_amount_micro, to_amount=self.to_amount)

    def limits(self, *, from_currency, from_network, to_currency="XNO", to_network=""):
        return self._limits

    def create_order(self, plan):
        if self.fail_create:
            raise self.fail_create
        self.created.append(plan)
        return self._order or SwapOrder(
            order_id="ord-1", pay_in_address="0xpayin",
            from_amount_micro=plan.from_amount_micro, to_address=plan.own_address,
            expected_to_amount=self.to_amount)


def an_estimate(to_amount="1.5", from_micro=2 * MICRO_PER_USDC, to_currency="XNO"):
    return SwapEstimate(from_currency="USDC", from_network="BSC", to_currency=to_currency,
                        to_network="", from_amount_micro=from_micro, to_amount=to_amount)


def a_quote(amount_raw=RAW, pay_to=SELLER, network=CANONICAL_NANO_NETWORK):
    return NanoQuote(pay_to=pay_to, amount_raw=amount_raw, network=network)


def a_plan(**over):
    args = dict(quote=a_quote(), own_address=AGENT, estimate=an_estimate(),
                max_from_amount="5", order_key="k1")
    args.update(over)
    estimate = args.pop("estimate")
    return plan_swap_hop(args.pop("quote"), args.pop("own_address"), estimate, **args)


# ------------------------------------------------------------------- amounts


class UsdcAmounts(unittest.TestCase):
    def test_exact_decimal_strings_convert_to_integer_micro(self):
        self.assertEqual(usdc_to_micro("1"), 1_000_000)
        self.assertEqual(usdc_to_micro("0.000001"), 1)
        self.assertEqual(usdc_to_micro("1.5"), 1_500_000)
        self.assertEqual(usdc_to_micro(".5"), 500_000)
        self.assertEqual(usdc_to_micro("12.345678"), 12_345_678)

    def test_round_trips(self):
        for text in ("1", "0.000001", "1.5", "12.345678", "1000000"):
            self.assertEqual(micro_to_usdc(usdc_to_micro(text)), text, text)

    def test_a_float_is_refused_outright(self):
        with self.assertRaises(SwapRefused) as caught:
            usdc_to_micro(1.5)
        self.assertEqual(caught.exception.reason, "invalid_amount")

    def test_a_bool_is_not_a_number_here(self):
        with self.assertRaises(SwapRefused):
            usdc_to_micro(True)

    def test_more_than_six_decimals_is_refused_rather_than_rounded(self):
        with self.assertRaises(SwapRefused) as caught:
            usdc_to_micro("1.0000001")
        self.assertEqual(caught.exception.reason, "invalid_amount")

    def test_a_non_ascii_digit_is_refused(self):
        # str.isdigit() is true for every Unicode digit. A check without
        # isascii() accepts what a JavaScript /^\d+$/ peer refuses, and the two
        # sides then disagree about whether an amount is valid at all.
        for text in ("٣", "²", "٣.5", "1.٣"):
            with self.assertRaises(SwapRefused, msg=text):
                usdc_to_micro(text)

    def test_zero_is_refused(self):
        with self.assertRaises(SwapRefused):
            usdc_to_micro("0")

    def test_whitespace_and_signs_are_refused(self):
        for text in ("-1", "+1", "1e6", "", " ", "1,5"):
            with self.assertRaises(SwapRefused, msg=text):
                usdc_to_micro(text)


# --------------------------------------------------------------------- quote


class Quote(unittest.TestCase):
    def test_a_quote_normalises_its_payee_and_keeps_raw_exact(self):
        quote = a_quote(amount_raw="1000000000000000000000000000001")
        self.assertEqual(quote.amount_raw, 10 ** 30 + 1)
        self.assertEqual(quote.pay_to, mandate.normalise_address(SELLER))

    def test_a_float_amount_is_refused(self):
        with self.assertRaises(SwapRefused) as caught:
            a_quote(amount_raw=1.0)
        self.assertEqual(caught.exception.reason, "invalid_amount")

    def test_a_bad_checksum_payee_is_refused(self):
        bad = SELLER[:-1] + ("a" if SELLER[-1] != "a" else "b")
        with self.assertRaises(SwapRefused) as caught:
            a_quote(pay_to=bad)
        self.assertEqual(caught.exception.reason, "invalid_payee")

    def test_nano_mainnet_with_a_hyphen_is_read_and_the_colon_is_emitted(self):
        self.assertEqual(a_quote(network="nano-mainnet").network, CANONICAL_NANO_NETWORK)

    def test_a_bare_family_name_is_not_assumed_to_be_mainnet(self):
        for name in ("nano", "xno", "NANO"):
            with self.assertRaises(SwapRefused, msg=name) as caught:
                a_quote(network=name)
            self.assertEqual(caught.exception.reason, "network_unspecified")

    def test_a_test_network_is_a_different_refusal_from_not_nano(self):
        self.assertEqual(
            self.assertRaises_reason(lambda: a_quote(network="nano:testnet")), "not_mainnet")
        self.assertEqual(
            self.assertRaises_reason(lambda: a_quote(network="base")), "not_nano")

    def assertRaises_reason(self, fn):
        with self.assertRaises(SwapRefused) as caught:
            fn()
        return caught.exception.reason

    def test_an_x402_entry_is_read_under_either_price_field_name(self):
        for name in ("amount", "maxAmountRequired"):
            quote = NanoQuote.from_x402_entry(
                {"payTo": SELLER, name: str(RAW), "network": "nano:mainnet"})
            self.assertEqual(quote.amount_raw, RAW)

    def test_an_entry_carrying_two_different_prices_is_refused_not_picked(self):
        with self.assertRaises(SwapRefused) as caught:
            NanoQuote.from_x402_entry({"payTo": SELLER, "amount": str(RAW),
                                       "maxAmountRequired": str(RAW * 2)})
        self.assertEqual(caught.exception.reason, "contradictory_price")

    def test_an_entry_carrying_the_same_price_under_both_names_is_fine(self):
        # This is what dual-rail emits on purpose: one integer, both names.
        quote = NanoQuote.from_x402_entry({"payTo": SELLER, "amount": str(RAW),
                                           "maxAmountRequired": str(RAW)})
        self.assertEqual(quote.amount_raw, RAW)

    def test_an_entry_with_no_price_or_no_payee_is_refused(self):
        self.assertEqual(self.assertRaises_reason(
            lambda: NanoQuote.from_x402_entry({"payTo": SELLER})), "invalid_quote")
        self.assertEqual(self.assertRaises_reason(
            lambda: NanoQuote.from_x402_entry({"amount": str(RAW)})), "invalid_quote")

    def test_a_decimal_xno_price_in_an_entry_is_refused_not_rescaled(self):
        # "0.0001" is main's old bug (dhyabi2/dual-rail#2). An entry carrying it
        # is not silently read as 10**26 raw.
        with self.assertRaises(SwapRefused):
            NanoQuote.from_x402_entry({"payTo": SELLER, "amount": "0.0001"})


# ---------------------------------------------------------------- the plan


class Planning(unittest.TestCase):
    def test_a_sound_hop_plans(self):
        plan = a_plan()
        self.assertEqual(plan.quote.amount_raw, RAW)
        self.assertEqual(plan.own_address, mandate.normalise_address(AGENT))
        self.assertEqual(plan.from_amount, "2")
        self.assertEqual(plan.estimated_to_amount_raw, 15 * 10 ** 29)
        self.assertEqual(plan.required_to_amount_raw, RAW * 101 // 100)
        self.assertGreater(plan.headroom_raw, 0)

    def test_swapping_straight_to_the_seller_is_refused(self):
        # The shortcut that looks like it saves a leg: the provider would pay
        # out what the swap yielded, from its own account - not the quote's
        # exact raw, and not a block bound to this agent's order.
        with self.assertRaises(SwapRefused) as caught:
            a_plan(own_address=SELLER)
        self.assertEqual(caught.exception.reason, "swap_destination_is_payee")

    def test_the_payee_check_is_on_the_normalised_account_not_the_spelling(self):
        with self.assertRaises(SwapRefused) as caught:
            a_plan(own_address=SELLER.replace("nano_", "xrb_"))
        self.assertEqual(caught.exception.reason, "swap_destination_is_payee")

    def test_an_estimate_short_of_the_quote_is_refused_before_the_usdc_goes(self):
        with self.assertRaises(SwapRefused) as caught:
            a_plan(estimate=an_estimate(to_amount="0.9"))
        self.assertEqual(caught.exception.reason, "estimate_below_quote")

    def test_an_estimate_exactly_equal_to_the_quote_is_still_refused(self):
        # x402 "exact" means exact; an estimate is not a guarantee. Landing one
        # raw short leaves the USDC spent and the payment unmakeable, so the
        # bare quote is not enough.
        with self.assertRaises(SwapRefused) as caught:
            a_plan(estimate=an_estimate(to_amount="1"))
        self.assertEqual(caught.exception.reason, "estimate_below_quote")

    def test_the_default_headroom_is_the_one_percent_the_docs_claim(self):
        self.assertEqual(DEFAULT_SLIPPAGE_BPS, 100)
        self.assertEqual(a_plan().slippage_bps, DEFAULT_SLIPPAGE_BPS)
        self.assertEqual(a_plan().required_to_amount_raw, RAW * 101 // 100)

    def test_with_zero_headroom_asked_for_the_bare_quote_is_accepted(self):
        plan = a_plan(estimate=an_estimate(to_amount="1"), slippage_bps=0)
        self.assertEqual(plan.required_to_amount_raw, RAW)
        self.assertEqual(plan.headroom_raw, 0)

    def test_one_raw_short_of_the_requirement_is_refused(self):
        required = RAW * 101 // 100
        short = mandate.raw_to_xno(required - 1)
        with self.assertRaises(SwapRefused) as caught:
            a_plan(estimate=an_estimate(to_amount=short))
        self.assertEqual(caught.exception.reason, "estimate_below_quote")

    def test_exactly_the_requirement_is_accepted(self):
        required = RAW * 101 // 100
        plan = a_plan(estimate=an_estimate(to_amount=mandate.raw_to_xno(required)))
        self.assertEqual(plan.headroom_raw, 0)

    def test_the_headroom_is_rounded_up_so_it_never_vanishes(self):
        # 1 raw at 1bp: a floor would give back the bare quote, which is the
        # case the guard exists for.
        plan_required = plan_swap_hop(
            a_quote(amount_raw=1), AGENT, an_estimate(to_amount=mandate.raw_to_xno(2)),
            max_from_amount="5", order_key="k", slippage_bps=1).required_to_amount_raw
        self.assertEqual(plan_required, 2)

    def test_a_swap_over_the_cap_is_refused(self):
        with self.assertRaises(SwapRefused) as caught:
            a_plan(max_from_amount="1")
        self.assertEqual(caught.exception.reason, "exceeds_cap")

    def test_a_swap_exactly_at_the_cap_is_allowed(self):
        self.assertEqual(a_plan(max_from_amount="2").from_amount, "2")

    def test_the_providers_minimum_and_maximum_are_honoured(self):
        with self.assertRaises(SwapRefused) as caught:
            a_plan(limits=SwapLimits(min_from_micro=5 * MICRO_PER_USDC))
        self.assertEqual(caught.exception.reason, "below_provider_minimum")
        with self.assertRaises(SwapRefused) as caught:
            a_plan(limits=SwapLimits(min_from_micro=1, max_from_micro=MICRO_PER_USDC))
        self.assertEqual(caught.exception.reason, "above_provider_maximum")

    def test_an_estimate_for_another_pair_is_refused(self):
        with self.assertRaises(SwapRefused) as caught:
            a_plan(estimate=an_estimate(to_currency="BAN"))
        self.assertEqual(caught.exception.reason, "estimate_wrong_pair")

    def test_an_empty_estimated_output_is_not_read_as_zero(self):
        # mandate.xno_to_raw("") returned 0 raw: "" partitions to a whole part
        # of "" which was defaulted to "0". A string naming no amount is not
        # the number zero, and it must not reach a comparison as one.
        with self.assertRaises(SwapRefused) as caught:
            a_plan(estimate=an_estimate(to_amount=""))
        self.assertEqual(caught.exception.reason, "estimate_unparsable")
        with self.assertRaises(SwapRefused) as caught:
            a_plan(estimate=an_estimate(to_amount="   "))
        self.assertEqual(caught.exception.reason, "estimate_unparsable")

    def test_an_unparsable_estimated_output_is_refused_not_coerced(self):
        for bad in ("about 1.5", "1.5 XNO", "", "1.5e0", "   "):
            with self.assertRaises(SwapRefused, msg=bad) as caught:
                a_plan(estimate=an_estimate(to_amount=bad))
            self.assertEqual(caught.exception.reason, "estimate_unparsable")

    def test_an_estimated_output_with_31_decimals_is_refused(self):
        with self.assertRaises(SwapRefused) as caught:
            a_plan(estimate=an_estimate(to_amount="1." + "0" * 31))
        self.assertEqual(caught.exception.reason, "estimate_unparsable")

    def test_a_nonsense_slippage_is_refused(self):
        for bps in (-1, 10_000, 20_000, 1.5, True, "100"):
            with self.assertRaises(SwapRefused, msg=repr(bps)) as caught:
                a_plan(slippage_bps=bps)
            self.assertEqual(caught.exception.reason, "invalid_slippage")

    def test_a_quote_whose_headroom_would_exceed_the_nano_ceiling_is_refused(self):
        with self.assertRaises(SwapRefused) as caught:
            plan_swap_hop(a_quote(amount_raw=mandate.MAX_RAW), AGENT,
                          an_estimate(to_amount="1"), max_from_amount="5", order_key="k")
        self.assertEqual(caught.exception.reason, "amount_above_ceiling")

    def test_an_empty_order_key_is_refused_because_retry_depends_on_it(self):
        for key in ("", "   "):
            with self.assertRaises(SwapRefused, msg=repr(key)) as caught:
                a_plan(order_key=key)
            self.assertEqual(caught.exception.reason, "invalid_order_key")

    def test_a_bad_own_address_is_refused(self):
        with self.assertRaises(SwapRefused) as caught:
            a_plan(own_address="nano_notanaddress")
        self.assertEqual(caught.exception.reason, "invalid_own_address")

    def test_planning_moves_no_money_and_calls_nothing(self):
        provider = RecordingProvider()
        a_plan()
        self.assertEqual(provider.created, [])

    def test_the_plan_renders_every_amount_as_a_string(self):
        rendered = json.loads(json.dumps(a_plan().as_dict()))
        for key in ("amount_raw", "estimated_to_amount_raw", "required_to_amount_raw",
                    "headroom_raw"):
            self.assertIsInstance(rendered[key], str, key)
        self.assertEqual(rendered["network"], CANONICAL_NANO_NETWORK)


# ------------------------------------------------------------------- the hop


class TheHop(unittest.TestCase):
    def setUp(self):
        self.provider = RecordingProvider()
        self.rail = FakeRail()
        self.log = {}

    def hop(self, **over):
        args = dict(quote=a_quote(), own_address=AGENT, provider=self.provider,
                    from_currency="USDC", from_network="BSC", from_amount="2",
                    max_from_amount="5", order_key="k1", rail=self.rail,
                    order_log=self.log)
        args.update(over)
        quote = args.pop("quote")
        own = args.pop("own_address")
        provider = args.pop("provider")
        return pay_nano_quote_from_usdc(quote, own, provider, **args)

    def test_by_default_it_plans_and_spends_nothing(self):
        result = self.hop()
        self.assertIsInstance(result, SwapPlan)
        self.assertEqual(self.provider.created, [])
        self.assertEqual(self.rail.calls, [])
        self.assertEqual(self.log, {})

    def test_executing_without_an_order_log_is_refused(self):
        with self.assertRaises(SwapRefused) as caught:
            self.hop(execute=True, order_log=None, balance_raw=lambda: 0)
        self.assertEqual(caught.exception.reason, "no_order_log")
        self.assertEqual(self.provider.created, [])

    def test_executing_without_a_balance_source_is_refused(self):
        with self.assertRaises(SwapRefused) as caught:
            self.hop(execute=True)
        self.assertEqual(caught.exception.reason, "no_balance_source")
        self.assertEqual(self.provider.created, [])

    def test_executing_without_a_rail_is_refused(self):
        with self.assertRaises(SwapRefused) as caught:
            self.hop(execute=True, rail=None, balance_raw=lambda: 0)
        self.assertEqual(caught.exception.reason, "no_rail")
        self.assertEqual(self.provider.created, [])

    def test_the_first_call_creates_the_order_and_sends_nothing_yet(self):
        with self.assertRaises(SwapRefused) as caught:
            self.hop(execute=True, balance_raw=lambda: 0)
        self.assertEqual(caught.exception.reason, "swap_not_received_yet")
        self.assertEqual(len(self.provider.created), 1)
        self.assertEqual(self.rail.calls, [])
        self.assertIn("k1", self.log)

    def test_retrying_with_the_same_key_does_not_buy_a_second_swap(self):
        balances = [0, 0, 0]
        with self.assertRaises(SwapRefused):
            self.hop(execute=True, balance_raw=lambda: balances.pop(0))
        with self.assertRaises(SwapRefused):
            self.hop(execute=True, balance_raw=lambda: balances.pop(0))
        self.assertEqual(len(self.provider.created), 1)
        self.assertEqual(self.rail.calls, [])

    def test_once_the_swap_lands_the_quotes_exact_raw_is_sent(self):
        # The swap over-delivers, as it is planned to. The seller still gets
        # exactly the quote; the surplus stays in the agent's own account.
        delivered = 15 * 10 ** 29
        balances = iter([0, delivered])
        result = self.hop(execute=True, balance_raw=lambda: next(balances))
        self.assertIsInstance(result, SwapHopResult)
        self.assertEqual(result.received_raw, delivered)
        self.assertEqual(self.rail.calls, [{"payee": mandate.normalise_address(SELLER),
                                            "amount_raw": RAW, "ref": "k1"}])
        self.assertTrue(result.settled)

    def test_a_retry_after_a_successful_send_does_not_pay_the_seller_twice(self):
        # The hop is planned to over-deliver, so after a send the agent's own
        # account still holds more than the quote. Without the recorded attempt
        # the retry read that surplus as a swap that had just landed and sent
        # the quote a second time: 2 XNO out the door for a 1 XNO quote.
        delivered = 3 * RAW
        state = {"balance": 0}
        provider = RecordingProvider(to_amount="3")
        with self.assertRaises(SwapRefused):
            self.hop(execute=True, provider=provider, balance_raw=lambda: state["balance"])
        state["balance"] = delivered
        self.hop(execute=True, provider=provider, balance_raw=lambda: state["balance"])
        state["balance"] -= RAW                      # the send left the account
        with self.assertRaises(SwapRefused) as caught:
            self.hop(execute=True, provider=provider, balance_raw=lambda: state["balance"])
        self.assertEqual(caught.exception.reason, "send_already_attempted")
        self.assertEqual(len(self.rail.calls), 1)
        self.assertEqual(sum(c["amount_raw"] for c in self.rail.calls), RAW)
        self.assertEqual(len(provider.created), 1)

    def test_the_attempt_is_recorded_before_the_send_so_a_crash_mid_send_is_refused(self):
        # A send that raised may still have moved the money. Under-counting an
        # unknown outcome is how a quote gets paid twice, so it is refused too.
        class Exploding:
            def pay_to(self, payee, amount_raw, ref=""):
                raise RuntimeError("the node went away mid-send")

        provider = RecordingProvider(to_amount="3")
        state = {"balance": 0}
        balance = lambda: state["balance"]
        with self.assertRaises(SwapRefused):
            self.hop(execute=True, provider=provider, balance_raw=balance)
        state["balance"] = 3 * RAW
        with self.assertRaises(RuntimeError):
            self.hop(execute=True, provider=provider, rail=Exploding(), balance_raw=balance)
        self.assertEqual(self.log["k1"]["send_attempted"]["outcome"], "unknown")
        with self.assertRaises(SwapRefused) as caught:
            self.hop(execute=True, provider=provider, balance_raw=balance)
        self.assertEqual(caught.exception.reason, "send_already_attempted")
        self.assertEqual(self.rail.calls, [])

    def test_the_recorded_attempt_names_the_payee_amount_and_outcome(self):
        provider = RecordingProvider(to_amount="3")
        state = {"balance": 0}
        balance = lambda: state["balance"]
        with self.assertRaises(SwapRefused):
            self.hop(execute=True, provider=provider, balance_raw=balance)
        state["balance"] = 3 * RAW
        self.hop(execute=True, provider=provider, balance_raw=balance)
        attempt = self.log["k1"]["send_attempted"]
        self.assertEqual(attempt["pay_to"], mandate.normalise_address(SELLER))
        self.assertEqual(attempt["amount_raw"], str(RAW))   # a string, like every other amount
        self.assertEqual(attempt["outcome"], "settled")
        self.assertEqual(attempt["ref"], "k1")

    def test_a_send_that_did_not_settle_is_recorded_as_such_and_still_not_retried(self):
        provider = RecordingProvider(to_amount="3")
        state = {"balance": 0}
        balance = lambda: state["balance"]
        with self.assertRaises(SwapRefused):
            self.hop(execute=True, provider=provider, balance_raw=balance)
        state["balance"] = 3 * RAW
        result = self.hop(execute=True, provider=provider, rail=FakeRail(settled=False),
                          balance_raw=balance)
        self.assertFalse(result.settled)
        self.assertEqual(self.log["k1"]["send_attempted"]["outcome"], "not_settled")
        with self.assertRaises(SwapRefused) as caught:
            self.hop(execute=True, provider=provider, balance_raw=balance)
        self.assertEqual(caught.exception.reason, "send_already_attempted")

    def test_a_first_call_whose_swap_has_already_landed_still_sends(self):
        # The control: the refusal must not cost a hop its one legitimate send.
        balances = iter([0, 15 * 10 ** 29])
        result = self.hop(execute=True, balance_raw=lambda: next(balances))
        self.assertIsInstance(result, SwapHopResult)
        self.assertEqual(len(self.rail.calls), 1)

    def test_a_shortfall_of_one_raw_sends_nothing(self):
        balances = iter([0, RAW - 1])
        with self.assertRaises(SwapRefused) as caught:
            self.hop(execute=True, balance_raw=lambda: next(balances))
        self.assertEqual(caught.exception.reason, "swap_not_received_yet")
        self.assertEqual(self.rail.calls, [])

    def test_the_received_amount_is_measured_as_a_delta_not_the_balance(self):
        # An account that already held XNO must not have its existing balance
        # counted as the swap's delivery.
        balances = iter([5 * RAW, 5 * RAW])
        with self.assertRaises(SwapRefused) as caught:
            self.hop(execute=True, balance_raw=lambda: next(balances))
        self.assertEqual(caught.exception.reason, "swap_not_received_yet")
        self.assertEqual(self.rail.calls, [])

    def test_a_float_balance_is_refused(self):
        with self.assertRaises(SwapRefused) as caught:
            self.hop(execute=True, balance_raw=lambda: 1.0)
        self.assertEqual(caught.exception.reason, "balance_not_an_integer")
        self.assertEqual(self.provider.created, [])

    def test_reusing_an_order_key_for_a_different_quote_is_refused(self):
        balances = [0, 0]
        with self.assertRaises(SwapRefused):
            self.hop(execute=True, balance_raw=lambda: balances.pop(0))
        other = a_quote(pay_to=seed_address(7))
        with self.assertRaises(SwapRefused) as caught:
            self.hop(quote=other, execute=True, balance_raw=lambda: balances.pop(0))
        self.assertEqual(caught.exception.reason, "order_key_reused")
        self.assertEqual(len(self.provider.created), 1)

    def test_the_shortcut_is_refused_before_the_provider_is_called_at_all(self):
        # A hop that is already refused must not quote first: the call is
        # wasted, and a provider log then shows a hop that never existed.
        with self.assertRaises(SwapRefused) as caught:
            self.hop(own_address=SELLER, execute=True, balance_raw=lambda: 0)
        self.assertEqual(caught.exception.reason, "swap_destination_is_payee")
        self.assertEqual(self.provider.estimates, [])
        self.assertEqual(self.provider.created, [])

    def test_the_providers_limits_are_fetched_and_applied(self):
        self.provider._limits = SwapLimits(min_from_micro=10 * MICRO_PER_USDC)
        with self.assertRaises(SwapRefused) as caught:
            self.hop()
        self.assertEqual(caught.exception.reason, "below_provider_minimum")

    def test_limits_can_be_skipped(self):
        self.provider._limits = SwapLimits(min_from_micro=10 * MICRO_PER_USDC)
        self.assertIsInstance(self.hop(check_limits=False), SwapPlan)

    def test_a_cap_over_the_estimate_input_is_what_bounds_the_spend(self):
        with self.assertRaises(SwapRefused) as caught:
            self.hop(from_amount="2", max_from_amount="1.999999")
        self.assertEqual(caught.exception.reason, "exceeds_cap")


# -------------------------------------------------------------- the provider


class Nanswap(unittest.TestCase):
    """Requests are asserted against the published npm client 1.0.3."""

    def setUp(self):
        self.seen = []

    def transport(self, payload):
        def call(method, url, headers, body):
            self.seen.append({"method": method, "url": url, "headers": dict(headers),
                              "body": body})
            return payload
        return call

    def test_the_estimate_request_matches_the_published_client(self):
        provider = NanswapProvider(transport=self.transport({"amountTo": "1.5"}))
        estimate = provider.estimate(from_currency="USDC", from_network="BSC",
                                     from_amount_micro=2 * MICRO_PER_USDC)
        self.assertEqual(estimate.to_amount_raw, 15 * 10 ** 29)
        call = self.seen[0]
        self.assertEqual(call["method"], "GET")
        self.assertTrue(call["url"].startswith(
            "https://api.nanswap.com/v1/get-estimate-partner?"), call["url"])
        for part in ("from=USDC", "to=XNO", "amount=2", "fromNetwork=BSC", "toNetwork="):
            self.assertIn(part, call["url"])
        self.assertIsNone(call["body"])

    def test_the_limits_request_matches_the_published_client(self):
        provider = NanswapProvider(transport=self.transport({"min": "1", "max": "1000"}))
        limits = provider.limits(from_currency="USDC", from_network="BSC")
        self.assertEqual(limits.min_from_micro, MICRO_PER_USDC)
        self.assertEqual(limits.max_from_micro, 1000 * MICRO_PER_USDC)
        self.assertIn("/get-limits-partner?", self.seen[0]["url"])

    def test_limits_without_a_maximum_is_read_as_no_maximum(self):
        provider = NanswapProvider(transport=self.transport({"min": "1"}))
        self.assertIsNone(provider.limits(from_currency="USDC", from_network="BSC").max_from_micro)

    def test_creating_an_order_sends_the_api_key_in_the_documented_header(self):
        plan = a_plan()
        payload = {"id": "ord-9", "payinAddress": "0xabc",
                   "payoutAddress": mandate.normalise_address(AGENT),
                   "expectedAmountTo": "1.5", "expectedAmountFrom": "2"}
        provider = NanswapProvider(api_key="KEY", transport=self.transport(payload))
        order = provider.create_order(plan)
        self.assertEqual(order.order_id, "ord-9")
        self.assertEqual(order.pay_in_address, "0xabc")
        call = self.seen[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "https://api.nanswap.com/v1/create-order-partner")
        self.assertEqual(call["headers"][NANSWAP_API_KEY_HEADER], "KEY")
        self.assertEqual(call["body"]["toAddress"], mandate.normalise_address(AGENT))
        self.assertEqual(call["body"]["to"], "XNO")
        self.assertEqual(call["body"]["amount"], "2")

    def test_creating_an_order_without_a_key_is_refused_before_any_request(self):
        provider = NanswapProvider(transport=self.transport({}))
        with self.assertRaises(SwapRefused) as caught:
            provider.create_order(a_plan())
        self.assertEqual(caught.exception.reason, "no_api_key")
        self.assertEqual(self.seen, [])

    def test_an_order_paying_out_somewhere_else_is_refused(self):
        payload = {"id": "ord-9", "payinAddress": "0xabc",
                   "payoutAddress": SELLER,  # not the plan's own_address
                   "expectedAmountTo": "1.5", "expectedAmountFrom": "2"}
        provider = NanswapProvider(api_key="KEY", transport=self.transport(payload))
        with self.assertRaises(SwapRefused) as caught:
            provider.create_order(a_plan())
        self.assertEqual(caught.exception.reason, "order_destination_changed")

    def test_a_missing_field_is_refused_rather_than_defaulted(self):
        provider = NanswapProvider(transport=self.transport({"nope": 1}))
        with self.assertRaises(SwapRefused) as caught:
            provider.estimate(from_currency="USDC", from_network="BSC", from_amount_micro=1)
        self.assertEqual(caught.exception.reason, "provider_response_unrecognised")
        self.assertIn("amountTo", str(caught.exception))

    def test_a_response_that_is_not_an_object_is_refused(self):
        provider = NanswapProvider(transport=self.transport(["1.5"]))
        with self.assertRaises(SwapRefused) as caught:
            provider.estimate(from_currency="USDC", from_network="BSC", from_amount_micro=1)
        self.assertEqual(caught.exception.reason, "provider_response_unrecognised")

    def test_an_amount_that_arrives_as_a_json_number_is_refused(self):
        # json.loads gives a float, which cannot hold 30 decimals, so the value
        # has already lost precision before this module sees it.
        provider = NanswapProvider(transport=self.transport({"amountTo": 1.5}))
        with self.assertRaises(SwapRefused) as caught:
            provider.estimate(from_currency="USDC", from_network="BSC", from_amount_micro=1)
        self.assertEqual(caught.exception.reason, "provider_amount_not_a_string")

    def test_a_boolean_is_not_accepted_where_a_string_is_wanted(self):
        provider = NanswapProvider(transport=self.transport({"amountTo": True}))
        with self.assertRaises(SwapRefused) as caught:
            provider.estimate(from_currency="USDC", from_network="BSC", from_amount_micro=1)
        self.assertEqual(caught.exception.reason, "provider_response_unrecognised")

    def test_reading_an_order_back_uses_the_partner_endpoint(self):
        payload = {"id": "ord-9", "payinAddress": "0xabc", "payoutAddress": AGENT,
                   "expectedAmountTo": "1.5", "expectedAmountFrom": "2", "status": "sending"}
        provider = NanswapProvider(transport=self.transport(payload))
        order = provider.order("ord-9")
        self.assertEqual(order.status, "sending")
        self.assertIn("/get-order-partner?id=ord-9", self.seen[0]["url"])


# ----------------------------------------------------- end to end, no network


class EndToEnd(unittest.TestCase):
    def test_a_whole_hop_through_the_nanswap_provider_and_the_real_rail(self):
        from agent_wallet_multirail import NanoRail

        sent = {}

        def rpc(request):
            sent.update(request)
            return {"block": "BLOCK1", "confirmed": True}

        responses = iter([
            {"min": "1", "max": "1000"},
            {"amountTo": "1.500000000000000000000000000001"},
            {"id": "ord-42", "payinAddress": "0xpayin",
             "payoutAddress": mandate.normalise_address(AGENT),
             "expectedAmountTo": "1.5", "expectedAmountFrom": "2"},
        ])
        provider = NanswapProvider(api_key="KEY",
                                   transport=lambda m, u, h, b: next(responses))
        quote = NanoQuote.from_x402_entry(
            {"payTo": SELLER, "amount": str(RAW), "maxAmountRequired": str(RAW),
             "network": "nano-mainnet"})
        log = {}
        balances = iter([0, 15 * 10 ** 29])
        result = pay_nano_quote_from_usdc(
            quote, AGENT, provider, from_currency="USDC", from_network="BSC",
            from_amount="2", max_from_amount="5", order_key="order-42",
            rail=NanoRail(rpc=rpc), balance_raw=lambda: next(balances),
            order_log=log, execute=True)

        self.assertTrue(result.settled)
        self.assertEqual(result.order.order_id, "ord-42")
        # The seller is paid the quote's exact raw, as an integer string.
        self.assertEqual(sent["destination"], mandate.normalise_address(SELLER))
        self.assertEqual(sent["amount_raw"], str(RAW))
        self.assertEqual(log["order-42"]["order"].order_id, "ord-42")


if __name__ == "__main__":
    unittest.main()
