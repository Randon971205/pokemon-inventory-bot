import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz

# Logging
logging.basicConfig(level=logging.INFO)

# Google Sheets Auth
scope = ["https://spreadsheets.google.com/feeds",'https://www.googleapis.com/auth/spreadsheets',
         "https://www.googleapis.com/auth/drive.file","https://www.googleapis.com/auth/drive"]

import json
from io import StringIO

credentials_raw = os.getenv("GOOGLE_CREDS_JSON")
credentials_data = json.load(StringIO(credentials_raw))
creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_data, scope)
client = gspread.authorize(creds)

sheet = client.open("PokemonInventory")  # Replace with your actual Google Sheet name
inv_sheet = sheet.worksheet("Inventory")
log_sheet = sheet.worksheet("Logs")

SG_TIME = pytz.timezone("Asia/Singapore")

def log_action(action, product, qty, user, note=""):
    now = datetime.now(SG_TIME).strftime("%d/%m/%Y %H:%M:%S")
    log_sheet.append_row([now, action, product, qty, f"@{user}", note])

def update_inventory(product, delta):
    try:
        cell = inv_sheet.find(product)
        current = int(inv_sheet.cell(cell.row, cell.col + 1).value)
        inv_sheet.update_cell(cell.row, cell.col + 1, current + delta)
    except gspread.exceptions.CellNotFound:
        inv_sheet.append_row([product, delta])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📥 Add", callback_data='add')],
        [InlineKeyboardButton("❌ Minus", callback_data='minus')],
        [InlineKeyboardButton("📦 Open", callback_data='open')],
        [InlineKeyboardButton("📊 Stock", callback_data='stock')],
        [InlineKeyboardButton("📈 Report", callback_data='report')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Welcome to the Pokémon Inventory Bot!\nChoose a command:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    command_map = {
        "add": "/add [product_name] [qty]",
        "minus": "/minus [product_name] [qty]",
        "open": "/open [product_name] [qty] [note]",
        "stock": "/stock [product_name] or /stock all",
        "report": "/report"
    }
    message = f"📌 Usage for `{query.data}`:\n{command_map[query.data]}"
    await query.edit_message_text(text=message, parse_mode="Markdown")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        product = context.args[0]
        qty = int(context.args[1])
        user = update.effective_user.username
        update_inventory(product, qty)
        log_action("Add", product, qty, user)
        await update.message.reply_text(f"✅ Added {qty} of {product}.")
    except:
        await update.message.reply_text("❗ Usage: /add product_name quantity")

async def minus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        product = context.args[0]
        qty = int(context.args[1])
        user = update.effective_user.username
        update_inventory(product, -qty)
        log_action("Minus", product, qty, user)
        await update.message.reply_text(f"❌ Subtracted {qty} of {product}.")
    except:
        await update.message.reply_text("❗ Usage: /minus product_name quantity")

async def open_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        product = context.args[0]
        qty = int(context.args[1])
        note = ' '.join(context.args[2:]) or "Opened for singles"
        user = update.effective_user.username
        update_inventory(product, -qty)
        log_action("Open", product, qty, user, note)
        await update.message.reply_text(f"📦 Opened {qty} of {product} - {note}")
    except:
        await update.message.reply_text("❗ Usage: /open product_name quantity note")

async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if context.args[0].lower() == "all":
            all_data = inv_sheet.get_all_records()
            msg = "📋 Current Stock:\n"
            for item in all_data:
                msg += f"- {item['Product Name']}: {item['Quantity']}\n"
        else:
            product = context.args[0]
            cell = inv_sheet.find(product)
            qty = inv_sheet.cell(cell.row, cell.col + 1).value
            msg = f"📦 {product}: {qty}"
        await update.message.reply_text(msg)
    except:
        await update.message.reply_text("❗ Usage: /stock product_name OR /stock all")

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(SG_TIME).strftime("%d/%m/%Y")
    records = log_sheet.get_all_records()
    today_logs = [r for r in records if r['Timestamp'].startswith(today)]
    if not today_logs:
        await update.message.reply_text("📭 No activity logged today.")
        return

    msg = f"📊 Daily Report for {today}:\n"
    for log in today_logs:
        note = f"({log['Note']})" if log['Note'] else ""
        msg += f"{log['Timestamp']} - {log['Action']} {log['Quantity']}x {log['Product']} by {log['User']} {note}\n"
    await update.message.reply_text(msg)

if __name__ == '__main__':
    import os
    app = ApplicationBuilder().token(os.getenv("8139322681:AAG106qLNF57Uf-freXqBHwwV_vmlYUAn5E")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("minus", minus))
    app.add_handler(CommandHandler("open", open_product))
    app.add_handler(CommandHandler("stock", stock))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()
