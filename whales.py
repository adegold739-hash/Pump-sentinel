import os
import requests

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

HELIUS_URL = (
    "https://mainnet.helius-rpc.com/"
    f"?api-key={HELIUS_API_KEY}"
)


def get_top_holders(token_address, limit=10):
    if not HELIUS_API_KEY:
        return None, "Helius API key is missing."

    try:
        response = requests.post(
            HELIUS_URL,
            json={
                "jsonrpc": "2.0",
                "id": "pump-sentinel",
                "method": "getTokenAccounts",
                "params": {
                    "mint": token_address,
                    "page": 1,
                    "limit": 1000
                }
            },
            timeout=20
        )

        if not response.ok:
            return None, "Helius request failed."

        data = response.json()

        if "error" in data:
            return None, "Could not retrieve token holders."

        accounts = data.get("result", {}).get(
            "token_accounts", []
        )

        if not accounts:
            return None, "No token holders found."

        # Combine multiple token accounts belonging
        # to the same wallet.
        holders = {}

        for account in accounts:
            owner = account.get("owner")
            amount = account.get("amount", 0)

            if owner:
                holders[owner] = holders.get(owner, 0) + amount

        sorted_holders = sorted(
            holders.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return sorted_holders[:limit], None

    except requests.RequestException:
        return None, "Could not connect to Helius."
