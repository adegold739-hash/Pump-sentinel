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
# ACCOUNT KEYS
# =========================

def get_account_keys(transaction):
    message = (
        transaction
        .get("transaction", {})
        .get("message", {})
    )

    keys = []

    for key in (
        message.get("accountKeys", [])
        or []
    ):
        if isinstance(key, dict):
            keys.append(
                key.get("pubkey")
            )
        else:
            keys.append(key)

    return keys


# =========================
# PRE/POST TOKEN BALANCES
# =========================

def get_token_balance_changes(transaction):
    meta = transaction.get("meta") or {}

    account_keys = get_account_keys(
        transaction
    )

    pre_balances = (
        meta.get("preTokenBalances", [])
        or []
    )

    post_balances = (
        meta.get("postTokenBalances", [])
        or []
    )

    accounts = {}

    # -------------------------
    # PRE BALANCES
    # -------------------------

    for balance in pre_balances:
        account_index = balance.get(
            "accountIndex"
        )

        if account_index is None:
            continue

        if account_index >= len(account_keys):
            continue

        account = account_keys[
            account_index
        ]

        mint = balance.get("mint")

        token_amount = (
            balance
            .get("uiTokenAmount", {})
        )

        amount = token_amount.get(
            "uiAmount"
        )

        if amount is None:
            amount = 0

        accounts[account] = {
            "account": account,
            "mint": mint,
            "owner": balance.get(
                "owner"
            ),
            "pre": amount,
            "post": 0,
        }

    # -------------------------
    # POST BALANCES
    # -------------------------

    for balance in post_balances:
        account_index = balance.get(
            "accountIndex"
        )

        if account_index is None:
            continue

        if account_index >= len(account_keys):
            continue

        account = account_keys[
            account_index
        ]

        mint = balance.get("mint")

        token_amount = (
            balance
            .get("uiTokenAmount", {})
        )

        amount = token_amount.get(
            "uiAmount"
        )

        if amount is None:
            amount = 0

        if account not in accounts:
            accounts[account] = {
                "account": account,
                "mint": mint,
                "owner": balance.get(
                    "owner"
                ),
                "pre": 0,
                "post": amount,
            }
        else:
            accounts[account]["post"] = amount

            if not accounts[account].get(
                "owner"
            ):
                accounts[account]["owner"] = (
                    balance.get("owner")
                )

    changes = []

    for account_data in accounts.values():
        pre = account_data.get(
            "pre",
            0
        )

        post = account_data.get(
            "post",
            0
        )

        try:
            net = float(post) - float(pre)
        except (
            TypeError,
            ValueError
        ):
            net = 0

        if net == 0:
            continue

        changes.append({
            "account":
                account_data.get(
                    "account"
                ),
            "mint":
                account_data.get(
                    "mint"
                ),
            "owner":
                account_data.get(
                    "owner"
                ),
            "pre": pre,
            "post": post,
            "net": net,
        })

    return changes


# =========================
# SOL BALANCE CHANGE
# =========================

def get_sol_balance_changes(transaction):
    meta = transaction.get("meta") or {}

    account_keys = get_account_keys(
        transaction
    )

    pre = (
        meta.get("preBalances", [])
        or []
    )

    post = (
        meta.get("postBalances", [])
        or []
    )

    changes = []

    count = min(
        len(account_keys),
        len(pre),
        len(post)
    )

    for index in range(count):
        try:
            difference = (
                int(post[index])
                - int(pre[index])
            )
        except (
            TypeError,
            ValueError
        ):
            continue

        if difference == 0:
            continue

        changes.append({
            "account":
                account_keys[index],
            "pre":
                pre[index],
            "post":
                post[index],
            "net":
                difference,
        })

    return changes


# =========================
# INSTRUCTION PARSER
# =========================

def extract_parsed_instruction(
    instruction
):
    if not isinstance(
        instruction,
        dict
    ):
        return None

    parsed = instruction.get(
        "parsed"
    )

    if not isinstance(
        parsed,
        dict
    ):
        return None

    info = parsed.get(
        "info",
        {}
    )

    if not isinstance(
        info,
        dict
    ):
        info = {}

    return {
        "program":
            instruction.get(
                "program",
                "unknown"
            ),
        "program_id":
            instruction.get(
                "programId"
            ),
        "type":
            parsed.get(
                "type",
                "unknown"
            ),
        "info": info,
    }


def collect_instructions(
    transaction
):
    message = (
        transaction
        .get("transaction", {})
        .get("message", {})
    )

    meta = transaction.get(
        "meta"
    ) or {}

    instructions = []

    for instruction in (
        message.get(
            "instructions",
            []
        )
        or []
    ):
        parsed = (
            extract_parsed_instruction(
                instruction
            )
        )

        if parsed:
            instructions.append({
                "location": "outer",
                "group": None,
                "data": parsed,
            })

    for group in (
        meta.get(
            "innerInstructions",
            []
        )
        or []
    ):
        group_index = group.get(
            "index"
        )

        for instruction in (
            group.get(
                "instructions",
                []
            )
            or []
        ):
            parsed = (
                extract_parsed_instruction(
                    instruction
                )
            )

            if parsed:
                instructions.append({
                    "location": "inner",
                    "group": group_index,
                    "data": parsed,
                })

    return instructions


# =========================
# TRANSFERS
# =========================

def collect_transfers(transaction):
    instructions = (
        collect_instructions(
            transaction
        )
    )

    sol_transfers = []
    token_transfers = []

    for item in instructions:
        data = item["data"]

        program = data["program"]
        instruction_type = data["type"]
        info = data["info"]

        # -------------------------
        # SOL TRANSFERS
        # -------------------------

        if (
            program == "system"
            and instruction_type == "transfer"
        ):
            lamports = info.get(
                "lamports"
            )

            if lamports is not None:
                sol_transfers.append({
                    "source":
                        info.get(
                            "source"
                        ),
                    "destination":
                        info.get(
                            "destination"
                        ),
                    "lamports":
                        lamports,
                })

        # -------------------------
        # TOKEN TRANSFERS
        # -------------------------

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

            amount = info.get(
                "amount"
            )

            if amount is None:
                amount = token_amount.get(
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
                and amount is not None
            ):
                try:
                    if decimals is not None:
                        ui_amount = (
                            int(amount)
                            / (
                                10
                                ** int(decimals)
                            )
                        )
                except (
                    ValueError,
                    TypeError,
                    ZeroDivisionError
                ):
                    ui_amount = None

            token_transfers.append({
                "source":
                    info.get("source"),
                "destination":
                    info.get("destination"),
                "authority":
                    info.get("authority"),
                "mint":
                    info.get("mint"),
                "amount":
                    amount,
                "ui_amount":
                    ui_amount,
            })

    return (
        sol_transfers,
        token_transfers
    )


# =========================
# TRADE CLASSIFICATION
# =========================

def classify_trade(
    wallet,
    target_mint,
    token_changes,
    sol_changes
):
    wallet_token_change = 0

    for change in token_changes:
        if change.get("mint") != target_mint:
            continue

        owner = change.get(
            "owner"
        )

        account = change.get(
            "account"
        )

        # Prefer explicit owner.
        if owner == wallet:
            wallet_token_change += change[
                "net"
            ]

        # Some RPC responses may not
        # contain owner. The fee payer
        # can still be associated with
        # the token account through
        # transaction-level evidence.
        elif not owner:
            wallet_token_change += 0

    wallet_sol_change = 0

    for change in sol_changes:
        if change.get("account") == wallet:
            wallet_sol_change += change[
                "net"
            ]

    # Ignore the normal transaction fee
    # when determining trade direction.
    #
    # The important question is whether
    # the wallet's SOL/token position moved
    # in opposite directions.

    if (
        wallet_sol_change < 0
        and wallet_token_change > 0
    ):
        return (
            "🟢 POSSIBLE BUY",
            wallet_sol_change,
            wallet_token_change
        )

    if (
        wallet_sol_change > 0
        and wallet_token_change < 0
    ):
        return (
            "🔴 POSSIBLE SELL",
            wallet_sol_change,
            wallet_token_change
        )

    return (
        "⚪ UNCLEAR",
        wallet_sol_change,
        wallet_token_change
    )


# =========================
# /START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "🟢 Pump Sentinel\n\n"
        "Your Solana memecoin monitoring "
        "system is online.\n\n"
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

    token_address = (
        context.args[0].strip()
    )

    added = add_token(
        token_address
    )

    if added:
        await update.message.reply_text(
            "👁️ Token added to watchlist.\n\n"
            f"Token:\n{token_address}"
        )
    else:
        await update.message.reply_text(
            "⚠️ That token is already "
            "being watched."
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

    message = (
        "👁️ Watched Tokens\n\n"
    )

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

    token_address = (
        context.args[0].strip()
    )

    token_info, error = (
        get_token_info(
            token_address
        )
    )

    if error:
        await update.message.reply_text(
            f"❌ {error}"
        )
        return

    message = (
        "🪙 Token Information\n\n"
        f"Name: "
        f"{token_info.get('name')}\n"
        f"Symbol: "
        f"{token_info.get('symbol')}\n"
        f"Address:\n"
        f"{token_info.get('address')}\n\n"
        f"Supply: "
        f"{token_info.get('supply')}\n"
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

    address = (
        context.args[0].strip()
    )

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

    message = (
        "📊 Recent Activity\n\n"
    )

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

        err = tx_data.get(
            "err"
        )

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

    signature = (
        context.args[0].strip()
    )

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

    meta = result.get(
        "meta"
    ) or {}

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
    # WALLET
    # =========================

    fee_payer = get_fee_payer(
        result
    )

    # =========================
    # BALANCE CHANGES
    # =========================

    token_changes = (
        get_token_balance_changes(
            result
        )
    )

    sol_changes = (
        get_sol_balance_changes(
            result
        )
    )

    # =========================
    # TARGET MINT
    # =========================

    target_mints = []

    for change in token_changes:
        mint = change.get(
            "mint"
        )

        if (
            mint
            and mint !=
            "So11111111111111111111111111111111111111112"
            and mint not in target_mints
        ):
            target_mints.append(
                mint
            )

    target_mint = (
        target_mints[0]
        if target_mints
        else None
    )

    # =========================
    # CLASSIFY
    # =========================

    classification = "⚪ UNCLEAR"
    wallet_sol_change = 0
    wallet_token_change = 0

    if (
        fee_payer
        and target_mint
    ):
        (
            classification,
            wallet_sol_change,
            wallet_token_change
        ) = classify_trade(
            fee_payer,
            target_mint,
            token_changes,
            sol_changes
        )

    # =========================
    # TRANSFERS
    # =========================

    sol_transfers, token_transfers = (
        collect_transfers(
            result
        )
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
        f"{fee_payer or 'Unknown'}\n\n"
        f"🧠 Trade Analysis:\n"
        f"{classification}\n"
    )

    if target_mint:
        message += (
            f"🎯 Target mint:\n"
            f"{target_mint}\n"
        )

    message += (
        f"💰 Wallet SOL change: "
        f"{format_sol(wallet_sol_change):.9f} SOL\n"
        f"🪙 Wallet token change: "
        f"{wallet_token_change:,.6f}\n"
    )

    # =========================
    # PRE/POST TOKEN CHANGES
    # =========================

    if token_changes:
        message += (
            "\n📈 Token Balance Changes:\n"
        )

        shown = 0

        for change in token_changes:
            if shown >= 10:
                break

            message += (
                f"\nMint: "
                f"{shorten_address(change.get('mint'))}\n"
                f"Account: "
                f"{shorten_address(change.get('account'))}\n"
                f"Owner: "
                f"{shorten_address(change.get('owner'))}\n"
                f"Before: "
                f"{change.get('pre')}\n"
                f"After: "
                f"{change.get('post')}\n"
                f"Net: "
                f"{change.get('net'):+,.6f}\n"
            )

            shown += 1
    else:
        message += (
            "\n📈 Token Balance Changes:\n"
            "None detected.\n"
        )

    # =========================
    # SOL BALANCE CHANGES
    # =========================

    if sol_changes:
        message += (
            "\n💰 SOL Balance Changes:\n"
        )

        shown = 0

        for change in sol_changes:
            if shown >= 10:
                break

            message += (
                f"\nAccount: "
                f"{shorten_address(change.get('account'))}\n"
                f"Net: "
                f"{format_sol(change.get('net')):+.9f} SOL\n"
            )

            shown += 1

    # =========================
    # TOKEN TRANSFERS
    # =========================

    if token_transfers:
        message += (
            "\n🪙 Token Transfers:\n"
        )

        for index, transfer in enumerate(
            token_transfers[:10],
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
                f"\n{index}. "
                f"Amount: {amount}\n"
                f"Mint: "
                f"{shorten_address(transfer.get('mint'))}\n"
                f"From: "
                f"{shorten_address(transfer.get('source'))}\n"
                f"To: "
                f"{shorten_address(transfer.get('destination'))}\n"
                f"Authority: "
                f"{shorten_address(transfer.get('authority'))}\n"
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
            programs.append(
                program_id
            )

    for group in (
        meta.get(
            "innerInstructions",
            []
        )
        or []
    ):
        for instruction in (
            group.get(
                "instructions",
                []
            )
            or []
        ):
            program_id = instruction.get(
                "programId"
            )

            if (
                program_id
                and program_id not in programs
            ):
                programs.append(
                    program_id
                )

    message += (
        "\n🏗️ Programs Called:\n"
    )

    for program_id in programs:
        message += (
            f"• "
            f"{shorten_address(program_id, 12)}\n"
        )

    message += (
        "\n🔗 Signature:\n"
        f"{signature}"
    )

    # Telegram limit
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
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "ping",
            ping
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status
        )
    )

    application.add_handler(
        CommandHandler(
            "watch",
            watch
        )
    )

    application.add_handler(
        CommandHandler(
            "list",
            list_tokens
        )
    )

    application.add_handler(
        CommandHandler(
            "info",
            info
        )
    )

    application.add_handler(
        CommandHandler(
            "activity",
            activity
        )
    )

    application.add_handler(
        CommandHandler(
            "tx",
            tx
        )
    )

    application.run_polling()


if __name__ == "__main__":
    main()
