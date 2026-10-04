#!/usr/bin/env python3
"""An agent holding only USDC pays a seller's XNO x402 quote.

pursekeeper.dev's rank 3: *"an agent with USDC pays a Nano seller through a
Nanswap-style hop"*, because *"Nobody in the x402 buyer population holds Nano"*.

Runs with no network, no wallet and no key: the swap provider's HTTP seam and
the Nano rail's RPC seam are both local stubs here. The literal responses below
are in the shape the published ``nanswap`` npm client reads.

    python3 examples/pay_nano_quote_from_usdc.py          # the whole hop
    python3 examples/pay_nano_quote_from_usdc.py refuse   # the shortcut, refused
"""
import json
import sys

from agent_wallet_multirail import NanoRail
from agent_wallet_multirail.swap import (
    NanoQuote,
    NanswapProvider,
    SwapRefused,
    pay_nano_quote_from_usdc,
)

RAW = 10 ** 30

# The seller's 402 challenge entry, as a Nano-accepting seller emits it.
SELLER_ENTRY = {
    "scheme": "exact",
    "network": "nano:mainnet",
    "payTo": "nano_1111111111111111111111111111111111111111111111111111hifc8npp",
    "amount": str(RAW // 10000),              # 0.0001 XNO, as an integer of raw
    "maxAmountRequired": str(RAW // 10000),   # x402 v1's name for the same integer
    "maxTimeoutSeconds": 60,
}

# The agent's OWN Nano account - the swap's destination, never the seller's.
AGENT_ACCOUNT = "nano_3t6k35gi95xu6tergt6p69ck76ogmitsa8mnijtpxm9fkcm736xtoncuohr3"


def stub_transport(responses):
    answers = iter(responses)

    def transport(method, url, headers, body):
        answer = next(answers)
        print("    %-4s %s" % (method, url.split("?")[0].rsplit("/", 1)[-1]))
        return answer

    return transport


def main(argv):
    shortcut = len(argv) > 1 and argv[1] == "refuse"

    quote = NanoQuote.from_x402_entry(SELLER_ENTRY)
    print("seller wants %s raw (%s XNO) at %s" % (quote.amount_raw, quote.amount_xno, quote.pay_to))

    provider = NanswapProvider(api_key="demo-key", transport=stub_transport([
        {"min": "0.5", "max": "1000"},            # get-limits-partner
        {"amountTo": "0.000105"},                 # get-estimate-partner
        {"id": "ord-demo", "payinAddress": "0xTheProviderPaysInHere",
         "payoutAddress": AGENT_ACCOUNT,
         "expectedAmountTo": "0.000105", "expectedAmountFrom": "1"},
    ]))

    # The swap delivers 0.000105 XNO; the seller is still paid exactly 0.0001.
    balances = iter([0, 105 * 10 ** 24])
    sent = {}

    def rpc(request):
        sent.update(request)
        return {"block": "DEMOBLOCK", "confirmed": True}

    destination = quote.pay_to if shortcut else AGENT_ACCOUNT
    if shortcut:
        print("\n-- swapping STRAIGHT to the seller (the shortcut) --")
    else:
        print("\n-- swapping into the agent's own account, then sending --")

    try:
        result = pay_nano_quote_from_usdc(
            quote, destination, provider,
            from_currency="USDC", from_network="BSC",
            from_amount="1", max_from_amount="2",
            order_key="demo-order-1",
            rail=NanoRail(rpc=rpc),
            balance_raw=lambda: next(balances),
            order_log={},
            execute=True,
        )
    except SwapRefused as refused:
        print("\nREFUSED (%s)\n  %s" % (refused.reason, refused.message))
        print("\nNothing was swapped and nothing was sent.")
        return 1

    print(json.dumps(result.plan.as_dict(), indent=2))
    print("\nswap order      %s (pay the provider at %s)"
          % (result.order.order_id, result.order.pay_in_address))
    print("swap delivered  %s raw" % result.received_raw)
    print("sent to seller  %s raw to %s" % (sent["amount_raw"], sent["destination"]))
    print("surplus kept    %s raw" % (result.received_raw - quote.amount_raw))
    print("settled         %s" % result.settled)
    assert sent["amount_raw"] == str(quote.amount_raw), "the seller must get the exact quote"
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
