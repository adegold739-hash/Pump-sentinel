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

SOL_MINT = "So11111111111111111111111111111111111111112"

app = Flask(__name__)


# =========================================================
# WEB SERVER
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
        use_reloader=False,
    )


# =========================================================
# GENERAL HELPERS
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
            return None, (
                f"Helius request failed "
                f"(HTTP {response.status_code})."
            )

        data = response.json()

        if "error" in data:
            error = data["error"]

            if isinstance(error, dict):
                return None, error.get(
                    "message",
                    "Helius returned an error.",
                )

            return None, str(error)

        return data.get("result"), None

    except requests.RequestException as error:
        return None, f"Network error: {error}"

    except ValueError:
        return None, "Helius returned invalid JSON."


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
    context: ContextTypes.DEFAULT_TYPE,
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
    context: ContextTypes.DEFAULT_TYPE,
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
    context: ContextTypes.DEFAULT_TYPE,
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n/watch <token_address>"
        )
        return

    token_address = context.args[0].strip()

    if len(token_address) < 30:
        await update.message.reply_text(
            "❌ That doesn't look like a valid "
            "Solana token address."
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
    context: ContextTypes.DEFAULT_TYPE,
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
        parse_mode="Markdown",
    )


# =========================================================
# /INFO
# =========================================================

async def info_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
            "id": token_address,
        },
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
    context: ContextTypes.DEFAULT_TYPE,
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
                "limit": 10,
            },
        ],
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

    for number, transaction in enumerate(
        result,
        start=1,
    ):
        signature = transaction.get(
            "signature",
            "",
        )

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
        parse_mode="Markdown",
    )


# =========================================================
# TRANSACTION HELPERS
# =========================================================

def get_fee_payer(transaction):
    message = transaction.get(
        "transaction",
        {},
    ).get(
        "message",
        {},
    )

    account_keys = message.get(
        "accountKeys",
        [],
    )

    for key in account_keys:
        if isinstance(key, dict) and key.get("signer"):
            return key.get("pubkey")

    if not account_keys:
        return None

    first = account_keys[0]

    if isinstance(first, dict):
        return first.get("pubkey")

    return first


def get_account_keys(transaction):
    message = transaction.get(
        "transaction",
        {},
    ).get(
        "message",
        {},
    )

    return message.get(
        "accountKeys",
        [],
    )


def get_token_balance_changes(transaction):
    meta = transaction.get("meta") or {}

    pre_balances = meta.get(
        "preTokenBalances",
        [],
    )

    post_balances = meta.get(
        "postTokenBalances",
        [],
    )

    pre_map = {}
    post_map = {}

    for balance in pre_balances:
        account_index = balance.get(
            "accountIndex",
        )
        pre_map[account_index] = balance

    for balance in post_balances:
        account_index = balance.get(
            "accountIndex",
        )
        post_map[account_index] = balance

    all_indexes = set(pre_map) | set(post_map)

    changes = []

    for account_index in all_indexes:
        pre = pre_map.get(
            account_index,
            {},
        )

        post = post_map.get(
            account_index,
            {},
        )

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

    pre_balances = meta.get(
        "preBalances",
        [],
    )

    post_balances = meta.get(
        "postBalances",
        [],
    )

    changes = []

    count = min(
        len(pre_balances),
        len(post_balances),
    )

    for index in range(count):
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

    return instruction.get("parsed")


def collect_instructions(transaction):
    message = transaction.get(
        "transaction",
        {},
    ).get(
        "message",
        {},
    )

    instructions = list(
        message.get("instructions", [])
    )

    meta = transaction.get("meta") or {}

    for group in meta.get(
        "innerInstructions",
        [],
    ):
        instructions.extend(
            group.get("instructions", [])
        )

    return instructions


# =========================================================
# TOKEN TRANSFER PARSER
# =========================================================

def collect_transfers(transaction):
    transfers = []

    for instruction in collect_instructions(transaction):
        parsed = extract_parsed_instruction(
            instruction
        )

        if not parsed:
            continue

        instruction_type = parsed.get("type")
        info = parsed.get("info", {})

        program = instruction.get("program")
        program_id = instruction.get("programId")

        is_token_program = (
            program in [
                "spl-token",
                "spl-token-2022",
            ]
            or program_id in [
                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnB4jM8y7D4c7c",
            ]
        )

        if not is_token_program:
            continue

        if instruction_type not in [
            "transfer",
            "transferChecked",
        ]:
            continue

        source = info.get("source")
        destination = info.get("destination")
        authority = (
            info.get("authority")
            or info.get("owner")
        )

        token_amount = info.get("amount")

        if token_amount is None:
            token_amount = (
                info.get("tokenAmount", {})
                .get("uiAmount")
            )

        decimals = (
            info.get("decimals")
            or info.get("tokenAmount", {})
            .get("decimals")
        )

        if decimals is not None:
            try:
                display_amount = (
                    float(token_amount) /
                    (10 ** int(decimals))
                )
            except (
                TypeError,
                ValueError,
            ):
                display_amount = token_amount
        else:
            display_amount = token_amount

        transfers.append({
            "source": source,
            "destination": destination,
            "authority": authority,
            "amount": token_amount,
            "display_amount": display_amount,
            "mint": info.get("mint"),
            "decimals": decimals,
        })

    return transfers


# =========================================================
# TRANSACTION INTELLIGENCE
# =========================================================

def analyze_transaction(transaction):
    fee_payer = get_fee_payer(transaction)

    meta = transaction.get("meta") or {}

    fee_lamports = meta.get(
        "fee",
        0,
    )

    fee_sol = fee_lamports / 1_000_000_000

    status = (
        "FAILED ❌"
        if meta.get("err")
        else "SUCCESS ✅"
    )

    token_changes = get_token_balance_changes(
        transaction
    )

    sol_changes = get_sol_balance_changes(
        transaction
    )

    transfers = collect_transfers(
        transaction
    )

    return {
        "status": status,
        "fee_payer": fee_payer,
        "fee_lamports": fee_lamports,
        "fee_sol": fee_sol,
        "token_changes": token_changes,
        "sol_changes": sol_changes,
        "transfers": transfers,
    }


def format_transaction_report(
    signature,
    transaction,
):
    analysis = analyze_transaction(
        transaction
    )

    lines = [
        "🔬 Transaction Intelligence",
        "",
        f"📊 Status: {analysis['status']}",
        f"💸 Fee: {analysis['fee_lamports']:,} lamports "
        f"({analysis['fee_sol']:.9f} SOL)",
        "",
        "👤 Fee payer:",
        shorten_address(
            analysis["fee_payer"],
            10,
        ),
    ]

    transfers = analysis["transfers"]

    if transfers:
        lines.extend([
            "",
            "🪙 Token Transfers:",
        ])

        for transfer in transfers[:10]:
            amount = transfer.get(
                "display_amount"
            )

            source = shorten_address(
                transfer.get("source"),
                6,
            )

            destination = shorten_address(
                transfer.get("destination"),
                6,
            )

            lines.append(
                f"• {amount} | "
                f"{source} → {destination}"
            )

    sol_changes = [
        change
        for change in analysis["sol_changes"]
        if abs(change["net_sol"]) > 0
    ]

    if sol_changes:
        lines.extend([
            "",
            "◎ SOL Balance Changes:",
        ])

        for change in sol_changes[:10]:
            lines.append(
                f"• Account #{change['account_index']}: "
                f"{format_sol(change['net_sol'])}"
            )

    lines.extend([
        "",
        "🧾 Signature:",
        signature,
    ])

    return "\n".join(lines)


# =========================================================
# /TX
# =========================================================

async def tx_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n/tx <transaction_signature>"
        )
        return

    signature = context.args[0].strip()

    if len(signature) < 40:
        await update.message.reply_text(
            "❌ That doesn't look like a valid "
            "Solana transaction signature."
        )
        return

    result, error = helius_rpc(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
            },
        ],
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

    report = format_transaction_report(
        signature,
        result,
    )

    await update.message.reply_text(
        report
    )


# =========================================================
# BOT STARTUP
# =========================================================

def create_application():
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
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "ping",
            ping_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "watch",
            watch_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "list",
            list_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "info",
            info_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "activity",
            activity_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "tx",
            tx_command,
        )
    )

    return application


def main():
    print("Starting Pump Sentinel...")

    init_database()

    web_thread = threading.Thread(
        target=run_web_server,
        daemon=True,
    )

    web_thread.start()

    application = create_application()

    print("Telegram bot starting...")
    print(
        f"Helius: "
        f"{'CONNECTED' if HELIUS_API_KEY else 'MISSING'}"
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
