import os
import threading
import requests
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

app = Flask(__name__)


@app.route("/")
def home():
    return "🛡️ Pump Sentinel is online!"


@app.route("/health")
def health():
    return "OK"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ Pump Sentinel is online!\n\n"
        "Blockchain monitoring system is being built."
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


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def main():
    if not TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    bot = Application.builder().token(TOKEN).build()

    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("ping", ping))
    bot.add_handler(CommandHandler("status", status))

    print("🛡️ Pump Sentinel is running...")

    bot.run_polling()


if __name__ == "__main__":
    main()
