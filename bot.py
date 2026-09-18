import asyncio
import http.server
import logging
import os
import sys
import threading
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv(override=True)

import database
import gemini_agent
import google_sheets_sync
import sheets_sync

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Lightweight Health-check HTTP Server for Free 24/7 Cloud Hosting (Render/Railway)
class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ADS Fashion Telegram Bot is running 24/7 on Cloud!")

    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    try:
        server = http.server.HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info(f"Health-check web server started on port {port}")
    except Exception as e:
        logger.warning(f"Could not start health server on port {port}: {e}")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

admin_raw = os.getenv("ADMIN_CHAT_ID", "6583528395,8485295738")
ADMIN_CHAT_IDS = [int(x.strip()) for x in admin_raw.split(",") if x.strip().lstrip("-").isdigit()]

ai_agent: gemini_agent.GeminiSalesAgent = None

def get_ai_agent() -> gemini_agent.GeminiSalesAgent:
    global ai_agent
    if ai_agent is None:
        ai_agent = gemini_agent.GeminiSalesAgent()
    return ai_agent

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_CHAT_IDS

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_name = os.getenv("STORE_NAME", "ADS Fashion")
    logger.info(f"User {user.id} ({user.full_name}) started the bot.")

    welcome_text = (
        f"আসসালামু আলাইকুম **{user.first_name}**! 👋\n"
        f"স্বাগতম **{store_name}**-এ। আমি আপনার ২৪/৭ এআই সেলস ও কাস্টমার সাপোর্ট অ্যাসিস্ট্যান্ট। 🤖👕\n\n"
        "আমি আপনাকে কীভাবে সাহায্য করতে পারি?\n"
        "• আমাদের সেরা পোশাকের কালেকশন দেখতে বাটনে চাপুন বা লিখুন (যেমন: *পাঞ্জাবি দেখান*, *টি-শার্টের দাম কত?*)\n"
        "• সরাসরি অর্ডার করতে যেকোনো সময় পণ্যের নাম, সাইজ, আপনার নাম, মোবাইল ও ঠিকানা লিখুন।\n"
        "• আপনার অর্ডার ট্র্যাক করতে অর্ডার আইডি বা ফোন নম্বর লিখুন।"
    )

    keyboard = [
        [
            InlineKeyboardButton("🛍️ ফ্যাশন কালেকশন", callback_data="btn_catalog"),
            InlineKeyboardButton("📦 অর্ডার ট্র্যাকিং", callback_data="btn_track")
        ],
        [
            InlineKeyboardButton("💳 পেমেন্ট ও ডেলিভারি তথ্য", callback_data="btn_policy"),
            InlineKeyboardButton("👨‍💼 সরাসরি কথা বলুন", callback_data="btn_support")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_text, 
        reply_markup=reply_markup, 
        parse_mode=ParseMode.MARKDOWN
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "💡 **ADS Fashion বট ব্যবহারের নিয়মাবলী:**\n\n"
        "1. **প্রোডাক্ট দেখা**: আপনি যা খুঁজছেন তা লিখে মেসেজ দিন। যেমন: *'টি-শার্টের সাইজ কি কি আছে?'* বা *'পাঞ্জাবির দাম কত?'*\n"
        "2. **অর্ডার দেওয়া**: আপনি যে পোশাক কিনতে চান তার নাম, সাইজ, আপনার নাম, ফোন নম্বর ও ডেলিভারি ঠিকানা লিখে দিলে অর্ডার কনফার্ম হয়ে যাবে।\n"
        "3. **অর্ডার ট্র্যাকিং**: আপনার অর্ডার আইডি (যেমন `ORD-1001`) বা ফোন নম্বর পাঠালে বর্তমান স্ট্যাটাস দেখতে পাবেন।\n"
        "4. **হিউম্যান সাপোর্ট**: সরাসরি কথা বলতে লিখুন *'সাপোর্ট চাই'* অথবা বাটনে ক্লিক করুন।\n"
        "5. **নতুন করে চ্যাট শুরু করতে**: `/clear` কমান্ড দিন।"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def catalog_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = await database.get_all_products(limit=10)
    if not products:
        await update.message.reply_text("দুঃখিত, ক্যাটালগে বর্তমানে কোনো প্রোডাক্ট নেই।")
        return

    currency = os.getenv("CURRENCY", "৳")
    msg = f"🛍️ **{os.getenv('STORE_NAME', 'ADS Fashion')}-এর বর্তমান কালেকশন (প্রতিটি ৫০টি করে স্টকে আছে):**\n\n"
    for p in products:
        msg += f"🔹 **{p['name']}**\n"
        msg += f"   💰 মূল্য: **{int(p['price'])}{currency}** | ইন-স্টক: {p['stock']} টি\n"
        msg += f"   📝 কোড: `{p['id']}`\n\n"

    msg += "👉 যেকোনো পোশাকের ছবি ও বিস্তারিত দেখতে বা অর্ডার করতে তার নাম লিখে মেসেজ পাঠান!"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await database.clear_user_history(user_id)
    await update.message.reply_text("🧹 আপনার সাথে পূর্বের সমস্ত কথোপকথন রিসেট করা হয়েছে। আপনি নতুন করে কথা শুরু করতে পারেন!")

# --- Admin Commands ---

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ আপনি অ্যাডমিন হিসেবে অনুমোদিত নন।")
        return

    admin_help = (
        "⚙️ **ADS Fashion অ্যাডমিন কন্ট্রোল প্যানেল:**\n\n"
        "• `/orders` - সাম্প্রতিক ১০টি অর্ডার দেখুন\n"
        "• `/status <ORDER_ID> <STATUS>` - অর্ডারের স্ট্যাটাস পরিবর্তন করুন (Pending, Confirmed, Shipped, Delivered)\n"
        "• `/sync` - ক্যাটালগ ও স্টক রিফ্রেশ করুন\n\n"
        "📊 **গুগল শিট নোটিফিকেশন:** নতুন যেকোনো অর্ডার আসলে আপনার এখানে নোটিফিকেশন আসবে এবং স্বয়ংক্রিয়ভাবে গুগল শিটে 'All Orders' ও 'Inside/Outside Dhaka' শিটে এন্ট্রি হয়ে যাবে!"
    )
    await update.message.reply_text(admin_help, parse_mode=ParseMode.MARKDOWN)

async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ অ্যাডমিন অনুমতি নেই।")
        return

    orders = await database.get_recent_orders(limit=10)
    if not orders:
        await update.message.reply_text("এখনো কোনো নতুন অর্ডার আসেনি।")
        return

    currency = os.getenv("CURRENCY", "৳")
    res = "📋 **ADS Fashion - সাম্প্রতিক অর্ডারের তালিকা:**\n\n"
    for o in orders:
        zone = google_sheets_sync.determine_zone(o['shipping_address'], o['total_amount'], o['items_summary'])
        res += (
            f"🔹 **আইডি:** `{o['id']}` | **স্ট্যাটাস:** `{o['status']}`\n"
            f"   👤 নাম: {o['customer_name']} | 📱 ফোন: `{o['customer_phone']}`\n"
            f"   📍 ঠিকানা: {o['shipping_address']} ({zone})\n"
            f"   📦 পণ্য: {o['items_summary']}\n"
            f"   💰 মোট বিল: {o['total_amount']}{currency} ({o['payment_method']})\n"
            f"   🕒 সময়: {o['created_at']}\n"
            "-----------------------------\n"
        )
    await update.message.reply_text(res, parse_mode=ParseMode.MARKDOWN)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("ব্যবহার নিয়ম: `/status <ORDER_ID> <NEW_STATUS>`\nযেমন: `/status ORD-1003 Shipped`")
        return

    order_id = context.args[0]
    new_status = context.args[1]
    success = await database.update_order_status(order_id, new_status)
    if success:
        await update.message.reply_text(f"✅ অর্ডার `{order_id.upper()}`-এর স্ট্যাটাস পরিবর্তন করে `{new_status.capitalize()}` করা হয়েছে।", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"❌ অর্ডার `{order_id}` খুঁজে পাওয়া যায়নি।", parse_mode=ParseMode.MARKDOWN)

# --- Callback Queries ---

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "btn_catalog":
        products = await database.get_all_products(limit=5)
        currency = os.getenv("CURRENCY", "৳")
        for p in products:
            btn_buy = InlineKeyboardMarkup([[
                InlineKeyboardButton("🛒 এটি অর্ডার করতে চাই", callback_data=f"buy_{p['id']}")
            ]])
            caption = (
                f"🏷️ **{p['name']}**\n"
                f"💰 মূল্য: **{int(p['price'])}{currency}**\n"
                f"📝 বিবরণ: {p['description']}\n"
                f"📦 ইন-স্টক: {p['stock']} টি"
            )
            if p.get("image_url"):
                try:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=p["image_url"],
                        caption=caption,
                        reply_markup=btn_buy,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    continue
                except Exception as e:
                    logger.warning(f"Could not send photo: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=caption,
                reply_markup=btn_buy,
                parse_mode=ParseMode.MARKDOWN
            )

    elif data.startswith("buy_"):
        product_id = data.split("buy_")[1]
        prod = await database.get_product_by_id(product_id)
        if prod:
            await query.message.reply_text(
                f"আপনি **{prod['name']}** অর্ডার করতে চাচ্ছেন। 🎉\n\n"
                "দয়া করে আপনার:\n"
                "১. **পছন্দের সাইজ ও কালার**\n"
                "২. **আপনার পূর্ণ নাম**\n"
                "৩. **সচল মোবাইল নম্বর**\n"
                "৪. **সম্পূর্ণ ডেলিভারি ঠিকানা** (জেলা সহ)\n"
                "৫. **পেমেন্ট মেথড** (ক্যাশ অন ডেলিভারি নাকি বিকাশ/নগদ)\n\n"
                "লিখে মেসেজ পাঠান, আমি এখনই আপনার অর্ডার কনফার্ম করে দিচ্ছি!",
                parse_mode=ParseMode.MARKDOWN
            )

    elif data == "btn_track":
        await query.message.reply_text(
            "📦 আপনার অর্ডার ট্র্যাক করতে অনুগ্রহ করে আপনার **অর্ডার আইডি** (যেমন: `ORD-1003`) অথবা আপনার মোবাইল নম্বরটি লিখে পাঠান।",
            parse_mode=ParseMode.MARKDOWN
        )

    elif data == "btn_policy":
        fee_dhaka = os.getenv("DELIVERY_FEE_INSIDE_DHAKA", "60")
        fee_outside = os.getenv("DELIVERY_FEE_OUTSIDE_DHAKA", "120")
        bkash = os.getenv("BKASH_NUMBER", "01631188500")
        currency = os.getenv("CURRENCY", "৳")

        policy_text = (
            f"🚚 **ADS Fashion ডেলিভারি চার্জ ও সময়:**\n"
            f"• ঢাকার ভেতরে: **{fee_dhaka}{currency}** (২৪-৪৮ ঘণ্টা)\n"
            f"• ঢাকার বাইরে: **{fee_outside}{currency}** (৩-৫ দিন)\n\n"
            f"💳 **পেমেন্ট মেথড:**\n"
            f"• ক্যাশ অন ডেলিভারি (পণ্য হাতে পেয়ে টাকা)\n"
            f"• বিকাশ / নগদ: `{bkash}` (Personal)\n\n"
            f"🔄 **রিটার্ন পলিসি:**\n"
            f"সাইজ না মিললে বা কোনো সমস্যা থাকলে ৭ দিনের মধ্যে ফ্রি এক্সচেঞ্জ গ্যারান্টি।"
        )
        await query.message.reply_text(policy_text, parse_mode=ParseMode.MARKDOWN)

    elif data == "btn_support":
        await query.message.reply_text(
            "👨‍💼 ADS Fashion কাস্টমার কেয়ার। আপনি কী বিষয়ে কথা বলতে চান তা লিখে মেসেজ দিন, আমাদের টিম মেম্বার আপনাকে সহায়তা করবেন।"
        )

# --- Message Handler ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()

    # CHECK: Is this a reply from ADMIN in the admin chat?
    if is_admin(user_id) and update.message.reply_to_message:
        replied_msg_id = update.message.reply_to_message.message_id
        target_customer_id = await database.get_user_id_by_admin_message(replied_msg_id)
        if target_customer_id:
            try:
                admin_forward_text = f"👨‍💼 **ADS Fashion সাপোর্ট ম্যানেজারের বার্তা:**\n\n{text}"
                await context.bot.send_message(
                    chat_id=target_customer_id,
                    text=admin_forward_text,
                    parse_mode=ParseMode.MARKDOWN
                )
                await update.message.reply_text("✅ আপনার বার্তাটি সরাসরি কাস্টমারের কাছে পৌঁছে দেওয়া হয়েছে।")
                return
            except Exception as e:
                logger.error(f"Failed to forward admin reply to user {target_customer_id}: {e}")
                await update.message.reply_text(f"❌ কাস্টমারকে বার্তা পাঠানো যায়নি: {e}")
                return

    # Normal Customer Message -> Process with Gemini AI Agent
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        agent = get_ai_agent()
        reply_text, side_effects = await agent.chat(telegram_user_id=user_id, user_text=text)

        await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)

        # Process side-effects
        for effect in side_effects:
            etype = effect.get("type")

            # 1. New Order Placed -> Send to Google Sheet & Notify Admin!
            if etype == "order_placed" and ADMIN_CHAT_IDS:
                o = effect["order"]
                currency = os.getenv("CURRENCY", "৳")
                
                # Send to Google Sheets and Backup CSV
                sheet_res = await google_sheets_sync.send_order_to_google_sheet(o)
                zone = sheet_res.get("zone", "Outside Dhaka")

                admin_alert = (
                    f"🔔 **আপনার নতুন অর্ডার গুগল শিটে যুক্ত করা হয়েছে!** 📊\n\n"
                    f"🆔 **অর্ডার আইডি:** `{o['order_id']}`\n"
                    f"👤 **কাস্টমার:** {o['customer_name']}\n"
                    f"📱 **মোবাইল:** `{o['customer_phone']}`\n"
                    f"📍 **ঠিকানা:** {o['shipping_address']}\n"
                    f"🚚 **ক্যাটাগরি:** **{zone}** (শিটের '{zone}' স্লাইডে এন্ট্রি হয়েছে)\n"
                    f"📦 **পণ্য ও সাইজ:** {o['items']}\n"
                    f"💰 **সর্বমোট বিল:** {o['total_price']}{currency}\n"
                    f"💳 **পেমেন্ট মেথড:** {o['payment_method']}\n"
                    f"🔖 **TrxID:** {o.get('trx_id') or 'N/A'}\n"
                    f"🕒 কাস্টমার টেলিগ্রাম আইডি: `{o['telegram_user_id']}`\n\n"
                    "👉 আপনি এই মেসেজে **Reply** দিলে সরাসরি কাস্টমার উত্তর পেয়ে যাবে।"
                )
                for aid in ADMIN_CHAT_IDS:
                    try:
                        admin_msg = await context.bot.send_message(
                            chat_id=aid,
                            text=admin_alert,
                            parse_mode=ParseMode.MARKDOWN
                        )
                        await database.record_support_ticket(
                            telegram_user_id=user_id,
                            user_name=o['customer_name'],
                            admin_message_id=admin_msg.message_id
                        )
                    except Exception as e_send:
                        logger.warning(f"Could not send alert to admin {aid}: {e_send}")

            # 2. Human Support Escalation
            elif etype == "human_escalated" and ADMIN_CHAT_IDS:
                reason = effect.get("reason", "Customer requested human support.")
                admin_ticket_text = (
                    f"⚠️ **ADS Fashion সাপোর্ট রিকোয়েস্ট**\n\n"
                    f"👤 কাস্টমার: {user.full_name} (@{user.username or 'N/A'})\n"
                    f"🆔 ইউজার আইডি: `{user_id}`\n"
                    f"💬 কারণ: *{reason}*\n"
                    f"📝 সর্বশেষ মেসেজ: \"{text}\"\n\n"
                    "👉 কাস্টমারকে উত্তর দিতে এই মেসেজে **Reply** করুন।"
                )
                for aid in ADMIN_CHAT_IDS:
                    try:
                        admin_msg = await context.bot.send_message(
                            chat_id=aid,
                            text=admin_ticket_text,
                            parse_mode=ParseMode.MARKDOWN
                        )
                        await database.record_support_ticket(
                            telegram_user_id=user_id,
                            user_name=user.full_name,
                            admin_message_id=admin_msg.message_id
                        )
                    except Exception as e_send:
                        logger.warning(f"Could not send escalation to admin {aid}: {e_send}")

            # 3. Products Found -> Display visual photo cards
            elif etype == "products_found":
                prods = effect.get("products", [])
                currency = os.getenv("CURRENCY", "৳")
                for p in prods[:2]:
                    if p.get("image_url"):
                        buy_markup = InlineKeyboardMarkup([[
                            InlineKeyboardButton("🛒 এটি অর্ডার করতে চাই", callback_data=f"buy_{p['id']}")
                        ]])
                        caption = f"🏷️ **{p['name']}**\n💰 মূল্য: **{int(p['price'])}{currency}**"
                        try:
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=p["image_url"],
                                caption=caption,
                                reply_markup=buy_markup,
                                parse_mode=ParseMode.MARKDOWN
                            )
                        except Exception as img_err:
                            logger.debug(f"Photo send skipped: {img_err}")

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        await update.message.reply_text(
            "দুঃখিত, আপনার অনুরোধটি প্রসেস করতে একটি সাময়িক ত্রুটি হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।"
        )

# --- Main Entry Point ---

def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        print("❌ ERROR: TELEGRAM_BOT_TOKEN সেট করা হয়নি!")
        return

    # Start health check server for Render/Railway free 24/7 hosting
    start_health_server()

    asyncio.run(database.init_db())
    asyncio.run(database.seed_products_from_json("catalog.json"))

    print("🤖 Starting ADS Fashion Sales & Support Bot with Multi-Admin & Google Sheets...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("catalog", catalog_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("track", lambda u, c: u.message.reply_text("আপনার অর্ডার আইডি বা ফোন নম্বর লিখুন:")))

    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("status", status_command))

    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ ADS Fashion Bot is polling for messages. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
