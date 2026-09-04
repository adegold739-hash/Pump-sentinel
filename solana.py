import os
import requests

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

HELIUS_URL = (
    "https://mainnet.helius-rpc.com/"
    f"?api-key={HELIUS_API_KEY}"
)


def get_token_info(token_address):
    if not HELIUS_API_KEY:
        return None, "Helius API key is missing."

    try:
        response = requests.post(
            HELIUS_URL,
            json={
                "jsonrpc": "2.0",
                "id": "pump-sentinel",
                "method": "getAsset",
                "params": {
                    "id": token_address
                }
            },
            timeout=15
        )

        if not response.ok:
            return None, "Helius request failed."

        data = response.json()

        if "error" in data:
            return None, "Token was not found."

        asset = data.get("result")

        if not asset:
            return None, "Token was not found."

        token_info = asset.get("token_info", {})
        content = asset.get("content", {})
        metadata = content.get("metadata", {})

        return {
            "address": token_address,
            "name": metadata.get("name", "Unknown"),
            "symbol": metadata.get("symbol", "Unknown"),
            "supply": token_info.get("supply"),
            "decimals": token_info.get("decimals"),
        }, None

    except requests.RequestException:
        return None, "Could not connect to Helius."
