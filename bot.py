import os
import threading
import requests

from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from database import init_database, add_token, get_tokens
from solana import get_token_info


# =========================
# CONFIG
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

app = Flask(__name__)


# =========================
# FLASK SERVER
# =========================

@app.route("/")
def home():
    return "Pump Sentinel is running."


@app.route("/health")
def health():
    return "OK"


def run_web_server():
    port = int(os.getenv("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False
    )


# =========================
# HELPERS
# =========================

def shorten_address(address, length=8):
    if not address:
        return "Unknown"

    if len(address) <= length * 2:
        return address

    return f"{address[:length]}...{address[-length:]}"


def helius_rpc(method, params):
    if not HELIUS_API_KEY:
        return None, "Helius API key is missing."

    url = (
        "https://mainnet.helius-rpc.com/"
        f"?api-key={HELIUS_API_KEY}"
    )

    try:
        response = requests.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": "pump-sentinel",
                "method": method,
                "params": params,
            },
            timeout=20,
        )

        if not response.ok:
            return None, "Helius request failed."

        data = response.json()

        if "error" in data:
            return None, data["error"].get(
                "message",
                "Helius returned an error."
            )

        return data.get("result"), None

    except requests.RequestException:
        return None, "Could not connect to Helius."


def format_sol(lamports):
    try:
        return lamports / 1_000_000_000
    except (TypeError, ValueError):
        return 0


# =========================
# TRANSACTION PARSING
# =========================

def extract_parsed_instruction(instruction):
    if not isinstance(instruction, dict):
        return None

    parsed = instruction.get("parsed")

    if not isinstance(parsed, dict):
        return None

    info = parsed.get("info", {})

    if not isinstance(info, dict):
        info = {}

    return {
        "program": instruction.get(
            "program",
            "unknown"
        ),
        "program_id": instruction.get(
            "programId"
        ),
        "type": parsed.get(
            "type",
            "unknown"
        ),
        "info": info,
    }


def collect_instructions(transaction):
    message = (
        transaction
        .get("transaction", {})
        .get("message", {})
    )

    meta = transaction.get("meta") or {}

    instructions = []

    # Outer instructions
    for instruction in (
        message.get("instructions", [])
        or []
    ):
        parsed = extract_parsed_instruction(
            instruction
        )

        if parsed:
            instructions.append({
                "location": "outer",
                "group": None,
                "data": parsed,
            })

    # Inner instructions
    for group in (
        meta.get("innerInstructions", [])
        or []
    ):
        group_index = group.get("index")

        for instruction in (
            group.get("instructions", [])
            or []
        ):
            parsed = extract_parsed_instruction(
                instruction
            )

            if parsed:
                instructions.append({
                    "location": "inner",
                    "group": group_index,
                    "data": parsed,
                })

    return instructions


def collect_transfers(transaction):
    instructions = collect_instructions(
        transaction
    )

    sol_transfers = []
    token_transfers = []

    for item in instructions:
        data = item["data"]

        program = data["program"]
        instruction_type = data["type"]
        info = data["info"]

        # =========================
        # SOL
        # =========================

        if (
            program == "system"
            and instruction_type == "transfer"
        ):
            lamports = info.get("lamports")

            if lamports is not None:
                sol_transfers.append({
                    "source": info.get("source"),
