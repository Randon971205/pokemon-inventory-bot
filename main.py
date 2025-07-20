import os
import json
import logging
import gspread
import pytz
from google.oauth2.service_account import Credentials
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Load and authorize Google Sheets credentials
creds_json = os.getenv("GOOGLE_SHEET_CREDENTIALS")
if not creds_json:
    raise Exception("GOOGLE_SHEET_CREDENTIALS environment variable not set.")

creds_dict = json.loads(creds_json)
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(credentials)

# Start dummy HTTP server for Render health check
def run_dummy_server():
    class DummyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Telegram bot is running!')
    server = HTTPServer(('0.0.0.0', 10000), DummyHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server).start()

# Logging
logging.basicConfig(level=logging.INFO)

# Timezone
SG_TIME = pytz.timezone("Asia/Singapore")

# Auth control
OTP_CODE = "PPLaoBan"
AUTHORIZED_USERS = set()

# Access sheets
try:
    sheet = client.open("PokemonInventory")
    inv_sheet = sheet.worksheet("Inventory")
    log_sheet = sheet.worksheet("Logs")
except Exception as e:
    raise Exception(f"Failed to access Google Sheet: {e}")

# Log inventory changes
def log_action(action, product, qty, user, stock_type, note=""):
    now = datetime.now(SG_TIME).strftime("%d/%m/%Y %H:%M:%S")
    log_sheet.append_row([now, action, product, stock_type, qty, f"@{user}", note])

# Update inventory count
def update_inventory(product, stock_type, delta):
    try:
        records = inv_sheet.get_all_records()
        for i, row in enumerate(records, start=2):
            if row['Product Name'] == product and row['Stock Type'] == stock_type:
                new_qty = int(row['Quantity']) + delta
                inv_sheet.update_cell(i, 3, new_qty)
                return
        inv_sheet.append_row([product, stock_type, delta])
    except Exception as e:
        logging.error(f"Inventory update failed: {e}")

# Telegram handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in AUTHORIZED_USERS:
        await send_main_menu(update)
        return
    await update.message.reply_text("🔐 Please enter the OTP to access the bot.")

async def otp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    if user_id in AUTHORIZED_USERS:
        return
    if message_text == OTP_CODE:
        AUTHORIZED_USERS.add(user_id)
        await update.message.reply_text("✅ Login successful!")
        await send_main_menu(update)
    else:
        await update.message.reply_text("❌ Invalid OTP. Please try again.")

async def send_main_menu(update: Update):
    keyboard = [
        [InlineKeyboardButton("📥 Add", callback_data='add')],
        [InlineKeyboardButton("❌ Minus", callback_data='minus')],
        [InlineKeyboardButton("📦 Open", callback_data='open')],
        [InlineKeyboardButton("📊 Stock", callback_data='stock')],
        [InlineKeyboardButton("📈 Report", callback_data='report')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👋 Welcome Laoban to the Pokémon Inventory Bot!\nChoose a command:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    command_map = {
        "add": "/add [product_name] [qty] [Loose|Keep Sealed|Bag of 50]",
        "minus": "/minus [product_name] [qty] [Loose|Keep Sealed|Bag of 50]",
        "open": "/open [product_name] [qty] [Loose|Keep Sealed|Bag of 50] [note]",
        "stock": "/stock [product_name] or /stock all",
        "report": "/report"
    }
    message = f"📌 Usage for `{query.data}`:\n{command_map[query.data]}"
    await query.edit_message_text(text=message, parse_mode="Markdown")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        product = context.args[0]
        qty = int(context.args[1])
        stock_type = context.args[2] if len(context.args) > 2 else "Loose"
        user = update.effective_user.username
        update_inventory(product, stock_type, qty)
        log_action("Add", product, qty, user, stock_type)
        await update.message.reply_text(f"✅ Added {qty} of {product} ({stock_type}).")
    except:
        await update.message.reply_text("❗ Usage: /add product_name qty [Loose|Keep Sealed|Bag of 50]")

async def minus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        product = context.args[0]
        qty = int(context.args[1])
        stock_type = context.args[2] if len(context.args) > 2 else "Loose"
        user = update.effective_user.username
        update_inventory(product, stock_type, -qty)
        log_action("Minus", product, qty, user, stock_type)
        await update.message.reply_text(f"❌ Subtracted {qty} of {product} ({stock_type}).")
    except:
        await update.message.reply_text("❗ Usage: /minus product_name qty [Loose|Keep Sealed|Bag of 50]")

async def open_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        product = context.args[0]
        qty = int(context.args[1])
        stock_type = context.args[2]
        note = ' '.join(context.args[3:]) or "Opened for singles"
        user = update.effective_user.username
        update_inventory(product, stock_type, -qty)
        log_action("Open", product, qty, user, stock_type, note)
        await update.message.reply_text(f"📦 Opened {qty} of {product} ({stock_type}) - {note}")
    except:
        await update.message.reply_text("❗ Usage: /open product_name qty stock_type note")

async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if context.args[0].lower() == "all":
            all_data = inv_sheet.get_all_records()
            msg = "📋 Current Stock:\n"
            for item in all_data:
                msg += f"- {item['Product Name']} ({item['Stock Type']}): {item['Quantity']}\n"
        else:
            product = context.args[0]
            all_data = inv_sheet.get_all_records()
            matches = [i for i in all_data if i['Product Name'] == product]
            if not matches:
                msg = f"❌ No data found for {product}"
            else:
                msg = f"📦 Stock for {product}:\n"
                for i in matches:
                    msg += f"- {i['Stock Type']}: {i['Quantity']}\n"
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
        msg += f"{log['Timestamp']} - {log['Action']} {log['Quantity']}x {log['Product']} ({log['Stock Type']}) by {log['User']} {note}\n"
    await update.message.reply_text(msg)

if __name__ == '__main__':
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN environment variable not found!")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("minus", minus))
    app.add_handler(CommandHandler("open", open_product))
    app.add_handler(CommandHandler("stock", stock))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, otp_handler))
    print("Starting Telegram bot...")
    app.run_polling()
