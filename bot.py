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
    [[KeyboardButton("📋 List"), KeyboardButton("➕ Add"), KeyboardButton("✏️ Edit"), KeyboardButton("🗑️ Remove")]],
    resize_keyboard=True,
)

WAITING_NAME, WAITING_DATE, WAITING_LINK = range(3)
EDIT_SELECT, EDIT_FIELD, EDIT_VALUE = range(3, 6)
WARNING_DAYS = 7
TIMEZONE = pytz.timezone("Africa/Lagos")


def get_hackathons():
    res = httpx.get(REST, headers=HEADERS, params={"select": "*", "order": "end_date"})
    logger.info("GET hackathons: %s %s", res.status_code, res.text)
    return res.json() if res.is_success else []


def insert_hackathon(name, end_date, added_by, link):
    httpx.post(REST, headers={**HEADERS, "Prefer": "return=minimal"}, json={
        "name": name,
        "end_date": end_date,
        "added_by": added_by,
        "link": link,
    })


def update_hackathon(hackathon_id, field, value):
    httpx.patch(REST, headers={**HEADERS, "Prefer": "return=minimal"},
                params={"id": f"eq.{hackathon_id}"}, json={field: value})


def delete_hackathon(hackathon_id):
    httpx.delete(REST, headers=HEADERS, params={"id": f"eq.{hackathon_id}"})


def days_left(end_date_str):
    return (date.fromisoformat(end_date_str) - date.today()).days


def format_digest(hackathons):
    if not hackathons:
        return "No hackathons listed yet. Use /add to add one."

    lines = ["<b>📋 Hackathon Tracker</b>\n"]
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

        link_part = f' — <a href="{h["link"]}">link</a>' if h.get("link") else ""
        lines.append(f"<b>{h['name']}</b>\n└ {end} — {status}{link_part}\n")

    if warnings:
        lines.append("⚠️ <b>Ending soon:</b> " + ", ".join(warnings))

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

    ctx.user_data["hack_date"] = str(parsed)
    await update.message.reply_text("What's the hackathon link? (e.g. https://example.com)")
    return WAITING_LINK


async def add_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    if not raw.startswith("http"):
        await update.message.reply_text("Invalid URL. Must start with http:// or https://")
        return WAITING_LINK

    name = ctx.user_data["hack_name"]
    end_date = ctx.user_data["hack_date"]
    added_by = update.effective_user.username or update.effective_user.first_name
    insert_hackathon(name, end_date, added_by, raw)

    dl = days_left(end_date)
    await update.message.reply_text(
        f"✅ <b>{name}</b> added!\nEnds: {date.fromisoformat(end_date).strftime('%b %d, %Y')} ({dl} days left)",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END


async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


async def list_hackathons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    hackathons = get_hackathons()
    await update.message.reply_text(format_digest(hackathons), parse_mode="HTML")


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
    await update.message.reply_text(f"🗑️ <b>{h['name']}</b> removed.", parse_mode="HTML", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


async def edit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    hackathons = get_hackathons()
    if not hackathons:
        await update.message.reply_text("No hackathons to edit.")
        return ConversationHandler.END

    lines = ["Which hackathon do you want to edit? Reply with the number:\n"]
    for i, h in enumerate(hackathons, 1):
        lines.append(f"{i}. {h['name']}")

    ctx.user_data["hackathons"] = hackathons
    await update.message.reply_text("\n".join(lines))
    return EDIT_SELECT


async def edit_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    hackathons = ctx.user_data.get("hackathons", [])
    raw = update.message.text.strip()

    try:
        idx = int(raw) - 1
        if idx < 0 or idx >= len(hackathons):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Send a valid number.")
        return EDIT_SELECT

    ctx.user_data["edit_hackathon"] = hackathons[idx]
    kb = ReplyKeyboardMarkup([
        [KeyboardButton("Name"), KeyboardButton("Date"), KeyboardButton("Link")]
    ], resize_keyboard=True)
    await update.message.reply_text("What field do you want to edit?", reply_markup=kb)
    return EDIT_FIELD


async def edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    field = update.message.text.strip().lower()
    if field == "name":
        ctx.user_data["edit_field"] = "name"
        await update.message.reply_text("Enter the new name:")
    elif field == "date":
        ctx.user_data["edit_field"] = "end_date"
        await update.message.reply_text("Enter the new date (YYYY-MM-DD):")
    elif field == "link":
        ctx.user_data["edit_field"] = "link"
        await update.message.reply_text("Enter the new link (http/https):")
    else:
        await update.message.reply_text("Invalid field. Choose Name, Date, or Link.")
        return EDIT_FIELD

    return EDIT_VALUE


async def edit_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    field = ctx.user_data["edit_field"]
    hackathon = ctx.user_data["edit_hackathon"]

    if field == "end_date":
        try:
            parsed = date.fromisoformat(raw)
            value = str(parsed)
        except ValueError:
            await update.message.reply_text("Invalid date. Use YYYY-MM-DD format.")
            return EDIT_VALUE
    elif field == "link":
        if not raw.startswith("http"):
            await update.message.reply_text("Invalid URL. Must start with http:// or https://")
            return EDIT_VALUE
        value = raw
    else:
        value = raw

    update_hackathon(hackathon["id"], field, value)
    await update.message.reply_text(
        f"✅ <b>{hackathon['name']}</b> updated!",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END


async def daily_digest(ctx: ContextTypes.DEFAULT_TYPE):
    hackathons = get_hackathons()

    for h in hackathons:
        if days_left(h["end_date"]) < -1:
            delete_hackathon(h["id"])

    hackathons = get_hackathons()
    await ctx.bot.send_message(chat_id=CHAT_ID, text=format_digest(hackathons), parse_mode="HTML")


async def handle_buttons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📋 List":
        await list_hackathons(update, ctx)
    elif text == "➕ Add":
        return await add_start(update, ctx)
    elif text == "✏️ Edit":
        return await edit_start(update, ctx)
    elif text == "🗑️ Remove":
        return await remove_start(update, ctx)


async def set_commands(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Show available commands"),
        BotCommand("add", "Add a new hackathon"),
        BotCommand("list", "View all hackathons"),
        BotCommand("edit", "Edit a hackathon"),
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
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_link)],
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

    edit_conv = ConversationHandler(
        entry_points=[CommandHandler("edit", edit_start)],
        states={
            EDIT_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_select)],
            EDIT_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field)],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_conv)
    app.add_handler(remove_conv)
    app.add_handler(edit_conv)
    app.add_handler(CommandHandler("list", list_hackathons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    job_queue = app.job_queue
    target_time = datetime.now(TIMEZONE).replace(hour=6, minute=0, second=0, microsecond=0)
    job_queue.run_daily(daily_digest, time=target_time.timetz())

    logger.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
