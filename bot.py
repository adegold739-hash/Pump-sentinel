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

from database import (
    init_database,
    add_token,
    get_tokens,
)


# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

HELIUS_URL = (
    "https://mainnet.helius-rpc.com/"
    f"?api-key={HELIUS_API_KEY}"
)

app = Flask(__name__)


# =========================================================
# BASIC WEB SERVER
# =========================================================

@app.route("/")
def home():
    return "Pump Sentinel is running."


@app.route("/health")
def health():
    return "OK"


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False
    )


# =========================================================
# HELPERS
# =========================================================

def shorten_address(address, length=8):
    if not address:
        return "Unknown"

    if len(address) <= length * 2:
        return address

    return f"{address[:length]}...{address[-length:]}"


def format_sol(amount):
    if amount is None:
        return "0 SOL"

    return f"{amount:,.9f} SOL"


def helius_rpc(method, params):
    if not HELIUS_API_KEY:
        return None, "Helius API key is missing."

    try:
        response = requests.post(
            HELIUS_URL,
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

    except requests.RequestException as error:
        return None, f"Network error: {error}"


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "🟢 Pump Sentinel\n\n"
        "Your Solana memecoin risk-monitoring bot is online.\n\n"
        "Commands:\n"
        "/status - Check bot status\n"
        "/ping - Test Telegram\n"
        "/watch <token> - Watch a token\n"
        "/list - List watched tokens\n"
        "/info <token> - Token information\n"
        "/activity <token> - Recent transactions\n"
        "/tx <signature> - Transaction intelligence"
    )


# =========================================================
# /PING
# =========================================================

async def ping_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "🏓 Pong!\n\n"
        "Telegram connection is working."
    )


# =========================================================
# /STATUS
# =========================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    telegram_status = (
        "ONLINE ✅"
        if TELEGRAM_BOT_TOKEN
        else "MISSING ❌"
    )

    helius_status = (
        "CONNECTED ✅"
        if HELIUS_API_KEY
        else "MISSING ❌"
    )

    await update.message.reply_text(
        "🟢 Pump Sentinel\n\n"
        f"Telegram: {telegram_status}\n"
        f"Helius: {helius_status}"
    )


# =========================================================
# /WATCH
# =========================================================

async def watch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n/watch <token_address>"
        )
        return

    token_address = context.args[0].strip()

    if len(token_address) < 30:
        await update.message.reply_text(
            "❌ That doesn't look like a valid Solana token address."
        )
        return

    added = add_token(token_address)

    if added:
        await update.message.reply_text(
            "👁️ Token added to watchlist.\n\n"
            f"🎯 {token_address}"
        )
    else:
        await update.message.reply_text(
            "ℹ️ That token is already being watched."
        )


# =========================================================
# /LIST
# =========================================================

async def list_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    tokens = get_tokens()

    if not tokens:
        await update.message.reply_text(
            "📭 Your watchlist is empty."
        )
        return

    message = "👁️ Watched Tokens\n\n"

    for number, token in enumerate(tokens, start=1):
        message += (
            f"{number}. {shorten_address(token, 10)}\n"
            f"`{token}`\n\n"
        )

    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )


# =========================================================
# /INFO
# =========================================================

async def info_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n/info <token_address>"
        )
        return

    token_address = context.args[0].strip()

    result, error = helius_rpc(
        "getAsset",
        {
            "id": token_address
        }
    )

    if error:
        await update.message.reply_text(
            f"❌ {error}"
        )
        return

    if not result:
        await update.message.reply_text(
            "❌ Token was not found."
        )
        return

    token_info = result.get("token_info", {})
    content = result.get("content", {})
    metadata = content.get("metadata", {})

    name = metadata.get("name", "Unknown")
    symbol = metadata.get("symbol", "Unknown")
    decimals = token_info.get("decimals", "Unknown")
    supply = token_info.get("supply", "Unknown")

    await update.message.reply_text(
        "🪙 Token Intelligence\n\n"
        f"Name: {name}\n"
        f"Symbol: {symbol}\n"
        f"Decimals: {decimals}\n"
        f"Supply: {supply}\n\n"
        f"Address:\n{token_address}"
    )


# =========================================================
# /ACTIVITY
# =========================================================

async def activity_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n/activity <token_address>"
        )
        return

    token_address = context.args[0].strip()

    result, error = helius_rpc(
        "getSignaturesForAddress",
        [
            token_address,
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
            "No recent activity found."
        )
        return

    message = (
        "📡 Recent Activity\n\n"
        f"Token: {shorten_address(token_address, 10)}\n\n"
    )

    for number, transaction in enumerate(result, start=1):
        signature = transaction.get("signature", "")
        status = (
            "❌ FAILED"
            if transaction.get("err")
            else "✅ SUCCESS"
        )

        message += (
            f"{number}. {status}\n"
            f"`{signature}`\n\n"
        )

    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )


# =========================================================
# TRANSACTION HELPERS
# =========================================================

def get_fee_payer(transaction):
    message = transaction.get("transaction", {}).get(
        "message",
        {}
    )

    account_keys = message.get("accountKeys", [])

    for key in account_keys:
        if isinstance(key, dict):
            if key.get("signer"):
                return key.get("pubkey")

    if account_keys:
        first = account_keys[0]

        if isinstance(first, dict):
            return first.get("pubkey")

        return first

    return None


def get_account_keys(transaction):
    message = transaction.get("transaction", {}).get(
        "message",
        {}
    )

    return message.get("accountKeys", [])


def get_token_balance_changes(transaction):
    meta = transaction.get("meta") or {}

    pre_balances = meta.get("preTokenBalances", [])
    post_balances = meta.get("postTokenBalances", [])

    pre_map = {}
    post_map = {}

    for balance in pre_balances:
        account_index = balance.get("accountIndex")

        pre_map[account_index] = balance

    for balance in post_balances:
        account_index = balance.get("accountIndex")

        post_map[account_index] = balance

    all_indexes = set(pre_map) | set(post_map)

    changes = []

    for account_index in all_indexes:
        pre = pre_map.get(account_index, {})
        post = post_map.get(account_index, {})

        mint = (
            post.get("mint")
            or pre.get("mint")
        )

        owner = (
            post.get("owner")
            or pre.get("owner")
        )

        pre_amount = (
            pre.get("uiTokenAmount", {})
            .get("uiAmount")
            or 0
        )

        post_amount = (
            post.get("uiTokenAmount", {})
            .get("uiAmount")
            or 0
        )

        net_change = post_amount - pre_amount

        changes.append({
            "account_index": account_index,
            "mint": mint,
            "owner": owner,
            "before": pre_amount,
            "after": post_amount,
            "net": net_change,
        })

    return changes


def get_sol_balance_changes(transaction):
    meta = transaction.get("meta") or {}

    pre_balances = meta.get("preBalances", [])
    post_balances = meta.get("postBalances", [])

    changes = []

    for index in range(
        min(len(pre_balances), len(post_balances))
    ):
        pre = pre_balances[index]
        post = post_balances[index]

        net_lamports = post - pre
        net_sol = net_lamports / 1_000_000_000

        changes.append({
            "account_index": index,
            "net_sol": net_sol,
        })

    return changes


def extract_parsed_instruction(instruction):
    if not isinstance(instruction, dict):
        return None

    parsed = instruction.get("parsed")

    if not parsed:
        return None

    return parsed


def collect_instructions(transaction):
    message = transaction.get("transaction", {}).get(
        "message",
        {}
    )

    instructions = []

    for instruction in message.get(
        "instructions",
        []
    ):
        instructions.append(instruction)

    meta = transaction.get("meta") or {}

    inner_instructions = meta.get(
        "innerInstructions",
        []
    )

    for group in inner_instructions:
        for instruction in group.get(
            "instructions",
            []
        ):
            instructions.append(instruction)

    return instructions


def collect_transfers(transaction):
    transfers = []

    instructions = collect_instructions(
        transaction
    )

    for instruction in instructions:
        parsed = extract_parsed_instruction(
            instruction
        )

        if not parsed:
            continue

        instruction_type = parsed.get("type")
        info = parsed.get("info", {})

        if instruction_type in [
            "transfer",
            "transferChecked"
        ]:
            source = (
                info.get("source")
                or info.get("from")
            )

            destination = (
                info.get("destination")
                or info.get("to")
            )

            amount = (
                info.get("amount")
                or info.get("tokenAmount", {})
                .get("uiAmount")
            )

            mint = info.get("mint")

            transfers.append({
                "type": instruction_type,
                "from": source,
                "to": destination,
                "amount": amount,
                "mint": mint,
                "authority": info.get(
                    "authority"
                ),
            })

    return transfers


# =========================================================
# TRADE CLASSIFICATION
# =========================================================

def classify_trade(
    transaction,
    fee_payer
):
    token_changes = get_token_balance_changes(
        transaction
    )

    sol_changes = get_sol_balance_changes(
        transaction
    )

    account_keys = get_account_keys(
        transaction
    )

    wallet_sol_change = 0

    for change in sol_changes:
        index = change["account_index"]

        if index >= len(account_keys):
            continue

        account = account_keys[index]

        if isinstance(account, dict):
            address = account.get("pubkey")
        else:
            address = account

        if address == fee_payer:
            wallet_sol_change = change["net_sol"]
            break

    wallet_token_changes = []

    for change in token_changes:
        if change["owner"] == fee_payer:
            wallet_token_changes.append(change)

    non_sol_changes = [
        change
        for change in token_changes
        if change["mint"] !=
        "So11111111111111111111111111111111111111112"
    ]

    target_change = None

    for change in wallet_token_changes:
        if change["mint"] != (
            "So11111111111111111111111111111111111111112"
        ):
            target_change = change
            break

    if not target_change and wallet_token_changes:
        target_change = wallet_token_changes[0]

    if not target_change and non_sol_changes:
        target_change = non_sol_changes[0]

    if not target_change:
        return {
            "type": "⚪ UNCLEAR",
            "target_mint": None,
            "wallet_sol_change": wallet_sol_change,
            "wallet_token_change": 0,
            "position_before": None,
            "position_after": None,
            "position_percentage": None,
            "position_impact": "Unknown",
        }

    token_change = target_change["net"]

    position_before = target_change["before"]
    position_after = target_change["after"]

    position_percentage = None
    position_impact = "Unknown"

    if token_change < 0 and position_before > 0:
        amount_sold = abs(token_change)

        position_percentage = (
            amount_sold / position_before
        ) * 100

        if position_percentage < 5:
            position_impact = "🟢 Small position reduction"
        elif position_percentage < 20:
            position_impact = "🟡 Notable position reduction"
        elif position_percentage < 50:
            position_impact = "🟠 Large position reduction"
        else:
            position_impact = "🔴 Major position reduction"

    if token_change > 0 and wallet_sol_change < 0:
        trade_type = "🟢 POSSIBLE BUY"

    elif token_change < 0 and wallet_sol_change > 0:
        trade_type = "🔴 POSSIBLE SELL"

    else:
        trade_type = "⚪ UNCLEAR"

    return {
        "type": trade_type,
        "target_mint": target_change["mint"],
        "wallet_sol_change": wallet_sol_change,
        "wallet_token_change": token_change,
        "position_before": position_before,
        "position_after": position_after,
        "position_percentage": position_percentage,
        "position_impact": position_impact,
    }


# =========================================================
# /TX
# =========================================================

async def tx_command(
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

    status = (
        "❌ FAILED"
        if meta.get("err")
        else "✅ SUCCESS"
    )

    slot = result.get("slot", "Unknown")
    block_time = result.get(
        "blockTime",
        "Unknown"
    )

    fee = meta.get("fee", 0)

    fee_sol = fee / 1_000_000_000

    fee_payer = get_fee_payer(result)

    analysis = classify_trade(
        result,
        fee_payer
    )

    token_changes = get_token_balance_changes(
        result
    )

    sol_changes = get_sol_balance_changes(
        result
    )

    transfers = collect_transfers(
        result
    )

    account_keys = get_account_keys(
        result
    )

    message = (
        "🔬 Transaction Intelligence\n\n"
        f"📊 Status: {status}\n"
        f"🧱 Slot: {slot}\n"
        f"⏱️ Block time: {block_time}\n"
        f"💸 Fee: {fee:,} lamports "
        f"({fee_sol:.9f} SOL)\n\n"
    )

    message += (
        "👤 Fee payer:\n"
        f"{fee_payer or 'Unknown'}\n\n"
    )

    # -----------------------------------------------------
    # TRADE ANALYSIS
    # -----------------------------------------------------

    message += "🧠 Trade Analysis:\n"
    message += f"{analysis['type']}\n"

    if analysis["target_mint"]:
        message += (
            "🎯 Target mint:\n"
            f"{analysis['target_mint']}\n"
        )

    message += (
        "💰 Wallet SOL change: "
        f"{analysis['wallet_sol_change']:.9f} SOL\n"
    )

    message += (
        "🪙 Wallet token change: "
        f"{analysis['wallet_token_change']:,.6f}\n"
    )

    # -----------------------------------------------------
    # POSITION IMPACT
    # -----------------------------------------------------

    if analysis["position_before"] is not None:
        message += "\n"
        message += "📐 Position Impact:\n"

        message += (
            "Before: "
            f"{analysis['position_before']:,.6f}\n"
        )

        message += (
            "After: "
            f"{analysis['position_after']:,.6f}\n"
        )

        if analysis["position_percentage"] is not None:
            message += (
                "Position sold: "
                f"{analysis['position_percentage']:.2f}%\n"
            )

        message += (
            f"Impact: "
            f"{analysis['position_impact']}\n"
        )

    # -----------------------------------------------------
    # TOKEN BALANCES
    # -----------------------------------------------------

    if token_changes:
        message += "\n📈 Token Balance Changes:\n\n"

        for change in token_changes:
            message += (
                f"Mint: "
                f"{shorten_address(change['mint'], 10)}\n"
            )

            message += (
                f"Account: "
                f"{shorten_address(str(change['account_index']), 10)}\n"
            )

            if change["owner"]:
                message += (
                    f"Owner: "
                    f"{shorten_address(change['owner'], 10)}\n"
                )

            message += (
                f"Before: "
                f"{change['before']:,.6f}\n"
            )

            message += (
                f"After: "
                f"{change['after']:,.6f}\n"
            )

            message += (
                f"Net: "
                f"{change['net']:+,.6f}\n\n"
            )

    # -----------------------------------------------------
    # SOL BALANCES
    # -----------------------------------------------------

    if sol_changes:
        message += "💰 SOL Balance Changes:\n\n"

        for change in sol_changes:
            index = change["account_index"]

            if index < len(account_keys):
                account = account_keys[index]

                if isinstance(account, dict):
                    address = account.get(
                        "pubkey",
                        "Unknown"
                    )
                else:
                    address = account
            else:
                address = "Unknown"

            message += (
                f"Account: "
                f"{shorten_address(address, 10)}\n"
                f"Net: "
                f"{change['net_sol']:+.9f} SOL\n\n"
            )

    # -----------------------------------------------------
    # TRANSFERS
    # -----------------------------------------------------

    if transfers:
        message += "🪙 Token Transfers:\n\n"

        for number, transfer in enumerate(
            transfers,
            start=1
        ):
            message += (
                f"{number}. "
                f"Amount: {transfer['amount']}\n"
            )

            if transfer["mint"]:
                message += (
                    "Mint: "
                    f"{shorten_address(transfer['mint'], 10)}\n"
                )

            if transfer["from"]:
                message += (
                    "From: "
                    f"{shorten_address(transfer['from'], 10)}\n"
                )

            if transfer["to"]:
                message += (
                    "To: "
                    f"{shorten_address(transfer['to'], 10)}\n"
                )

            if transfer["authority"]:
                message += (
                    "Authority: "
                    f"{shorten_address(transfer['authority'], 10)}\n"
                )

            message += "\n"

    # -----------------------------------------------------
    # PROGRAMS
    # -----------------------------------------------------

    programs = []

    for instruction in collect_instructions(
        result
    ):
        program_id = instruction.get(
            "programId"
        )

        if program_id and program_id not in programs:
            programs.append(program_id)

    if programs:
        message += "🏗️ Programs Called:\n"

        for program in programs:
            message += (
                f"• {shorten_address(program, 10)}\n"
            )

        message += "\n"

    # -----------------------------------------------------
    # SIGNATURE
    # -----------------------------------------------------

    message += (
        "🔗 Signature:\n"
        f"{signature}"
    )

    # Telegram has a message-size limit.
    # Keep the important beginning if extremely large.
    if len(message) > 4000:
        message = message[:3950] + (
            "\n\n⚠️ Output shortened."
        )

    await update.message.reply_text(
        message
    )


# =========================================================
# MAIN
# =========================================================

def main():
    init_database()

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    # Flask runs in the background.
    # Telegram polling stays in the main thread.
    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "ping",
            ping_command
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )

    application.add_handler(
        CommandHandler(
            "watch",
            watch_command
        )
    )

    application.add_handler(
        CommandHandler(
            "list",
            list_command
        )
    )

    application.add_handler(
        CommandHandler(
            "info",
            info_command
        )
    )

    application.add_handler(
        CommandHandler(
            "activity",
            activity_command
        )
    )

    application.add_handler(
        CommandHandler(
            "tx",
            tx_command
        )
    )

    print("🟢 Pump Sentinel Telegram bot is running.")

    application.run_polling()


if __name__ == "__main__":
    main()
