"""Pay a Nano (XNO) x402 quote with a wallet that holds only USDC.

pursekeeper.dev states the gap this closes in its own words: *"the next bet is a
swap-in-the-payment-flow (an agent with USDC pays a Nano seller through a
Nanswap-style hop)"*, because *"Nobody in the x402 buyer population holds
Nano"*. A seller can advertise an XNO price all day; an agent whose wallet holds
USDC cannot pay it.

The hop is three legs, and **only the middle one is a swap**:

    USDC  --(swap provider)-->  XNO in the agent's OWN wallet  --(send)-->  seller

The third leg is an ordinary feeless XNO send of the quote's *exact* raw amount,
made by ``NanoRail.pay_to`` under whatever operator mandate is already in force
(see ``mandate.py``). That split is the whole design, and the module refuses the
shortcut that collapses it -- see ``swap_destination_is_payee`` below.

Everything here is integer arithmetic. XNO carries 30 decimals, USDC 6; a float
holds neither, so amounts cross this module as integers (raw, and micro-USDC) or
as exact decimal strings, never as ``float``. ``parse_raw`` and ``xno_to_raw``
from ``mandate.py`` already refuse a float outright and are reused rather than
re-implemented.

Two honest limits, stated here because they bound what this module can promise:

1.  **No live call to a swap provider was ever made from the environment this
    was written in** -- ``api.nanswap.com`` answers 403 to CONNECT under the
    network policy there. The *requests* ``NanswapProvider`` builds are checked
    against the URLs, query parameters and header name in the published
    ``nanswap`` npm client 1.0.3 (the only shipped client; the PyPI package of
    the same name is an empty sdist that installs no module at all). The
    *responses* it parses are **not** verified against the live API, so every
    field is validated and anything unrecognised is **refused** rather than
    guessed at: see ``_field``. A provider whose shape differs is a refusal to
    fix, never a payment made on a misread number.
2.  **A swap is custodial for the duration of the hop.** USDC leaves the agent's
    control and arrives as XNO only if the provider performs. Nothing in this
    module, or anywhere else, makes that leg trustless; ``max_from_amount`` is
    the only real protection and it is required, not optional.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional

from .mandate import (
    MAX_RAW,
    MandateRefused,
    normalise_address,
    parse_raw,
    raw_to_xno,
    xno_to_raw,
)

__all__ = [
    "SwapRefused",
    "NanoQuote",
    "SwapEstimate",
    "SwapLimits",
    "SwapOrder",
    "SwapPlan",
    "SwapHopResult",
    "NanswapProvider",
    "plan_swap_hop",
    "pay_nano_quote_from_usdc",
    "usdc_to_micro",
    "micro_to_usdc",
    "MICRO_PER_USDC",
    "DEFAULT_SLIPPAGE_BPS",
    "CANONICAL_NANO_NETWORK",
]

# USDC (and USDT) carry 6 decimals on every chain they are issued on.
MICRO_PER_USDC = 10 ** 6

# A swap quote is an estimate; x402's "exact" scheme demands an exact amount.
# The default headroom is deliberately not zero: an estimate that lands one raw
# short leaves the USDC spent and the payment unmakeable. 1% is a starting
# point, not a measurement -- no live provider was reachable to measure one.
DEFAULT_SLIPPAGE_BPS = 100

# The one spelling an x402 v2 client will accept. `nano-mainnet` is legal under
# x402 v1 and refused by v2 (@x402/core 2.28.0 NetworkSchemaV2 wants a colon),
# so it is read on input and never emitted.
CANONICAL_NANO_NETWORK = "nano:mainnet"

_NANO_NETWORK_ALIASES = {
    "nano:mainnet": CANONICAL_NANO_NETWORK,
    "nano-mainnet": CANONICAL_NANO_NETWORK,
}

# x402 renamed the price field between protocol versions, so a Nano entry in the
# wild carries one name or the other. Both are read; see dhyabi2/dual-rail#2.
_AMOUNT_FIELDS = ("amount", "maxAmountRequired")


class SwapRefused(Exception):
    """The hop was refused before any money moved.

    ``reason`` is a stable machine-readable code; ``str(exc)`` is for a human.
    Every refusal in this module is raised before the leg it guards, so a caught
    ``SwapRefused`` means nothing was spent by the leg that raised it.
    """

    def __init__(self, reason: str, message: str = ""):
        self.reason = reason
        self.message = message or reason
        super().__init__("%s: %s" % (reason, self.message) if message else reason)


# --------------------------------------------------------------- USDC amounts


def usdc_to_micro(text) -> int:
    """Exact decimal USDC string -> integer micro-USDC. No float is involved.

    Mirrors ``mandate.xno_to_raw`` deliberately, including its refusal of
    non-ASCII digits: ``str.isdigit()`` is true for every Unicode digit, so a
    check without ``isascii()`` accepts amounts a JavaScript ``/^\\d+$/`` peer
    refuses, and the two sides then disagree about whether a price is valid.
    """
    if isinstance(text, bool) or not isinstance(text, str):
        raise SwapRefused("invalid_amount",
                          "USDC amounts must be given as a decimal string, got %s"
                          % type(text).__name__)
    t = text.strip()
    if not t:
        raise SwapRefused("invalid_amount", "a USDC amount must not be empty, got %r" % text)
    whole, dot, frac = t.partition(".")
    if not whole:
        whole = "0"
    if not (whole.isdigit() and whole.isascii()) \
            or (dot and not (frac.isdigit() and frac.isascii())) \
            or len(frac) > 6:
        raise SwapRefused("invalid_amount",
                          "%r is not a decimal USDC amount (max 6 decimals)" % text)
    n = int(whole) * MICRO_PER_USDC + int(frac.ljust(6, "0") or "0")
    if n <= 0:
        raise SwapRefused("invalid_amount", "a USDC amount must be greater than zero, got %r" % text)
    return n


def micro_to_usdc(micro: int) -> str:
    """Integer micro-USDC -> exact decimal string, for a query parameter."""
    whole, frac = divmod(int(micro), MICRO_PER_USDC)
    frac_s = str(frac).rjust(6, "0").rstrip("0")
    return "%d.%s" % (whole, frac_s) if frac_s else "%d" % whole


def _canonical_nano_network(value) -> str:
    """The canonical Nano network identifier, or a refusal naming why not.

    A bare ``nano`` or ``xno`` is **not** read as mainnet. It names the family
    without naming the network, and Nano's test networks share the ``nano_``
    address prefix, so reading it as mainnet would be a guess about where money
    goes.
    """
    if not isinstance(value, str):
        raise SwapRefused("network_unspecified",
                          "network must be a string, got %s" % type(value).__name__)
    key = value.strip().lower()
    if key in _NANO_NETWORK_ALIASES:
        return _NANO_NETWORK_ALIASES[key]
    if key in ("nano", "xno"):
        raise SwapRefused("network_unspecified",
                          "%r names the family but not the network; expected %r"
                          % (value, CANONICAL_NANO_NETWORK))
    if key.startswith("nano:") or key.startswith("nano-"):
        raise SwapRefused("not_mainnet",
                          "%r is a Nano network but not mainnet; this hop only pays %r"
                          % (value, CANONICAL_NANO_NETWORK))
    raise SwapRefused("not_nano", "%r is not a Nano network" % value)


# ------------------------------------------------------------------- the quote


@dataclass(frozen=True)
class NanoQuote:
    """The seller's x402 price, in the only units it can be paid in.

    ``amount_raw`` is an exact integer count of raw. x402's ``exact`` scheme
    means exact: this amount is what gets sent, never the amount a swap
    happened to deliver.
    """

    pay_to: str
    amount_raw: int
    network: str = CANONICAL_NANO_NETWORK

    def __post_init__(self):
        try:
            object.__setattr__(self, "pay_to", normalise_address(self.pay_to))
        except MandateRefused as exc:
            raise SwapRefused("invalid_payee",
                              "payTo is not a payable Nano account (%s)" % exc.reason) from exc
        try:
            object.__setattr__(self, "amount_raw", parse_raw(self.amount_raw, "amount_raw"))
        except MandateRefused as exc:
            raise SwapRefused("invalid_amount", str(exc)) from exc
        object.__setattr__(self, "network", _canonical_nano_network(self.network))

    @property
    def amount_xno(self) -> str:
        return raw_to_xno(self.amount_raw)

    @classmethod
    def from_x402_entry(cls, entry: Mapping[str, Any]) -> "NanoQuote":
        """Read one ``accepts[]`` entry of an x402 402 challenge.

        Both of x402's price field names are accepted because a Nano entry in
        the wild carries one or the other, and an entry carrying both must agree
        -- two different prices in one entry is a refusal, not a choice to make
        on the payer's behalf.
        """
        if not isinstance(entry, Mapping):
            raise SwapRefused("invalid_quote",
                              "an x402 accepts[] entry must be an object, got %s"
                              % type(entry).__name__)
        present = {k: entry[k] for k in _AMOUNT_FIELDS if k in entry and entry[k] is not None}
        if not present:
            raise SwapRefused("invalid_quote",
                              "the entry carries no price: expected one of %s"
                              % ", ".join(_AMOUNT_FIELDS))
        amounts = set()
        for name, value in present.items():
            try:
                amounts.add(parse_raw(value, name))
            except MandateRefused as exc:
                raise SwapRefused("invalid_amount", str(exc)) from exc
        if len(amounts) > 1:
            raise SwapRefused("contradictory_price",
                              "the entry carries two different prices (%s); refusing to pick one"
                              % ", ".join("%s=%s" % (k, present[k]) for k in sorted(present)))
        if "payTo" not in entry:
            raise SwapRefused("invalid_quote", "the entry carries no payTo")
        return cls(pay_to=entry["payTo"], amount_raw=amounts.pop(),
                   network=entry.get("network", CANONICAL_NANO_NETWORK))


# ------------------------------------------------------- what a provider says


@dataclass(frozen=True)
class SwapEstimate:
    """A provider's estimate for one direction of one pair.

    ``to_amount`` is the provider's exact decimal XNO string; ``to_amount_raw``
    is that same number as an integer of raw and is what every comparison uses.
    """

    from_currency: str
    from_network: str
    to_currency: str
    to_network: str
    from_amount_micro: int
    to_amount: str

    @property
    def to_amount_raw(self) -> int:
        try:
            return xno_to_raw(self.to_amount)
        except MandateRefused as exc:
            raise SwapRefused("estimate_unparsable",
                              "the provider's estimated output %r is not an exact decimal XNO "
                              "amount (%s)" % (self.to_amount, exc.reason)) from exc


@dataclass(frozen=True)
class SwapLimits:
    """The provider's minimum and maximum input for a pair, in micro-USDC."""

    min_from_micro: int
    max_from_micro: Optional[int] = None


@dataclass(frozen=True)
class SwapOrder:
    """A created swap order: where to pay the provider, and what it will send."""

    order_id: str
    pay_in_address: str
    from_amount_micro: int
    to_address: str
    expected_to_amount: str
    status: str = "created"
    raw: Mapping[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------- the plan


@dataclass(frozen=True)
class SwapPlan:
    """A checked hop that has not happened yet. Building one moves no money."""

    quote: NanoQuote
    own_address: str
    from_currency: str
    from_network: str
    from_amount_micro: int
    estimated_to_amount_raw: int
    required_to_amount_raw: int
    slippage_bps: int
    order_key: str

    @property
    def from_amount(self) -> str:
        return micro_to_usdc(self.from_amount_micro)

    @property
    def headroom_raw(self) -> int:
        return self.estimated_to_amount_raw - self.required_to_amount_raw

    def as_dict(self) -> Dict[str, object]:
        return {
            "pay_to": self.quote.pay_to,
            "amount_raw": str(self.quote.amount_raw),
            "amount_xno": self.quote.amount_xno,
            "network": self.quote.network,
            "swap_to_address": self.own_address,
            "from_currency": self.from_currency,
            "from_network": self.from_network,
            "from_amount": self.from_amount,
            "estimated_to_amount_raw": str(self.estimated_to_amount_raw),
            "required_to_amount_raw": str(self.required_to_amount_raw),
            "headroom_raw": str(self.headroom_raw),
            "slippage_bps": self.slippage_bps,
            "order_key": self.order_key,
        }


@dataclass(frozen=True)
class SwapHopResult:
    """The outcome of a hop that was executed."""

    plan: SwapPlan
    order: SwapOrder
    received_raw: int
    settlement: Any = None

    @property
    def settled(self) -> bool:
        return bool(getattr(self.settlement, "settled", False))


def _required_with_headroom(amount_raw: int, slippage_bps: int) -> int:
    """The quote plus headroom, rounded UP, in integers only.

    Rounding up matters: rounding the headroom down can make the required
    output equal the bare quote, which is the case this guard exists to stop.
    """
    if isinstance(slippage_bps, bool) or not isinstance(slippage_bps, int):
        raise SwapRefused("invalid_slippage",
                          "slippage_bps must be an integer number of basis points, got %s"
                          % type(slippage_bps).__name__)
    if slippage_bps < 0:
        raise SwapRefused("invalid_slippage",
                          "slippage_bps must not be negative, got %d" % slippage_bps)
    if slippage_bps >= 10_000:
        raise SwapRefused("invalid_slippage",
                          "slippage_bps must be under 10000 (100%%), got %d" % slippage_bps)
    # ceil(amount * (10000 + bps) / 10000), as integers.
    required = -(-(amount_raw * (10_000 + slippage_bps)) // 10_000)
    if required > MAX_RAW:
        raise SwapRefused("amount_above_ceiling",
                          "the quote plus %d bps of headroom is %d raw, above the 2**128-1 a Nano "
                          "balance can hold" % (slippage_bps, required))
    return required


def plan_swap_hop(
    quote: NanoQuote,
    own_address: str,
    estimate: SwapEstimate,
    *,
    max_from_amount: str,
    order_key: str,
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
    limits: Optional[SwapLimits] = None,
) -> SwapPlan:
    """Check a USDC -> XNO -> seller hop. Pure: no network, no money, no key.

    Raises ``SwapRefused`` with a stable ``reason`` on anything that would make
    the hop lose money or pay the wrong party. Returns a ``SwapPlan`` only when
    every one of those checks passed.
    """
    if not isinstance(quote, NanoQuote):
        raise SwapRefused("invalid_quote", "quote must be a NanoQuote")
    if not isinstance(estimate, SwapEstimate):
        raise SwapRefused("invalid_estimate", "estimate must be a SwapEstimate")
    if not isinstance(order_key, str) or not order_key.strip():
        raise SwapRefused("invalid_order_key",
                          "order_key must be a non-empty string; it is what makes a retry "
                          "idempotent")

    try:
        own = normalise_address(own_address)
    except MandateRefused as exc:
        raise SwapRefused("invalid_own_address",
                          "the swap destination is not a payable Nano account (%s)" % exc.reason) from exc

    # The shortcut this module exists to refuse. Pointing the swap straight at
    # the seller looks like it saves a leg, and it breaks the payment in three
    # ways at once: the provider sends whatever the swap yielded, not the
    # quote's exact raw, so an "exact" scheme payment is the wrong amount; the
    # block comes from the provider's account, so it is not bound to this
    # agent's order and the agent cannot prove it paid; and a shortfall is
    # discovered by the seller rather than refused here, after the USDC is gone.
    if own == quote.pay_to:
        raise SwapRefused(
            "swap_destination_is_payee",
            "the swap destination is the seller's payTo. Swap into an account this agent "
            "controls, then send the quote's exact %s raw from it: a provider pays out what the "
            "swap yielded, from its own account, which is neither the exact amount nor a block "
            "bound to this order" % quote.amount_raw)

    # An estimate for the wrong pair is a quote for somebody else's trade, and
    # it would otherwise be compared against this quote as though it were ours.
    if not isinstance(estimate.to_currency, str) \
            or estimate.to_currency.strip().upper() not in ("XNO", "NANO"):
        raise SwapRefused("estimate_wrong_pair",
                          "the estimate's output is %r, not XNO" % (estimate.to_currency,))

    from_amount_micro = estimate.from_amount_micro
    if isinstance(from_amount_micro, bool) or not isinstance(from_amount_micro, int):
        raise SwapRefused("invalid_amount",
                          "the estimate's input must be integer micro-USDC, got %s"
                          % type(from_amount_micro).__name__)
    if from_amount_micro <= 0:
        raise SwapRefused("invalid_amount",
                          "the estimate's input must be greater than zero, got %d" % from_amount_micro)

    cap_micro = usdc_to_micro(max_from_amount)
    if from_amount_micro > cap_micro:
        raise SwapRefused(
            "exceeds_cap",
            "the swap would spend %s %s, over the %s cap. Nothing in a swap hop is trustless -- "
            "this cap is the only bound on what the provider receives"
            % (micro_to_usdc(from_amount_micro), estimate.from_currency,
               micro_to_usdc(cap_micro)))

    if limits is not None:
        if from_amount_micro < limits.min_from_micro:
            raise SwapRefused("below_provider_minimum",
                              "the provider's minimum for this pair is %s %s; the swap is %s"
                              % (micro_to_usdc(limits.min_from_micro), estimate.from_currency,
                                 micro_to_usdc(from_amount_micro)))
        if limits.max_from_micro is not None and from_amount_micro > limits.max_from_micro:
            raise SwapRefused("above_provider_maximum",
                              "the provider's maximum for this pair is %s %s; the swap is %s"
                              % (micro_to_usdc(limits.max_from_micro), estimate.from_currency,
                                 micro_to_usdc(from_amount_micro)))

    required = _required_with_headroom(quote.amount_raw, slippage_bps)
    estimated = estimate.to_amount_raw  # may itself raise estimate_unparsable
    if estimated < required:
        shortfall = required - estimated
        raise SwapRefused(
            "estimate_below_quote",
            "the swap is estimated to yield %s raw but the quote needs %s raw plus %d bps of "
            "headroom (%s raw), short by %s raw. Spending the USDC on this swap would leave the "
            "payment unmakeable and the USDC gone"
            % (estimated, quote.amount_raw, slippage_bps, required, shortfall))

    return SwapPlan(
        quote=quote,
        own_address=own,
        from_currency=estimate.from_currency,
        from_network=estimate.from_network,
        from_amount_micro=from_amount_micro,
        estimated_to_amount_raw=estimated,
        required_to_amount_raw=required,
        slippage_bps=slippage_bps,
        order_key=order_key.strip(),
    )


# -------------------------------------------------------------- the provider

#: Base URL and paths as the published ``nanswap`` npm client 1.0.3 spells them.
#: The "partner" endpoints are the cross-chain ones -- a USDC-on-BSC to XNO hop
#: is a partner route, not the native XNO/BAN route the plain endpoints serve.
NANSWAP_BASE = "https://api.nanswap.com/v1"
NANSWAP_ESTIMATE_PARTNER = "/get-estimate-partner"
NANSWAP_LIMITS_PARTNER = "/get-limits-partner"
NANSWAP_CREATE_ORDER_PARTNER = "/create-order-partner"
NANSWAP_GET_ORDER_PARTNER = "/get-order-partner"
NANSWAP_API_KEY_HEADER = "nanswap-api-key"


def _field(payload: Mapping[str, Any], name: str, kinds, where: str):
    """One field of a provider response, or a refusal naming what was wrong.

    No field is defaulted and no type is coerced. The live API was unreachable
    from the environment this was written in, so an unrecognised shape is a
    refusal to be fixed by someone who can see a real response -- never a
    payment made on a misread number.
    """
    if not isinstance(payload, Mapping):
        raise SwapRefused("provider_response_unrecognised",
                          "%s: expected a JSON object, got %s" % (where, type(payload).__name__))
    if name not in payload:
        raise SwapRefused("provider_response_unrecognised",
                          "%s: the response carries no %r (keys: %s)"
                          % (where, name, ", ".join(sorted(map(str, payload))) or "none"))
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, kinds):
        wanted = kinds if isinstance(kinds, tuple) else (kinds,)
        raise SwapRefused("provider_response_unrecognised",
                          "%s: %r is %s, expected %s"
                          % (where, name, type(value).__name__,
                             " or ".join(k.__name__ for k in wanted)))
    return value


def _exact_decimal(value, where: str, field_name: str) -> str:
    """A provider's amount as an exact decimal string.

    A JSON number is refused outright: ``json.loads`` gives back a float, and a
    float cannot hold 30 significant decimal digits, so an XNO amount that
    arrived as a number has already lost precision before this module saw it.
    """
    if isinstance(value, str):
        return value.strip()
    raise SwapRefused(
        "provider_amount_not_a_string",
        "%s: %r came back as %s. An XNO amount must arrive as a decimal string -- JSON's single "
        "number type is a float here, which cannot hold 30 decimals, so the value is already "
        "lossy by the time it is read"
        % (where, field_name, type(value).__name__))


class NanswapProvider:
    """Requests for Nanswap's partner (cross-chain) endpoints.

    The URLs, query parameter names, POST body keys and the API-key header are
    the ones in the published ``nanswap`` npm client 1.0.3 -- read off its
    source, not guessed. ``transport`` is the one seam: it takes
    ``(method, url, headers, body)`` and returns the decoded JSON, so the tests
    and the shipped example run with no network and no key.

    ``api_key`` is only ever needed by ``create_order``; a provider built
    without one can quote and read limits but cannot spend.
    """

    name = "nanswap"

    def __init__(self, api_key: Optional[str] = None,
                 transport: Optional[Callable[..., Any]] = None,
                 base_url: str = NANSWAP_BASE, timeout: float = 20.0):
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport or self._http

    # -- the one seam ------------------------------------------------------

    def _http(self, method: str, url: str, headers: Mapping[str, str], body):
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers = dict(headers)
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(self, path: str, params: Dict[str, str]):
        url = "%s%s?%s" % (self._base, path, urllib.parse.urlencode(params))
        return self._transport("GET", url, {}, None)

    def _post(self, path: str, body: Dict[str, Any]):
        if not self._api_key:
            raise SwapRefused("no_api_key",
                              "%s needs a Nanswap API key (header %r); a provider built without "
                              "one can quote but cannot create an order"
                              % (path, NANSWAP_API_KEY_HEADER))
        url = "%s%s" % (self._base, path)
        return self._transport("POST", url, {NANSWAP_API_KEY_HEADER: self._api_key}, body)

    # -- read path ---------------------------------------------------------

    def estimate(self, *, from_currency: str, from_network: str, from_amount_micro: int,
                 to_currency: str = "XNO", to_network: str = "") -> SwapEstimate:
        """Forward estimate: this much in, how much XNO out.

        Nanswap publishes ``get-estimate-reverse`` for its native pairs but
        **no reverse estimate for the partner (cross-chain) routes** -- it is
        absent from the npm client and so from the documented surface. There is
        therefore no way to ask "what input yields exactly this output" for a
        USDC hop. That is why ``plan_swap_hop`` takes an input amount and
        refuses one whose estimated output is short, rather than solving for the
        input: the direction the API offers is the direction the guard runs in.
        """
        payload = self._get(NANSWAP_ESTIMATE_PARTNER, {
            "from": from_currency,
            "to": to_currency,
            "amount": micro_to_usdc(from_amount_micro),
            "fromNetwork": from_network,
            "toNetwork": to_network,
        })
        where = "estimate %s(%s)->%s" % (from_currency, from_network, to_currency)
        amount = _exact_decimal(_field(payload, "amountTo", (str, int, float), where),
                                where, "amountTo")
        return SwapEstimate(
            from_currency=from_currency, from_network=from_network,
            to_currency=to_currency, to_network=to_network,
            from_amount_micro=from_amount_micro, to_amount=amount,
        )

    def limits(self, *, from_currency: str, from_network: str,
               to_currency: str = "XNO", to_network: str = "") -> SwapLimits:
        payload = self._get(NANSWAP_LIMITS_PARTNER, {
            "from": from_currency,
            "to": to_currency,
            "fromNetwork": from_network,
            "toNetwork": to_network,
        })
        where = "limits %s(%s)->%s" % (from_currency, from_network, to_currency)
        minimum = _exact_decimal(_field(payload, "min", (str, int, float), where), where, "min")
        limits_min = usdc_to_micro(minimum)
        limits_max = None
        if payload.get("max") is not None:
            limits_max = usdc_to_micro(_exact_decimal(payload["max"], where, "max"))
        return SwapLimits(min_from_micro=limits_min, max_from_micro=limits_max)

    def order(self, order_id: str) -> SwapOrder:
        payload = self._get(NANSWAP_GET_ORDER_PARTNER, {"id": order_id})
        return self._order_from(payload, "order %s" % order_id)

    # -- spend path --------------------------------------------------------

    def create_order(self, plan: SwapPlan) -> SwapOrder:
        """Create the swap order. **This is the leg that spends.**"""
        payload = self._post(NANSWAP_CREATE_ORDER_PARTNER, {
            "from": plan.from_currency,
            "to": "XNO",
            "amount": plan.from_amount,
            "fromAddress": "",
            "toAddress": plan.own_address,
        })
        order = self._order_from(payload, "create-order %s" % plan.order_key)
        # The provider is told where to send; it is still checked on the way
        # back out. A payout address that is not the one asked for is the whole
        # loss, so it is refused here rather than noticed later.
        if normalise_address(order.to_address) != plan.own_address:
            raise SwapRefused(
                "order_destination_changed",
                "the order came back paying out to %s, not the %s it was created for"
                % (order.to_address, plan.own_address))
        return order

    def _order_from(self, payload, where: str) -> SwapOrder:
        order_id = _field(payload, "id", str, where)
        pay_in = _field(payload, "payinAddress", str, where)
        to_address = _field(payload, "payoutAddress", str, where)
        expected = _exact_decimal(_field(payload, "expectedAmountTo", (str, int, float), where),
                                  where, "expectedAmountTo")
        from_amount = _exact_decimal(_field(payload, "expectedAmountFrom", (str, int, float), where),
                                     where, "expectedAmountFrom")
        return SwapOrder(
            order_id=order_id, pay_in_address=pay_in,
            from_amount_micro=usdc_to_micro(from_amount),
            to_address=to_address, expected_to_amount=expected,
            status=str(payload.get("status", "created")), raw=dict(payload),
        )


# ----------------------------------------------------------------- the hop


def pay_nano_quote_from_usdc(
    quote: NanoQuote,
    own_address: str,
    provider: Any,
    *,
    from_currency: str,
    from_network: str,
    from_amount: str,
    max_from_amount: str,
    order_key: str,
    rail: Any = None,
    balance_raw: Optional[Callable[[], int]] = None,
    order_log: Optional[Dict[str, Any]] = None,
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
    check_limits: bool = True,
    execute: bool = False,
) -> Any:
    """Quote, swap, send -- one call. Returns a ``SwapPlan`` or a ``SwapHopResult``.

    ``execute`` defaults to **False**, so the default behaviour of this function
    is to check the hop and return the plan without spending anything. Nothing
    moves until a caller asks for it in as many words.

    **Retry is this function, called again with the same ``order_key``.** A swap
    takes as long as the provider takes, so the first call that gets as far as
    creating an order raises ``swap_not_received_yet``; calling again with the
    same ``order_key`` reads the recorded order back out of ``order_log``
    instead of creating a second one, re-checks what arrived, and sends when it
    covers the quote. That is why ``order_log`` is required to execute: without
    somewhere durable to record the order, a retry after a crash would buy the
    swap twice and spend the USDC twice.
    """
    if not isinstance(order_key, str) or not order_key.strip():
        raise SwapRefused("invalid_order_key", "order_key must be a non-empty string")
    key = order_key.strip()

    from_amount_micro = usdc_to_micro(from_amount)

    # Checks that need no network run before the provider is spoken to at all.
    # Quoting a hop that is already refused wastes a call and reads, in a log,
    # as though the hop were under way.
    _refuse_unplannable(quote, own_address)

    limits = None
    if check_limits and hasattr(provider, "limits"):
        limits = provider.limits(from_currency=from_currency, from_network=from_network)

    recorded = (order_log or {}).get(key)
    if recorded is None:
        estimate = provider.estimate(from_currency=from_currency, from_network=from_network,
                                     from_amount_micro=from_amount_micro)
        plan = plan_swap_hop(quote, own_address, estimate, max_from_amount=max_from_amount,
                             order_key=key, slippage_bps=slippage_bps, limits=limits)
    else:
        # A retry. Re-plan from the recorded order so the amount that is about
        # to be sent is still checked, but never re-quote: the order exists and
        # its terms are fixed.
        plan = recorded["plan"]
        if plan.quote != quote:
            raise SwapRefused(
                "order_key_reused",
                "order_key %r already belongs to a hop paying %s raw to %s; a different quote "
                "under the same key would read that order as this one's"
                % (key, plan.quote.amount_raw, plan.quote.pay_to))

    if not execute:
        return plan

    if order_log is None:
        raise SwapRefused(
            "no_order_log",
            "executing needs an order_log to record the created order in. Without one a retry "
            "after a crash creates a second swap order and spends the USDC twice")
    if balance_raw is None:
        raise SwapRefused(
            "no_balance_source",
            "executing needs balance_raw() to read what the swap actually delivered. Sending "
            "the quote's amount without checking what arrived is how a shortfall becomes a "
            "failed payment with the USDC already gone")
    if rail is None:
        raise SwapRefused("no_rail", "executing needs a rail to make the final XNO send on")

    if recorded is None:
        before = _integer_balance(balance_raw, "before the swap")
        order = provider.create_order(plan)
        order_log[key] = {"plan": plan, "order": order, "balance_before_raw": before}
    else:
        order = recorded["order"]
        before = recorded["balance_before_raw"]

    after = _integer_balance(balance_raw, "after the swap")
    received = after - before
    if received < plan.quote.amount_raw:
        raise SwapRefused(
            "swap_not_received_yet",
            "the swap has delivered %s raw of the %s the quote needs (order %s). Nothing was "
            "sent. Call again with order_key %r once it has settled -- the recorded order is "
            "read back rather than bought a second time"
            % (received, plan.quote.amount_raw, order.order_id, key))

    # The exact raw of the quote, never the amount the swap happened to yield.
    # Any surplus stays in the agent's own account.
    settlement = rail.pay_to(plan.quote.pay_to, plan.quote.amount_raw, ref=key)
    return SwapHopResult(plan=plan, order=order, received_raw=received, settlement=settlement)


def _refuse_unplannable(quote: NanoQuote, own_address) -> None:
    """The subset of ``plan_swap_hop``'s refusals that need no estimate."""
    if not isinstance(quote, NanoQuote):
        raise SwapRefused("invalid_quote", "quote must be a NanoQuote")
    try:
        own = normalise_address(own_address)
    except MandateRefused as exc:
        raise SwapRefused("invalid_own_address",
                          "the swap destination is not a payable Nano account (%s)"
                          % exc.reason) from exc
    if own == quote.pay_to:
        raise SwapRefused(
            "swap_destination_is_payee",
            "the swap destination is the seller's payTo. Swap into an account this agent "
            "controls, then send the quote's exact %s raw from it: a provider pays out what the "
            "swap yielded, from its own account, which is neither the exact amount nor a block "
            "bound to this order" % quote.amount_raw)


def _integer_balance(balance_raw: Callable[[], int], when: str) -> int:
    value = balance_raw()
    if isinstance(value, bool) or not isinstance(value, int):
        raise SwapRefused("balance_not_an_integer",
                          "balance_raw() %s returned %s; a Nano balance is an integer count of "
                          "raw and a float cannot hold one" % (when, type(value).__name__))
    if value < 0:
        raise SwapRefused("balance_not_an_integer",
                          "balance_raw() %s returned %d" % (when, value))
    return value
