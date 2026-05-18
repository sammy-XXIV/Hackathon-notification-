import os
import logging
import httpx
from datetime import datetime, date
from telegram import Update, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}
REST = f"{SUPABASE_URL}/rest/v1/hackathons"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("📋 List"), KeyboardButton("➕ Add"), KeyboardButton("🗑️ Remove")]],
    resize_keyboard=True,
)

WAITING_NAME, WAITING_DATE = range(2)
WARNING_DAYS = 7
TIMEZONE = pytz.timezone("Africa/Lagos")


def get_hackathons():
    res = httpx.get(REST, headers=HEADERS, params={"select": "*", "order": "end_date"})
    logger.info("GET hackathons: %s %s", res.status_code, res.text)
    return res.json() if res.is_success else []


def insert_hackathon(name, end_date, added_by):
    httpx.post(REST, headers={**HEADERS, "Prefer": "return=minimal"}, json={
        "name": name,
        "end_date": end_date,
        "added_by": added_by,
    })


def delete_hackathon(hackathon_id):
    httpx.delete(REST, headers=HEADERS, params={"id": f"eq.{hackathon_id}"})


def days_left(end_date_str):
    return (date.fromisoformat(end_date_str) - date.today()).days


def format_digest(hackathons):
    if not hackathons:
        return "No hackathons listed yet. Use /add to add one."

    lines = ["📋 *Hackathon Tracker*\n"]
    warnings = []

    for h in hackathons:
        dl = days_left(h["end_date"])
        end = date.fromisoformat(h["end_date"]).strftime("%b %d, %Y")

        if dl < 0:
            status = "❌ Ended"
        elif dl == 0:
            status = "🔴 Ends TODAY"
        elif dl <= WARNING_DAYS:
            status = f"⚠️ {dl}d left"
            warnings.append(h["name"])
        else:
            status = f"🟢 {dl}d left"

        lines.append(f"*{h['name']}*\n└ {end} — {status}\n")

    if warnings:
        lines.append("⚠️ *Ending soon:* " + ", ".join(warnings))

    return "\n".join(lines)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hackathon Tracker Bot\n\n"
        "/add — add a hackathon\n"
        "/list — view all hackathons\n"
        "/remove — remove a hackathon",
        reply_markup=MAIN_KEYBOARD,
    )


async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("What's the hackathon name?")
    return WAITING_NAME


async def add_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["hack_name"] = update.message.text.strip()
    await update.message.reply_text("What's the end date? (format: YYYY-MM-DD)")
    return WAITING_DATE


async def add_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        await update.message.reply_text("Invalid date. Use YYYY-MM-DD format (e.g. 2025-06-30)")
        return WAITING_DATE

    name = ctx.user_data["hack_name"]
    added_by = update.effective_user.username or update.effective_user.first_name
    insert_hackathon(name, str(parsed), added_by)

    dl = days_left(str(parsed))
    await update.message.reply_text(
        f"✅ *{name}* added!\nEnds: {parsed.strftime('%b %d, %Y')} ({dl} days left)",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END


async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


async def list_hackathons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    hackathons = get_hackathons()
    await update.message.reply_text(format_digest(hackathons), parse_mode="Markdown")


async def remove_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    hackathons = get_hackathons()
    if not hackathons:
        await update.message.reply_text("No hackathons to remove.")
        return

    lines = ["Which hackathon do you want to remove? Reply with the number:\n"]
    for i, h in enumerate(hackathons, 1):
        lines.append(f"{i}. {h['name']}")

    ctx.user_data["hackathons"] = hackathons
    await update.message.reply_text("\n".join(lines))
    return "WAITING_REMOVE"


async def remove_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    hackathons = ctx.user_data.get("hackathons", [])
    raw = update.message.text.strip()

    try:
        idx = int(raw) - 1
        if idx < 0 or idx >= len(hackathons):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Send a valid number.")
        return "WAITING_REMOVE"

    h = hackathons[idx]
    delete_hackathon(h["id"])
    await update.message.reply_text(f"🗑️ *{h['name']}* removed.", parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


async def daily_digest(ctx: ContextTypes.DEFAULT_TYPE):
    hackathons = get_hackathons()

    for h in hackathons:
        if days_left(h["end_date"]) < -1:
            delete_hackathon(h["id"])

    hackathons = get_hackathons()
    await ctx.bot.send_message(chat_id=CHAT_ID, text=format_digest(hackathons), parse_mode="Markdown")


async def handle_buttons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📋 List":
        await list_hackathons(update, ctx)
    elif text == "➕ Add":
        return await add_start(update, ctx)
    elif text == "🗑️ Remove":
        return await remove_start(update, ctx)


async def set_commands(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Show available commands"),
        BotCommand("add", "Add a new hackathon"),
        BotCommand("list", "View all hackathons"),
        BotCommand("remove", "Remove a hackathon"),
        BotCommand("cancel", "Cancel current operation"),
    ])


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(set_commands).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            WAITING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_date)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    remove_conv = ConversationHandler(
        entry_points=[CommandHandler("remove", remove_start)],
        states={
            "WAITING_REMOVE": [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_select)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_conv)
    app.add_handler(remove_conv)
    app.add_handler(CommandHandler("list", list_hackathons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    job_queue = app.job_queue
    target_time = datetime.now(TIMEZONE).replace(hour=6, minute=0, second=0, microsecond=0)
    job_queue.run_daily(daily_digest, time=target_time.timetz())

    logger.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
