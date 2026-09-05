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

    for number, token in enumerate(
        tokens,
        start=1
    ):

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


def shorten_address(address):

    if not address:
        return "Unknown"

    if len(address) <= 12:
        return address

    return (
        address[:6]
        + "..."
        + address[-6:]
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
        "🔍 Inspecting transaction instructions..."
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
                "id": "pump-sentinel-instructions",
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
                "Transaction response:",
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
                "❌ Helius returned an error."
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

        message_data = (
            transaction
            .get("transaction", {})
            .get("message", {})
        )

        if not meta:

            await update.message.reply_text(
                "⚠️ Transaction found, but "
                "metadata is unavailable."
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

        account_keys = message_data.get(
            "accountKeys",
            []
        )

        instructions = message_data.get(
            "instructions",
            []
        )

        inner_instructions = meta.get(
            "innerInstructions",
            []
        )

        message = (
            "🔬 Transaction Inspection\n\n"
            f"📊 Status: {status}\n"
            f"🧱 Slot: {slot}\n"
            f"⏱️ Block time: {block_time}\n"
            f"💸 Fee: {fee} lamports\n\n"
        )

        message += (
            f"👥 Accounts involved: "
            f"{len(account_keys)}\n"
            f"🧩 Instructions: "
            f"{len(instructions)}\n"
            f"🔁 Inner instruction groups: "
            f"{len(inner_instructions)}\n\n"
        )

        program_ids = []

        for instruction in instructions:

            program_id = instruction.get(
                "programId"
            )

            if program_id:

                program_ids.append(
                    program_id
                )

            else:

                parsed = instruction.get(
                    "parsed"
                )

                if isinstance(parsed, dict):

                    program = instruction.get(
                        "program"
                    )

                    if program:
                        program_ids.append(
                            f"{program} (parsed)"
                        )

        unique_programs = []

        for program in program_ids:

            if program not in unique_programs:

                unique_programs.append(
                    program
                )

        if unique_programs:

            message += (
                "🏗️ Programs called:\n\n"
            )

            for program in unique_programs[:10]:

                message += (
                    f"• `{program}`\n"
                )

            message += "\n"

        else:

            message += (
                "🏗️ Programs called:\n"
                "None identified\n\n"
            )

        if instructions:

            message += (
                "🧩 Outer Instructions:\n\n"
            )

            for number, instruction in enumerate(
                instructions[:10],
                start=1
            ):

                program = instruction.get(
                    "program"
                )

                program_id = instruction.get(
                    "programId"
                )

                parsed = instruction.get(
                    "parsed"
                )

                if program:

                    label = program

                elif program_id:

                    label = shorten_address(
                        program_id
                    )

                else:

                    label = "Unknown"

                parsed_type = ""

                if isinstance(parsed, dict):

                    parsed_type = parsed.get(
                        "type",
                        ""
                    )

                if parsed_type:

                    message += (
                        f"{number}. {label}\n"
                        f"   Type: {parsed_type}\n"
                    )

                else:

                    message += (
                        f"{number}. {label}\n"
                    )

            message += "\n"

        if inner_instructions:

            message += (
                "🔁 Inner Instructions:\n\n"
            )

            inner_count = 0

            for group in inner_instructions:

                group_index = group.get(
                    "index",
                    "?"
                )

                inner_list = group.get(
                    "instructions",
                    []
                )

                for instruction in inner_list[:5]:

                    if inner_count >= 12:
                        break

                    program = instruction.get(
                        "program"
                    )

                    program_id = instruction.get(
                        "programId"
                    )

                    parsed = instruction.get(
                        "parsed"
                    )

                    if program:

                        label = program

                    elif program_id:

                        label = shorten_address(
                            program_id
                        )

                    else:

                        label = "Unknown"

                    parsed_type = ""

                    if isinstance(parsed, dict):

                        parsed_type = parsed.get(
                            "type",
                            ""
                        )

                    if parsed_type:

                        message += (
                            f"• Group {group_index}: "
                            f"{label}\n"
                            f"  Type: {parsed_type}\n"
                        )

                    else:

                        message += (
                            f"• Group {group_index}: "
                            f"{label}\n"
                        )

                    inner_count += 1

                if inner_count >= 12:
                    break

            message += "\n"

        else:

            message += (
                "🔁 Inner Instructions:\n"
                "None found\n\n"
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
            "Instruction analysis error:",
            error
        )

        await update.message.reply_text(
            "❌ Something went wrong while "
            "inspecting the transaction."
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
