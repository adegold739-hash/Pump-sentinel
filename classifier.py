"""
Pump Sentinel — classifier test harness

Runs real transaction signatures through analyze_transaction() and
prints the classification result, so you can verify Test 1-6 from
the project doc without going through Telegram for each one.

Usage:
    export HELIUS_API_KEY=your_key_here
    python3 test_classifier.py

Add / edit entries in TEST_CASES below as you find real signatures
for each scenario. "expected" is optional — if set, the script will
flag a PASS/FAIL; if left as None, it just reports what it found so
you can eyeball it.
"""

import os
import sys

import requests

# ---------------------------------------------------------------
# Import the real analysis code from bot.py without needing a
# running Telegram bot or Flask app.
# ---------------------------------------------------------------
import types

_stub_flask = types.ModuleType("flask")
_stub_flask.Flask = lambda *a, **k: types.SimpleNamespace(
    route=lambda *a, **k: (lambda f: f)
)
sys.modules["flask"] = _stub_flask

_stub_telegram = types.ModuleType("telegram")
_stub_telegram.Update = object
sys.modules["telegram"] = _stub_telegram

_stub_telegram_ext = types.ModuleType("telegram.ext")
_stub_telegram_ext.Application = object
_stub_telegram_ext.CommandHandler = object
_stub_telegram_ext.ContextTypes = type(
    "CT", (), {"DEFAULT_TYPE": object}
)
sys.modules["telegram.ext"] = _stub_telegram_ext

_stub_database = types.ModuleType("database")
_stub_database.init_database = lambda: None
_stub_database.add_token = lambda x: True
_stub_database.get_tokens = lambda: []
sys.modules["database"] = _stub_database

import bot  # noqa: E402


HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
HELIUS_URL = (
    "https://mainnet.helius-rpc.com/"
    f"?api-key={HELIUS_API_KEY}"
)


def fetch_transaction(signature):
    response = requests.post(
        HELIUS_URL,
        json={
            "jsonrpc": "2.0",
            "id": "test-harness",
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "jsonParsed",
                    "commitment": "confirmed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    return data.get("result")


# ---------------------------------------------------------------
# Test cases from the project doc (Section 17).
# Fill in real signatures as you collect them. Leave "expected" as
# None if you just want to inspect the output.
# ---------------------------------------------------------------
TEST_CASES = [
    {
        "name": "Test 3: Plain token transfer (reference case)",
        "signature": (
            "5KqGyWhTUvGMDnXxNxoksMui2epo6wfSL9tkgDojvPFPaoW2Gt3sV4PFKHkQKgqeVkTB2Lgp5sQbtL7LP6Q3NjvT"
        ),
        "expected": "TRANSFER",
    },
    {
        "name": "Test 1: Confirmed BUY",
        "signature": "PASTE_SIGNATURE_HERE",
        "expected": "BUY",
    },
    {
        "name": "Test 2: Confirmed SELL",
        "signature": "PASTE_SIGNATURE_HERE",
        "expected": "SELL",
    },
    {
        "name": "Test 4: Fee-only transaction",
        "signature": "PASTE_SIGNATURE_HERE",
        "expected": "UNKNOWN",
    },
    {
        "name": "Test 5: Real DEX swap",
        "signature": "PASTE_SIGNATURE_HERE",
        "expected": None,  # inspect manually — no confirmed answer yet
    },
    {
        "name": "Test 6: Complex/router transaction",
        "signature": "PASTE_SIGNATURE_HERE",
        "expected": None,
    },
]


def run_test(case):
    name = case["name"]
    signature = case["signature"]
    expected = case.get("expected")

    print(f"--- {name} ---")
    print(f"Signature: {signature}")

    if signature == "PASTE_SIGNATURE_HERE":
        print("SKIPPED (no signature filled in)\n")
        return None

    try:
        transaction = fetch_transaction(signature)
    except Exception as error:
        print(f"ERROR fetching transaction: {error}\n")
        return False

    if not transaction:
        print("ERROR: transaction not found\n")
        return False

    analysis = bot.analyze_transaction(transaction, signature)

    print(f"Status:         {analysis['status']}")
    print(f"Fee:            {analysis['fee_sol']:.9f} SOL")
    print(f"Fee payer:      {analysis['fee_payer']}")
    print(f"Classification: {analysis['classification']}")
    print(f"Trader:         {analysis['trader']}")
    print(f"Token delta:    {analysis['token_delta']}")
    print(f"SOL delta:      {analysis['sol_delta']}")

    if expected is not None:
        passed = analysis["classification"] == expected
        print(f"Expected:       {expected}")
        print("RESULT: " + ("PASS" if passed else "FAIL"))
        print()
        return passed

    print("RESULT: (no expected value set — inspect manually)\n")
    return None


def main():
    if not HELIUS_API_KEY:
        print("ERROR: set HELIUS_API_KEY in your environment first.")
        sys.exit(1)

    results = []

    for case in TEST_CASES:
        result = run_test(case)
        if result is not None:
            results.append(result)

    if results:
        passed = sum(1 for r in results if r)
        print(f"Summary: {passed}/{len(results)} tests passed.")
    else:
        print("Summary: no tests had both a signature and an expected value.")


if __name__ == "__main__":
    main()
