import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Web server for Render
app = Flask(__name__)

@app.route("/")
def home():
    return "🛡️ Pump Sentinel is online!"

@app.route("/health")
def health():
    return "OK"


# Telegram commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ Pump Sentinel is online!\n\n"
        "I am your Pump.fun monitoring bot.\n\n"
        "More monitoring features are coming soon."
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟢 Pump Sentinel is alive and responding!"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ Pump Sentinel Commands\n\n"
        "/start - Start the bot\n"
        "/ping - Check if the bot is alive\n"
        "/help - Show commands"
    )


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def main():
    if not TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN environment variable is missing."
        )

    # Start Render's web server
    web_thread = threading.Thread(
        target=run_web_server,
        daemon=True
    )
    web_thread.start()

    # Start Telegram bot
    bot = Application.builder().token(TOKEN).build()

    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("ping", ping))
    bot.add_handler(CommandHandler("help", help_command))

    print("🛡️ Pump Sentinel Telegram bot is running...")

    bot.run_polling()


if __name__ == "__main__":
    main()
