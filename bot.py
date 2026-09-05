import os
import threading
import requests

from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from database import init_database, add_token, get_tokens
from solana import get_token_info


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")


app = Flask(__name__)


@app.route("/")
def home():
    return "Pump Sentinel is online!"


@app.route("/health")
def health():
    return "OK"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🛡️ Pump Sentinel\n\n"
        "Commands:\n"
        "/watch TOKEN_ADDRESS - Watch a token\n"
        "/info TOKEN_ADDRESS - Get token information\n"
        "/list - Show watched tokens\n"
        "/activity TOKEN_ADDRESS - Recent activity\n"
        "/tx SIGNATURE - Analyze a transaction\n"
        "/status - Check connections\n"
        "/ping - Test the bot"
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🟢 Pump Sentinel is alive!"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not HELIUS_API_KEY:
        await update.message.reply_text(
            "🔴 Helius API key is missing."
        )
        return

    try:

        url = (
            "https://mainnet.helius-rpc.com/"
            f"?api-key={HELIUS_API_KEY}"
        )

        response = requests.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getHealth"
            },
            timeout=10
        )

        if response.ok:

            await update.message.reply_text(
                "🟢 Pump Sentinel\n\n"
                "Telegram: ONLINE ✅\n"
                "Helius: CONNECTED ✅"
            )

        else:

            await update.message.reply_text(
                "🟡 Telegram: ONLINE\n"
                "🔴 Helius connection failed."
            )

    except Exception:

        await update.message.reply_text(
            "🟡 Telegram: ONLINE\n"
            "🔴 Could not reach Helius."
        )


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "❌ Give me a Solana token address.\n\n"
            "Example:\n"
            "/watch TOKEN_ADDRESS"
        )

        return

    token_address = context.args[0].strip()

    if len(token_address) < 32:

        await update.message.reply_text(
            "❌ That doesn't look like a valid Solana address."
        )

        return

    await update.message.reply_text(
        "🔎 Checking the token on Solana..."
    )

    token_info, error = get_token_info(token_address)

    if error:

        await update.message.reply_text(
            f"❌ {error}"
        )

        return

    added = add_token(token_address)

    if not added:

        await update.message.reply_text(
            "👀 I'm already watching that token."
        )

        return

    name = token_info["name"]
    symbol = token_info["symbol"]

    await update.message.reply_text(
        f"👀 Now watching:\n\n"
        f"🪙 {name} ({symbol})\n"
        f"📍 `{token_address}`\n\n"
        f"✅ Token verified on Solana."
    )


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "❌ Give me a Solana token address.\n\n"
            "Example:\n"
            "/info TOKEN_ADDRESS"
        )

        return

    token_address = context.args[0].strip()

    if len(token_address) < 32:

        await update.message.reply_text(
            "❌ That doesn't look like a valid Solana address."
        )

        return

    await update.message.reply_text(
        "🔎 Fetching token information..."
    )

    token_info, error = get_token_info(token_address)

    if error:

        await update.message.reply_text(
            f"❌ {error}"
        )

        return

    watched_tokens = get_tokens()

    watching = token_address in watched_tokens

    watching_status = (
        "👀 YES"
        if watching
        else "❌ NO"
    )

    await update.message.reply_text(
        f"🪙 {token_info['name']}\n"
        f"🔤 Symbol: {token_info['symbol']}\n\n"
        f"📍 Address:\n"
        f"`{token_address}`\n\n"
        f"💰 Supply: {token_info['supply']}\n"
        f"🔢 Decimals: {token_info['decimals']}\n"
        f"👀 Watching: {watching_status}",
        parse_mode="Markdown"
    )


async def list_tokens(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    tokens = get_tokens()

    if not tokens:

        await update.message.reply_text(
            "📭 You're not watching any tokens yet."
        )

        return

    message = "👀 Watched tokens:\n\n"

    for number, token in enumerate(tokens, start=1):

        message += f"{number}. `{token}`\n"

    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )


async def activity(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "❌ Give me a Solana token address.\n\n"
            "Example:\n"
            "/activity TOKEN_ADDRESS"
        )

        return

    token_address = context.args[0].strip()

    if len(token_address) < 32:

        await update.message.reply_text(
            "❌ That doesn't look like a valid Solana address."
        )

        return

    if not HELIUS_API_KEY:

        await update.message.reply_text(
            "🔴 Helius API key is missing."
        )

        return

    await update.message.reply_text(
        "📡 Checking recent activity..."
    )

    try:

        url = (
            "https://mainnet.helius-rpc.com/"
            f"?api-key={HELIUS_API_KEY}"
        )

        response = requests.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": "pump-sentinel",
                "method": "getSignaturesForAddress",
                "params": [
                    token_address,
                    {
                        "limit": 10
                    }
                ]
            },
            timeout=15
        )

        if not response.ok:

            await update.message.reply_text(
                "❌ Helius request failed."
            )

            return

        data = response.json()

        if "error" in data:

            await update.message.reply_text(
                "❌ Helius returned an error."
            )

            return

        transactions = data.get(
            "result",
            []
        )

        if not transactions:

            await update.message.reply_text(
                "📭 No recent transactions found."
            )

            return

        message = (
            "📡 Recent Activity\n\n"
            f"📍 {token_address}\n"
            f"🔎 Transactions found: "
            f"{len(transactions)}\n\n"
        )

        for number, tx_data in enumerate(
            transactions,
            start=1
        ):

            status_icon = (
                "✅"
                if tx_data.get("err") is None
                else "❌"
            )

            signature = tx_data.get(
                "signature",
                "Unknown"
            )

            block_time = tx_data.get(
                "blockTime",
                "Unknown"
            )

            message += (
                f"{number}. {status_icon} "
                f"{'Success' if status_icon == '✅' else 'Failed'}\n"
                f"⏱️ {block_time}\n"
                f"🔗 `{signature}`\n\n"
            )

        await update.message.reply_text(
            message,
            parse_mode="Markdown"
        )

    except requests.RequestException:

        await update.message.reply_text(
            "❌ Could not connect to Helius."
        )

    except Exception as error:

        print(
            f"Activity error: {error}"
        )

        await update.message.reply_text(
            "❌ Something went wrong while "
            "checking activity."
        )


async def tx(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "❌ Give me a transaction signature.\n\n"
            "Example:\n"
            "/tx SIGNATURE"
        )

        return

    signature = context.args[0].strip()

    if not HELIUS_API_KEY:

        await update.message.reply_text(
            "🔴 Helius API key is missing."
        )

        return

    await update.message.reply_text(
        "🔍 Reading raw Solana transaction..."
    )

    try:

        url = (
            "https://mainnet.helius-rpc.com/"
            f"?api-key={HELIUS_API_KEY}"
        )

        response = requests.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": "pump-sentinel-tx",
                "method": "getTransaction",
                "params": [
                    signature,
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed",
                        "maxSupportedTransactionVersion": 0
                    }
                ]
            },
            timeout=20
        )

        if not response.ok:

            print(
                "Raw transaction response:",
                response.text
            )

            await update.message.reply_text(
                "❌ Helius transaction request failed."
            )

            return

        data = response.json()

        if "error" in data:

            print(
                "Helius transaction error:",
                data["error"]
            )

            await update.message.reply_text(
                "❌ Helius returned an error while "
                "reading the transaction."
            )

            return

        transaction = data.get("result")

        if not transaction:

            await update.message.reply_text(
                "❌ Transaction not found."
            )

            return

        meta = transaction.get(
            "meta"
        )

        if not meta:

            await update.message.reply_text(
                "⚠️ Transaction found, but no "
                "metadata was returned."
            )

            return

        block_time = transaction.get(
            "blockTime",
            "Unknown"
        )

        slot = transaction.get(
            "slot",
            "Unknown"
        )

        fee = meta.get(
            "fee",
            0
        )

        err = meta.get(
            "err"
        )

        status = (
            "✅ SUCCESS"
            if err is None
            else "❌ FAILED"
        )

        pre_balances = meta.get(
            "preBalances",
            []
        )

        post_balances = meta.get(
            "postBalances",
            []
        )

        account_keys = (
            transaction
            .get("transaction", {})
            .get("message", {})
            .get("accountKeys", [])
        )

        message = (
            "🔍 Raw Transaction Analysis\n\n"
            f"📊 Status: {status}\n"
            f"🧱 Slot: {slot}\n"
            f"⏱️ Block time: {block_time}\n"
            f"💸 Fee: {fee} lamports\n\n"
        )

        sol_changes = []

        count = min(
            len(pre_balances),
            len(post_balances),
            len(account_keys)
        )

        for i in range(count):

            before = pre_balances[i]
            after = post_balances[i]

            change = after - before

            if change == 0:
                continue

            account = account_keys[i]

            if isinstance(account, dict):

                address = account.get(
                    "pubkey",
                    "Unknown"
                )

            else:

                address = str(account)

            sol_change = (
                change / 1_000_000_000
            )

            sol_changes.append(
                (
                    address,
                    sol_change
                )
            )

        if sol_changes:

            message += "💰 SOL Balance Changes:\n\n"

            for address, change in sol_changes[:8]:

                direction = (
                    "📈 +"
                    if change > 0
                    else "📉 "
                )

                message += (
                    f"{direction}{change:.6f} SOL\n"
                    f"👤 `{address}`\n\n"
                )

        else:

            message += (
                "💰 SOL Balance Changes:\n"
                "None detected\n\n"
            )

        pre_token_balances = meta.get(
            "preTokenBalances",
            []
        )

        post_token_balances = meta.get(
            "postTokenBalances",
            []
        )

        token_before = {}

        for balance in pre_token_balances:

            account_index = balance.get(
                "accountIndex"
            )

            mint = balance.get(
                "mint",
                "Unknown"
            )

            ui_amount = (
                balance
                .get("uiTokenAmount", {})
                .get("uiAmount")
            )

            if ui_amount is None:

                raw_amount = (
                    balance
                    .get("uiTokenAmount", {})
                    .get("amount", "0")
                )

                decimals = (
                    balance
                    .get("uiTokenAmount", {})
                    .get("decimals", 0)
                )

                try:

                    ui_amount = (
                        int(raw_amount)
                        / (10 ** decimals)
                    )

                except Exception:

                    ui_amount = 0

            token_before[
                (account_index, mint)
            ] = ui_amount

        token_changes = []

        for balance in post_token_balances:

            account_index = balance.get(
                "accountIndex"
            )

            mint = balance.get(
                "mint",
                "Unknown"
            )

            ui_amount = (
                balance
                .get("uiTokenAmount", {})
                .get("uiAmount")
            )

            if ui_amount is None:

                raw_amount = (
                    balance
                    .get("uiTokenAmount", {})
                    .get("amount", "0")
                )

                decimals = (
                    balance
                    .get("uiTokenAmount", {})
                    .get("decimals", 0)
                )

                try:

                    ui_amount = (
                        int(raw_amount)
                        / (10 ** decimals)
                    )

                except Exception:

                    ui_amount = 0

            before_amount = token_before.get(
                (account_index, mint),
                0
            )

            change = ui_amount - before_amount

            if change == 0:
                continue

            owner = balance.get(
                "owner",
                "Unknown"
            )

            token_changes.append(
                (
                    mint,
                    owner,
                    change
                )
            )

        if token_changes:

            message += "🪙 Token Balance Changes:\n\n"

            for mint, owner, change in token_changes[:8]:

                direction = (
                    "📥 +"
                    if change > 0
                    else "📤 "
                )

                message += (
                    f"{direction}{change:,.6f} tokens\n"
                    f"🪙 Mint: `{mint}`\n"
                    f"👤 Owner: `{owner}`\n\n"
                )

        else:

            message += (
                "🪙 Token Balance Changes:\n"
                "None detected\n\n"
            )

        message += (
            "🔗 Signature:\n"
            f"`{signature}`"
        )

        if len(message) > 4000:

            message = (
                message[:3900]
                + "\n\n⚠️ Output shortened."
            )

        await update.message.reply_text(
            message,
            parse_mode="Markdown"
        )

    except requests.RequestException:

        await update.message.reply_text(
            "❌ Could not connect to Helius."
        )

    except Exception as error:

        print(
            f"Raw transaction analysis error: "
            f"{error}"
        )

        await update.message.reply_text(
            "❌ Something went wrong while "
            "reading the raw transaction."
        )


def run_web_server():

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False
    )


def main():

    print(
        "🛡️ Starting Pump Sentinel..."
    )

    if not TELEGRAM_BOT_TOKEN:

        raise ValueError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    init_database()

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    bot = (
        Application
        .builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    bot.add_handler(
        CommandHandler("start", start)
    )

    bot.add_handler(
        CommandHandler("ping", ping)
    )

    bot.add_handler(
        CommandHandler("status", status)
    )

    bot.add_handler(
        CommandHandler("watch", watch)
    )

    bot.add_handler(
        CommandHandler("info", info)
    )

    bot.add_handler(
        CommandHandler("list", list_tokens)
    )

    bot.add_handler(
        CommandHandler("activity", activity)
    )

    bot.add_handler(
        CommandHandler("tx", tx)
    )

    print(
        "🛡️ Pump Sentinel Telegram bot is running..."
    )

    bot.run_polling()


if __name__ == "__main__":
    main()
