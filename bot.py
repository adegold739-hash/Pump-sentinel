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

        message += (
            f"{number}. `{token}`\n"
        )

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

        for number, tx in enumerate(
            transactions,
            start=1
        ):

            status_icon = (
                "✅"
                if tx.get("err") is None
                else "❌"
            )

            signature = tx.get(
                "signature",
                "Unknown"
            )

            block_time = tx.get(
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
        "🔍 Analyzing transaction..."
    )

    try:

        url = (
            "https://api.helius.xyz/v0/transactions"
            f"?api-key={HELIUS_API_KEY}"
        )

        response = requests.post(
            url,
            json={
                "transactions": [
                    signature
                ]
            },
            timeout=15
        )

        if not response.ok:

            print(
                "Transaction API response:",
                response.text
            )

            await update.message.reply_text(
                "❌ Helius transaction request failed."
            )

            return

        data = response.json()

        if not data:

            await update.message.reply_text(
                "❌ Transaction was not found "
                "or could not be parsed."
            )

            return

        transaction = data[0]

        tx_type = transaction.get(
            "type",
            "UNKNOWN"
        )

        description = transaction.get(
            "description",
            "No description available."
        )

        timestamp = transaction.get(
            "timestamp",
            "Unknown"
        )

        fee = transaction.get(
            "fee",
            0
        )

        native_transfers = transaction.get(
            "nativeTransfers",
            []
        )

        token_transfers = transaction.get(
            "tokenTransfers",
            []
        )

        message = (
            "🔍 Transaction Analysis\n\n"
            f"🧩 Type: {tx_type}\n"
            f"📝 Description: {description}\n"
            f"⏱️ Timestamp: {timestamp}\n"
            f"💸 Fee: {fee} lamports\n\n"
        )

        if native_transfers:

            message += (
                "💰 SOL Transfers:\n"
            )

            for transfer in native_transfers[:5]:

                sender = transfer.get(
                    "fromUserAccount",
                    "Unknown"
                )

                receiver = transfer.get(
                    "toUserAccount",
                    "Unknown"
                )

                amount = transfer.get(
                    "amount",
                    0
                )

                sol_amount = (
                    amount / 1_000_000_000
                )

                message += (
                    f"• {sol_amount:.6f} SOL\n"
                    f"  From: `{sender}`\n"
                    f"  To: `{receiver}`\n\n"
                )

        if token_transfers:

            message += (
                "🪙 Token Transfers:\n"
            )

            for transfer in token_transfers[:5]:

                mint = transfer.get(
                    "mint",
                    "Unknown"
                )

                from_account = transfer.get(
                    "fromUserAccount",
                    "Unknown"
                )

                to_account = transfer.get(
                    "toUserAccount",
                    "Unknown"
                )

                token_amount = transfer.get(
                    "tokenAmount",
                    transfer.get(
                        "rawTokenAmount",
                        "Unknown"
                    )
                )

                message += (
                    f"• Amount: {token_amount}\n"
                    f"  Mint: `{mint}`\n"
                    f"  From: `{from_account}`\n"
                    f"  To: `{to_account}`\n\n"
                )

        message += (
            f"🔗 Signature:\n"
            f"`{signature}`"
        )

        if len(message) > 4000:

            message = message[:3950] + (
                "\n\n⚠️ Message shortened."
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
            f"Transaction analysis error: {error}"
        )

        await update.message.reply_text(
            "❌ Something went wrong while "
            "analyzing the transaction."
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
        CommandHandler(
            "start",
            start
        )
    )

    bot.add_handler(
        CommandHandler(
            "ping",
            ping
        )
    )

    bot.add_handler(
        CommandHandler(
            "status",
            status
        )
    )

    bot.add_handler(
        CommandHandler(
            "watch",
            watch
        )
    )

    bot.add_handler(
        CommandHandler(
            "info",
            info
        )
    )

    bot.add_handler(
        CommandHandler(
            "list",
            list_tokens
        )
    )

    bot.add_handler(
        CommandHandler(
            "activity",
            activity
        )
    )

    bot.add_handler(
        CommandHandler(
            "tx",
            tx
        )
    )

    print(
        "🛡️ Pump Sentinel Telegram bot is running..."
    )

    bot.run_polling()


if __name__ == "__main__":
    main()
