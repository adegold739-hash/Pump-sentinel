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

    name = token_info["name"]
    symbol = token_info["symbol"]
    supply = token_info["supply"]
    decimals = token_info["decimals"]

    watched_tokens = get_tokens()
    watching = token_address in watched_tokens

    watching_status = "👀 YES" if watching else "❌ NO"

    await update.message.reply_text(
        f"🪙 {name}\n"
        f"🔤 Symbol: {symbol}\n\n"
        f"📍 Address:\n"
        f"`{token_address}`\n\n"
        f"💰 Supply: {supply}\n"
        f"🔢 Decimals: {decimals}\n"
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


def run_web_server():

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )


def main():

    print("🛡️ Starting Pump Sentinel...")

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

    print(
        "🛡️ Pump Sentinel Telegram bot is running..."
    )

    bot.run_polling()


if __name__ == "__main__":
    main()
