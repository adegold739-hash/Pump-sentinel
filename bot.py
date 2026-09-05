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
                    "destination": info.get(
                        "destination"
                    ),
                    "lamports": lamports,
                    "location": item["location"],
                    "group": item["group"],
                })

        # =========================
        # SPL TOKEN
        # =========================

        if (
            program == "spl-token"
            and instruction_type in (
                "transfer",
                "transferChecked",
            )
        ):
            token_amount = info.get(
                "tokenAmount",
                {}
            )

            if not isinstance(
                token_amount,
                dict
            ):
                token_amount = {}

            raw_amount = info.get("amount")

            if raw_amount is None:
                raw_amount = token_amount.get(
                    "amount"
                )

            decimals = token_amount.get(
                "decimals"
            )

            ui_amount = token_amount.get(
                "uiAmount"
            )

            if (
                ui_amount is None
                and raw_amount is not None
            ):
                try:
                    if decimals is not None:
                        ui_amount = (
                            int(raw_amount)
                            / (
                                10
                                ** int(decimals)
                            )
                        )
                    else:
                        ui_amount = raw_amount
                except (
                    ValueError,
                    TypeError,
                    ZeroDivisionError
                ):
                    ui_amount = raw_amount

            token_transfers.append({
                "source": info.get("source"),
                "destination": info.get(
                    "destination"
                ),
                "authority": info.get(
                    "authority"
                ),
                "mint": info.get("mint"),
                "amount": raw_amount,
                "decimals": decimals,
                "ui_amount": ui_amount,
                "location": item["location"],
                "group": item["group"],
                "type": instruction_type,
            })

    return sol_transfers, token_transfers


# =========================
# FEE PAYER
# =========================

def get_fee_payer(transaction):
    message = (
        transaction
        .get("transaction", {})
        .get("message", {})
    )

    account_keys = (
        message.get("accountKeys", [])
        or []
    )

    if not account_keys:
        return None

    first = account_keys[0]

    if isinstance(first, dict):
        return first.get("pubkey")

    return first


# =========================
# WALLET TOKEN ACCOUNTS
# =========================

def get_wallet_token_accounts(wallet):
    if not wallet:
        return {}, None

    result, error = helius_rpc(
        "getTokenAccountsByOwner",
        [
            wallet,
            {
                "programId":
                    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
            },
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed"
            }
        ]
    )

    if error:
        return {}, error

    accounts = {}

    values = []

    if isinstance(result, dict):
        values = result.get(
            "value",
            []
        )

    for account in values:
        if not isinstance(
            account,
            dict
        ):
            continue

        token_account = account.get(
            "pubkey"
        )

        account_data = (
            account
            .get("account", {})
            .get("data", {})
        )

        parsed = account_data.get(
            "parsed",
            {}
        )

        info = parsed.get(
            "info",
            {}
        )

        if not token_account:
            continue

        accounts[token_account] = {
            "mint": info.get("mint"),
            "owner": info.get("owner"),
            "amount": (
                info
                .get("tokenAmount", {})
                .get("amount")
            ),
            "ui_amount": (
                info
                .get("tokenAmount", {})
                .get("uiAmount")
            ),
        }

    return accounts, None


# =========================
# WALLET FLOW ANALYSIS
# =========================

def analyze_wallet_flow(
    wallet,
    target_mint,
    sol_transfers,
    token_transfers,
    wallet_token_accounts
):
    wallet_token_addresses = set(
        wallet_token_accounts.keys()
    )

    sol_out = 0
    sol_in = 0

    target_out = 0
    target_in = 0

    relevant_token_transfers = []

    # =========================
    # SOL FLOW
    # =========================

    for transfer in sol_transfers:
        source = transfer.get("source")
        destination = transfer.get(
            "destination"
        )
        lamports = transfer.get(
            "lamports",
            0
        )

        try:
            lamports = int(lamports)
        except (
            TypeError,
            ValueError
        ):
            continue

        if source == wallet:
            sol_out += lamports

        if destination == wallet:
            sol_in += lamports

    # =========================
    # TARGET TOKEN FLOW
    # =========================

    for transfer in token_transfers:
        mint = transfer.get("mint")

        if mint != target_mint:
            continue

        source = transfer.get("source")
        destination = transfer.get(
            "destination"
        )

        amount = transfer.get(
            "ui_amount"
        )

        try:
            amount = float(amount)
        except (
            TypeError,
            ValueError
        ):
            continue

        source_belongs_to_wallet = (
            source in wallet_token_addresses
        )

        destination_belongs_to_wallet = (
            destination in wallet_token_addresses
        )

        if source_belongs_to_wallet:
            target_out += amount

        if destination_belongs_to_wallet:
            target_in += amount

        if (
            source_belongs_to_wallet
            or destination_belongs_to_wallet
        ):
            relevant_token_transfers.append(
                transfer
            )

    net_sol = sol_in - sol_out
    net_target = target_in - target_out

    # =========================
    # CLASSIFICATION
    # =========================

    classification = "⚪ UNCLEAR"

    # User pays SOL and receives target token
    if (
        sol_out > 0
        and target_in > 0
        and target_out == 0
    ):
        classification = "🟢 POSSIBLE BUY"

    # User sends target token and receives SOL
    elif (
        target_out > 0
        and sol_in > 0
        and target_in == 0
    ):
        classification = "🔴 POSSIBLE SELL"

    return {
        "classification": classification,
        "sol_out": sol_out,
        "sol_in": sol_in,
        "net_sol": net_sol,
        "target_out": target_out,
        "target_in": target_in,
        "net_target": net_target,
        "relevant_token_transfers":
            relevant_token_transfers,
    }


# =========================
# /START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "🟢 Pump Sentinel\n\n"
        "Your Solana memecoin monitoring system "
        "is online.\n\n"
        "Commands:\n"
        "/ping - Test bot\n"
        "/status - Check systems\n"
        "/watch <token> - Watch a token\n"
        "/list - List watched tokens\n"
        "/info <token> - Token information\n"
        "/activity <address> - Recent activity\n"
        "/tx <signature> - Inspect transaction"
    )


# =========================
# /PING
# =========================

async def ping(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "🏓 Pong! Pump Sentinel is alive."
    )


# =========================
# /STATUS
# =========================

async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    telegram_status = "ONLINE ✅"

    if HELIUS_API_KEY:
        helius_status = "CONNECTED ✅"
    else:
        helius_status = "MISSING ❌"

    await update.message.reply_text(
        "🟢 Pump Sentinel\n\n"
        f"Telegram: {telegram_status}\n"
        f"Helius: {helius_status}"
    )


# =========================
# /WATCH
# =========================

async def watch(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n/watch <token_address>"
        )
        return

    token_address = context.args[0].strip()

    added = add_token(token_address)

    if added:
        await update.message.reply_text(
            "👁️ Token added to watchlist.\n\n"
            f"Token:\n{token_address}"
        )
    else:
        await update.message.reply_text(
            "⚠️ That token is already being watched."
        )


# =========================
# /LIST
# =========================

async def list_tokens(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    tokens = get_tokens()

    if not tokens:
        await update.message.reply_text(
            "📭 Watchlist is empty."
        )
        return

    message = "👁️ Watched Tokens\n\n"

    for index, token in enumerate(
        tokens,
        start=1
    ):
        message += (
            f"{index}. {token}\n"
        )

    await update.message.reply_text(
        message
    )


# =========================
# /INFO
# =========================

async def info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n/info <token_address>"
        )
        return

    token_address = context.args[0].strip()

    token_info, error = get_token_info(
        token_address
    )

    if error:
        await update.message.reply_text(
            f"❌ {error}"
        )
        return

    message = (
        "🪙 Token Information\n\n"
        f"Name: {token_info.get('name')}\n"
        f"Symbol: {token_info.get('symbol')}\n"
        f"Address:\n"
        f"{token_info.get('address')}\n\n"
        f"Supply: {token_info.get('supply')}\n"
        f"Decimals: "
        f"{token_info.get('decimals')}"
    )

    await update.message.reply_text(
        message
    )


# =========================
# /ACTIVITY
# =========================

async def activity(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n/activity <wallet_or_address>"
        )
        return

    address = context.args[0].strip()

    result, error = helius_rpc(
        "getSignaturesForAddress",
        [
            address,
            {
                "limit": 10
            }
        ]
    )

    if error:
        await update.message.reply_text(
            f"❌ {error}"
        )
        return

    if not result:
        await update.message.reply_text(
            "📭 No recent activity found."
        )
        return

    message = "📊 Recent Activity\n\n"

    for index, tx_data in enumerate(
        result,
        start=1
    ):
        signature = tx_data.get(
            "signature",
            "Unknown"
        )

        slot = tx_data.get(
            "slot",
            "Unknown"
        )

        err = tx_data.get("err")

        status_text = (
            "❌ FAILED"
            if err
            else "✅ SUCCESS"
        )

        message += (
            f"{index}. {status_text}\n"
            f"Slot: {slot}\n"
            f"TX:\n{signature}\n\n"
        )

    await update.message.reply_text(
        message
    )


# =========================
# /TX
# =========================

async def tx(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n/tx <transaction_signature>"
        )
        return

    signature = context.args[0].strip()

    result, error = helius_rpc(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    )

    if error:
        await update.message.reply_text(
            f"❌ {error}"
        )
        return

    if not result:
        await update.message.reply_text(
            "❌ Transaction not found."
        )
        return

    meta = result.get("meta") or {}

    status_text = (
        "❌ FAILED"
        if meta.get("err")
        else "✅ SUCCESS"
    )

    slot = result.get(
        "slot",
        "Unknown"
    )

    block_time = result.get(
        "blockTime",
        "Unknown"
    )

    fee = meta.get(
        "fee",
        0
    )

    # =========================
    # TRANSFERS
    # =========================

    sol_transfers, token_transfers = (
        collect_transfers(result)
    )

    # =========================
    # FEE PAYER
    # =========================

    fee_payer = get_fee_payer(
        result
    )

    # =========================
    # TARGET MINT
    # =========================

    target_mints = []

    for transfer in token_transfers:
        mint = transfer.get("mint")

        if (
            mint
            and mint !=
            "So11111111111111111111111111111111111111112"
            and mint not in target_mints
        ):
            target_mints.append(mint)

    # =========================
    # WALLET ACCOUNTS
    # =========================

    wallet_accounts = {}
    wallet_error = None

    if fee_payer:
        wallet_accounts, wallet_error = (
            get_wallet_token_accounts(
                fee_payer
            )
        )

    # =========================
    # ANALYSIS
    # =========================

    analysis = None

    if (
        fee_payer
        and target_mints
        and wallet_accounts is not None
    ):
        # For now use the first non-SOL mint.
        target_mint = target_mints[0]

        analysis = analyze_wallet_flow(
            fee_payer,
            target_mint,
            sol_transfers,
            token_transfers,
            wallet_accounts
        )

    # =========================
    # MESSAGE
    # =========================

    message = (
        "🔬 Transaction Intelligence\n\n"
        f"📊 Status: {status_text}\n"
        f"🧱 Slot: {slot}\n"
        f"⏱️ Block time: {block_time}\n"
        f"💸 Fee: {fee:,} lamports\n\n"
        f"👤 Fee payer:\n"
        f"{fee_payer or 'Unknown'}\n"
    )

    # =========================
    # CLASSIFICATION
    # =========================

    if analysis:
        message += (
            "\n🧠 Trade Analysis:\n"
            f"{analysis['classification']}\n"
        )

        message += (
            f"💰 SOL out: "
            f"{format_sol(analysis['sol_out']):.9f}\n"
            f"💰 SOL in: "
            f"{format_sol(analysis['sol_in']):.9f}\n"
            f"🪙 Token in: "
            f"{analysis['target_in']:,.6f}\n"
            f"🪙 Token out: "
            f"{analysis['target_out']:,.6f}\n"
        )

    elif wallet_error:
        message += (
            "\n🧠 Trade Analysis:\n"
            "⚪ UNCLEAR\n"
            f"Wallet lookup failed: "
            f"{wallet_error}\n"
        )

    else:
        message += (
            "\n🧠 Trade Analysis:\n"
            "⚪ UNCLEAR\n"
        )

    # =========================
    # SOL TRANSFERS
    # =========================

    if sol_transfers:
        message += "\n💰 SOL Transfers:\n"

        for index, transfer in enumerate(
            sol_transfers,
            start=1
        ):
            amount = format_sol(
                transfer["lamports"]
            )

            message += (
                f"\n{index}. "
                f"{amount:.9f} SOL\n"
                f"From: "
                f"{shorten_address(transfer.get('source'))}\n"
                f"To: "
                f"{shorten_address(transfer.get('destination'))}\n"
            )
    else:
        message += (
            "\n💰 SOL Transfers:\n"
            "None detected.\n"
        )

    # =========================
    # TOKEN TRANSFERS
    # =========================

    if token_transfers:
        message += "\n🪙 Token Transfers:\n"

        for index, transfer in enumerate(
            token_transfers,
            start=1
        ):
            amount = transfer.get(
                "ui_amount"
            )

            if amount is None:
                amount = transfer.get(
                    "amount",
                    "Unknown"
                )

            message += (
                f"\n{index}. Amount: {amount}\n"
                f"Mint: "
                f"{shorten_address(transfer.get('mint'))}\n"
                f"From: "
                f"{shorten_address(transfer.get('source'))}\n"
                f"To: "
                f"{shorten_address(transfer.get('destination'))}\n"
                f"Authority: "
                f"{shorten_address(transfer.get('authority'))}\n"
            )
    else:
        message += (
            "\n🪙 Token Transfers:\n"
            "None detected.\n"
        )

    # =========================
    # PROGRAMS
    # =========================

    programs = []

    outer_instructions = (
        result
        .get("transaction", {})
        .get("message", {})
        .get("instructions", [])
    )

    for instruction in (
        outer_instructions or []
    ):
        program_id = instruction.get(
            "programId"
        )

        if (
            program_id
            and program_id not in programs
        ):
            programs.append(program_id)

    for group in (
        meta.get("innerInstructions", [])
        or []
    ):
        for instruction in (
            group.get("instructions", [])
            or []
        ):
            program_id = instruction.get(
                "programId"
            )

            if (
                program_id
                and program_id not in programs
            ):
                programs.append(program_id)

    message += "\n🏗️ Programs Called:\n"

    for program_id in programs:
        message += (
            f"• {shorten_address(program_id, 12)}\n"
        )

    message += (
        "\n🔗 Signature:\n"
        f"{signature}"
    )

    # Telegram safety limit
    if len(message) > 4000:
        message = (
            message[:3950]
            + "\n\n…truncated."
        )

    await update.message.reply_text(
        message
    )


# =========================
# MAIN
# =========================

def main():
    init_database()

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("ping", ping)
    )

    application.add_handler(
        CommandHandler("status", status)
    )

    application.add_handler(
        CommandHandler("watch", watch)
    )

    application.add_handler(
        CommandHandler("list", list_tokens)
    )

    application.add_handler(
        CommandHandler("info", info)
    )

    application.add_handler(
        CommandHandler("activity", activity)
    )

    application.add_handler(
        CommandHandler("tx", tx)
    )

    application.run_polling()


if __name__ == "__main__":
    main()
