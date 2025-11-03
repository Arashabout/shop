import telebot
import sqlite3
import logging
import os
import re
from datetime import datetime

# --- Configuration (SAFE - NO TOKEN IN CODE) ---
BOT_TOKEN = os.getenv('BOT_TOKEN')  # از Render میاد
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))

# --- Validate Token ---
if not BOT_TOKEN or ':' not in BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing or invalid! Set it in Render Environment Variables.")

# --- Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)
conn = sqlite3.connect('shop.db', check_same_thread=False)
cursor = conn.cursor()

# --- Database Setup ---
def init_db():
    cursor.execute('CREATE TABLE IF NOT EXISTS customers (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, address TEXT, join_date TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS cart (user_id INTEGER, product TEXT, quantity INTEGER, price REAL)')
    cursor.execute('CREATE TABLE IF NOT EXISTS orders (order_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, items TEXT, total REAL, status TEXT, tracking_code TEXT, receipt_photo TEXT, rating INTEGER)')
    conn.commit()
    logger.info("Database schema updated.")

init_db()

# --- Products ---
products = {
    "موبایل سامسونگ": 12000000,
    "لپ‌تاپ دل": 25000000,
    "هدفون سونی": 1500000
}

# --- Menus ---
def main_menu():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("محصولات", "سبد خرید")
    markup.add("پشتیبانی", "راهنما")
    return markup

def products_menu():
    markup = telebot.types.InlineKeyboardMarkup()
    for name, price in products.items():
        markup.add(telebot.types.InlineKeyboardButton(f"{name} - {price:,} تومان", callback_data=f"add_{name}"))
    markup.add(telebot.types.InlineKeyboardButton("بازگشت", callback_data="back"))
    return markup

def cart_menu(user_id):
    markup = telebot.types.InlineKeyboardMarkup()
    cursor.execute("SELECT product, quantity FROM cart WHERE user_id=?", (user_id,))
    items = cursor.fetchall()
    for product, qty in items:
        markup.add(
            telebot.types.InlineKeyboardButton(f"➖", callback_data=f"dec_{product}"),
            telebot.types.InlineKeyboardButton(f"{qty} × {product}", callback_data="info"),
            telebot.types.InlineKeyboardButton(f"➕", callback_data=f"inc_{product}")
        )
        markup.add(telebot.types.InlineKeyboardButton(f"حذف {product}", callback_data=f"del_{product}"))
    if items:
        markup.add(telebot.types.InlineKeyboardButton("ثبت سفارش", callback_data="checkout"))
    markup.add(telebot.types.InlineKeyboardButton("بازگشت", callback_data="back"))
    return markup

# --- Handlers ---
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    cursor.execute("INSERT OR IGNORE INTO customers (user_id) VALUES (?)", (user_id,))
    conn.commit()
    bot.send_message(
        user_id,
        "به *HoneyShop* خوش آمدید! \n"
        "تخفیف ۱۰٪ برای اولین خرید \n"
        "منو را انتخاب کنید:",
        reply_markup=main_menu(),
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda m: m.text == "محصولات")
def show_products(message):
    bot.send_message(message.from_user.id, "محصولات موجود:", reply_markup=products_menu())

@bot.message_handler(func=lambda m: m.text == "سبد خرید")
def show_cart(message):
    user_id = message.from_user.id
    cursor.execute("SELECT product, quantity, price FROM cart WHERE user_id=?", (user_id,))
    items = cursor.fetchall()
    if not items:
        bot.send_message(user_id, "سبد خرید خالی است.")
        return
    total = sum(qty * price for _, qty, price in items)
    discount = total * 0.1 if total >= 10000000 else 0
    final = int(total - discount)
    text = "سبد خرید شما:\n\n"
    for product, qty, price in items:
        text += f"• {product} × {qty} = {qty * price:,} تومان\n"
    text += f"\nجمع: {total:,} تومان"
    if discount > 0:
        text += f"\nتخفیف ۱۰٪: -{int(discount):,} تومان"
    text += f"\nپرداخت نهایی: {final:,} تومان"
    bot.send_message(user_id, text, reply_markup=cart_menu(user_id))

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data

    if data.startswith("add_"):
        product = data[4:]
        price = products[product]
        cursor.execute("INSERT INTO cart (user_id, product, quantity, price) VALUES (?, ?, 1, ?)", (user_id, product, price))
        conn.commit()
        bot.answer_callback_query(call.id, f"{product} به سبد اضافه شد!")

    elif data.startswith("inc_"):
        product = data[4:]
        cursor.execute("UPDATE cart SET quantity = quantity + 1 WHERE user_id=? AND product=?", (user_id, product))
        conn.commit()

    elif data.startswith("dec_"):
        product = data[4:]
        cursor.execute("SELECT quantity FROM cart WHERE user_id=? AND product=?", (user_id, product))
        qty = cursor.fetchone()[0]
        if qty > 1:
            cursor.execute("UPDATE cart SET quantity = quantity - 1 WHERE user_id=? AND product=?", (user_id, product))
        else:
            cursor.execute("DELETE FROM cart WHERE user_id=? AND product=?", (user_id, product))
        conn.commit()

    elif data.startswith("del_"):
        product = data[4:]
        cursor.execute("DELETE FROM cart WHERE user_id=? AND product=?", (user_id, product))
        conn.commit()

    elif data == "checkout":
        cursor.execute("SELECT product, quantity, price FROM cart WHERE user_id=?", (user_id,))
        items = cursor.fetchall()
        total = sum(qty * price for _, qty, price in items)
        discount = total * 0.1 if total >= 10000000 else 0
        final = int(total - discountide discount)
        items_text = ", ".join(f"{p}×{q}" for p, q, _ in items)
        order_id = cursor.execute("INSERT INTO orders (user_id, items, total, status) VALUES (?, ?, ?, 'pending')",
                                  (user_id, items_text, final)).lastrowid
        conn.commit()
        cursor.execute("DELETE FROM cart WHERE user_id=?", (user_id,))
        conn.commit()
        bot.send_message(user_id, f"سفارش #{order_id} ثبت شد!\nمبلغ قابل پرداخت: {final:,} تومان\nلطفاً رسید واریز را ارسال کنید:")
        bot.register_next_step_handler_by_chat_id(user_id, receive_receipt, order_id)

    elif data == "back":
        bot.send_message(user_id, "منوی اصلی:", reply_markup=main_menu())

    # Refresh cart
    if data not in ["back", "checkout"]:
        try:
            bot.edit_message_reply_markup(user_id, call.message.id, reply_markup=cart_menu(user_id))
        except:
            pass

def receive_receipt(message, order_id):
    if message.photo:
        file_id = message.photo[-1].file_id
        cursor.execute("UPDATE orders SET receipt_photo=?, status='paid' WHERE order_id=?", (file_id, order_id))
        conn.commit()
        bot.send_message(message.from_user.id, "رسید دریافت شد! سفارش در حال پردازش است...")
        bot.send_message(ADMIN_ID, f"رسید جدید برای سفارش #{order_id} از کاربر {message.from_user.id}")
    else:
        bot.send_message(message.from_user.id, "لطفاً عکس رسید را ارسال کنید.")
        bot.register_next_step_handler_by_chat_id(message.from_user.id, receive_receipt, order_id)

# --- Admin Panel ---
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    markup = telebot.types.ReplyKeyboardMarkup()
    markup.add("سفارشات", "ارسال کد رهگیری")
    bot.send_message(message.from_user.id, "پنل ادمین:", reply_markup=markup)

# --- Start Bot ---
if __name__ == '__main__':
    logger.info("HoneyShopBot v15.0 (DEMO) started")
    try:
        bot.infinity_polling()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        bot.infinity_polling()
