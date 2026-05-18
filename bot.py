import os
import logging
from datetime import datetime, date, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from supabase import create_client
import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

WAITING_NAME, WAITING_DATE = range(2)
WARNING_DAYS = 7
TIMEZONE = pytz.timezone("Africa/Lagos")


def get_hackathons():
    res = supabase.table("hackathons").select("*").order("end_date").execute()
    return res.data or []


def days_left(end_date_str):
    end = date.fromisoformat(end_date_str)
    return (end - date.today()).days


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
        "/remove — remove a hackathon"
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

    supabase.table("hackathons").insert({
        "name": name,
        "end_date": str(parsed),
        "added_by": added_by
    }).execute()

    dl = days_left(str(parsed))
    await update.message.reply_text(
        f"✅ *{name}* added!\nEnds: {parsed.strftime('%b %d, %Y')} ({dl} days left)",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def list_hackathons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    hackathons = get_hackathons()
    msg = format_digest(hackathons)
    await update.message.reply_text(msg, parse_mode="Markdown")


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
    supabase.table("hackathons").delete().eq("id", h["id"]).execute()
    await update.message.reply_text(f"🗑️ *{h['name']}* removed.", parse_mode="Markdown")
    return ConversationHandler.END


async def daily_digest(ctx: ContextTypes.DEFAULT_TYPE):
    hackathons = get_hackathons()

    # Remove ended hackathons older than 1 day
    for h in hackathons:
        if days_left(h["end_date"]) < -1:
            supabase.table("hackathons").delete().eq("id", h["id"]).execute()

    # Refresh after cleanup
    hackathons = get_hackathons()
    msg = format_digest(hackathons)

    await ctx.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

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

    # Schedule daily digest at 6am WAT
    job_queue = app.job_queue
    target_time = datetime.now(TIMEZONE).replace(hour=6, minute=0, second=0, microsecond=0)
    job_queue.run_daily(daily_digest, time=target_time.timetz())

    logger.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
