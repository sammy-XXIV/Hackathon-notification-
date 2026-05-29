import os
import logging
import httpx
from datetime import datetime, date
from telegram import Update, BotCommand, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
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

MAIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("📋 List", callback_data="list")],
    [InlineKeyboardButton("➕ Add", callback_data="add")],
    [InlineKeyboardButton("✏️ Edit", callback_data="edit")],
    [InlineKeyboardButton("🗑️ Remove", callback_data="remove")],
])

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
        "👋 Hackathon Tracker Bot\n\nChoose an action:",
        reply_markup=MAIN_MENU,
    )


async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("What's the hackathon name?")
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
    kb = MAIN_MENU
    await update.message.reply_text(
        f"✅ <b>{name}</b> added!\nEnds: {date.fromisoformat(end_date).strftime('%b %d, %Y')} ({dl} days left)",
        parse_mode="HTML",
        reply_markup=kb,
    )
    return ConversationHandler.END


async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def list_hackathons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    hackathons = get_hackathons()
    kb = MAIN_MENU
    await query.edit_message_text(format_digest(hackathons), parse_mode="HTML", reply_markup=kb)


async def remove_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    hackathons = get_hackathons()
    if not hackathons:
        await query.edit_message_text("No hackathons to remove.")
        return ConversationHandler.END

    ctx.user_data["hackathons"] = {h["id"]: h for h in hackathons}
    buttons = [[InlineKeyboardButton(h["name"], callback_data=f"remove_sel_{h['id']}")] for h in hackathons]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="remove_cancel")])
    kb = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("Which hackathon do you want to remove?", reply_markup=kb)
    return "WAITING_REMOVE"


async def remove_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "remove_cancel":
        await query.edit_message_text("Remove cancelled.")
        return ConversationHandler.END

    hackathons = ctx.user_data.get("hackathons", {})
    hackathon_id = int(query.data.split("_")[2])
    h = hackathons[hackathon_id]

    delete_hackathon(h["id"])
    kb = MAIN_MENU
    await query.edit_message_text(f"🗑️ <b>{h['name']}</b> removed.", parse_mode="HTML", reply_markup=kb)
    return ConversationHandler.END


async def edit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    hackathons = get_hackathons()
    if not hackathons:
        await query.edit_message_text("No hackathons to edit.")
        return ConversationHandler.END

    ctx.user_data["hackathons"] = {h["id"]: h for h in hackathons}
    buttons = [[InlineKeyboardButton(h["name"], callback_data=f"edit_sel_{h['id']}")] for h in hackathons]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")])
    kb = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("Which hackathon do you want to edit?", reply_markup=kb)
    return EDIT_SELECT


async def edit_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "edit_cancel":
        await query.edit_message_text("Edit cancelled.")
        return ConversationHandler.END

    hackathons = ctx.user_data.get("hackathons", {})
    hackathon_id = int(query.data.split("_")[2])
    ctx.user_data["edit_hackathon"] = hackathons[hackathon_id]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Name", callback_data="edit_field_name")],
        [InlineKeyboardButton("Date", callback_data="edit_field_end_date")],
        [InlineKeyboardButton("Link", callback_data="edit_field_link")],
        [InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")],
    ])
    await query.edit_message_text("What field do you want to edit?", reply_markup=kb)
    return EDIT_FIELD


async def edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.replace("edit_field_", "")

    if data == "cancel":
        await query.edit_message_text("Edit cancelled.")
        return ConversationHandler.END

    ctx.user_data["edit_field"] = data

    if data == "name":
        msg = "Enter the new name:"
    elif data == "end_date":
        msg = "Enter the new date (YYYY-MM-DD):"
    else:
        msg = "Enter the new link (http/https):"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel_value")]])
    await query.edit_message_text(msg, reply_markup=kb)
    return EDIT_VALUE


async def edit_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Handle cancel button callback
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "edit_cancel_value":
            await query.edit_message_text("Edit cancelled.")
            return ConversationHandler.END

    # Handle text input
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
    kb = MAIN_MENU
    await update.message.reply_text(
        f"✅ <b>{hackathon['name']}</b> updated!",
        parse_mode="HTML",
        reply_markup=kb,
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
    query = update.callback_query
    await query.answer()

    if query.data == "list":
        return await list_hackathons(update, ctx)
    elif query.data == "add":
        return await add_start(update, ctx)
    elif query.data == "edit":
        return await edit_start(update, ctx)
    elif query.data == "remove":
        return await remove_start(update, ctx)


async def set_commands(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Start the bot and show main menu"),
        BotCommand("add", "Add a new hackathon with name, date, and link"),
        BotCommand("list", "View all tracked hackathons with deadlines"),
        BotCommand("edit", "Edit hackathon details (name, date, or link)"),
        BotCommand("remove", "Remove a hackathon from the list"),
        BotCommand("cancel", "Cancel the current operation"),
    ])


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(set_commands).build()

    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_start, pattern="^add$")],
        states={
            WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            WAITING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_date)],
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_link)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    remove_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_start, pattern="^remove$")],
        states={
            "WAITING_REMOVE": [CallbackQueryHandler(remove_select, pattern="^remove_")],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_start, pattern="^edit$")],
        states={
            EDIT_SELECT: [CallbackQueryHandler(edit_select, pattern="^edit_sel_|^edit_cancel$")],
            EDIT_FIELD: [CallbackQueryHandler(edit_field, pattern="^edit_field_")],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value), CallbackQueryHandler(edit_value, pattern="^edit_cancel_value$")],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_conv)
    app.add_handler(remove_conv)
    app.add_handler(edit_conv)
    app.add_handler(CallbackQueryHandler(handle_buttons, pattern="^list$"))

    job_queue = app.job_queue
    target_time = datetime.now(TIMEZONE).replace(hour=6, minute=0, second=0, microsecond=0)
    job_queue.run_daily(daily_digest, time=target_time.timetz())

    logger.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
