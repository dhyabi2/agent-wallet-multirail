"""Tests for the PayClaw-shaped Nano rail example (examples/payclaw_nano_rail.py)."""

import sys

sys.path.insert(0, "src")
sys.path.insert(0, "examples")

from payclaw_nano_rail import PayClaw, PayClawWallet, WalletReceipt


def _wallet() -> PayClawWallet:
    payclaw = PayClaw(chain="base-sepolia")
    return payclaw.createWallet(
        policies={
            "dailyLimit": 500,
            "perTransactionLimit": 100,
            "approvalThreshold": 50,
            "allowedTokens": ["USDC", "XNO"],
        }
    )


def test_payclaw_pay_returns_receipt_shape():
    wallet = _wallet()
    receipt = wallet.pay(to="0xMerchant", token="USDC", amount=1.00, memo="Invoice #1")
    assert isinstance(receipt, WalletReceipt)
    assert receipt.memo == "Invoice #1"


def test_nano_token_routes_to_feeless_rail():
    wallet = _wallet()
    nano = wallet.pay(to="nano_...Merchant", token="XNO", amount=1.00, memo="Invoice #1")
    assert nano.rail == "nano-xno"
    assert nano.token == "XNO"
    assert nano.fee_usd == 0.0        # feeless per transfer
    assert nano.finality_s <= 1.0     # sub-second


def test_usdc_token_routes_to_stablecoin_rail():
    wallet = _wallet()
    usdc = wallet.pay(to="0xMerchant", token="USDC", amount=1.00, memo="Invoice #1")
    assert usdc.rail == "usdc-evm"
    assert usdc.token == "USDC"
    assert usdc.fee_usd > 0.0         # processing fee + EVM gas


def test_same_amount_settles_on_both_rails():
    wallet = _wallet()
    amount = 1.00
    usdc = wallet.pay(to="0xMerchant", token="USDC", amount=amount, memo="Invoice #1")
    nano = wallet.pay(to="nano_...Merchant", token="XNO", amount=amount, memo="Invoice #1")
    assert usdc.amount == nano.amount == amount


def test_main_runs_end_to_end():
    import payclaw_nano_rail as m
    # main() must complete without error (simulated, no keys).
    m.main()
