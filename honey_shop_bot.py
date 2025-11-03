# HoneyShopBot Pro v15.0 — Professional Telegram E-commerce Bot
import os
import json
import logging
import random
import string
import sqlite3
from datetime import datetime, date
import telebot
from telebot import types
import re

# ----------------------- Configuration -----------------------
import os
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
SHOP_NAME = "HoneyShop"
CURRENCY = "USD"
BANK_CARD = '1234-5678-9012-3456'
BANK_OWNER = 'John Doe'
POST_TRACKING_URL = "https://example.com/track?code={code}"
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
ORDERS_DIR = os.path.join(BASE_DIR, 'orders')
INVOICES_JSON = os.path.join(ORDERS_DIR, 'invoices.json')
DB_FILE = os.path.join(ORDERS_DIR, 'honeyshop.db')
os.makedirs(ORDERS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("HoneyShopBot")

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

def fa_to_en(text: str) -> str:
    return text.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))

def update_database_schema():
    try:
        cursor.execute("PRAGMA table_info(customers)")
        cols = [c[1] for c in cursor.fetchall()]
        for col in ['phone_mobile', 'phone_fixed', 'postal_code', 'city', 'address']:
            if col not in cols:
                cursor.execute(f"ALTER TABLE customers ADD COLUMN {col} TEXT")
        cursor.execute("PRAGMA table_info(orders)")
        cols = [c[1] for c in cursor.fetchall()]
        for col, sql in [
            ('tracking_code', 'TEXT'), ('shipped', 'INTEGER DEFAULT 0'),
            ('delivered', 'INTEGER DEFAULT 0'), ('rating', 'INTEGER'), ('feedback', 'TEXT')
        ]:
            if col not in cols:
                cursor.execute(f"ALTER TABLE orders ADD COLUMN {col} {sql}")
        conn.commit()
    except Exception as e:
        logger.warning(f"Schema update: {e}")

update_database_schema()

cursor.executescript('''
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE,
    first_name TEXT, last_name TEXT, city TEXT, address TEXT,
    phone_mobile TEXT, phone_fixed TEXT, postal_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, items_json TEXT,
    total_price INTEGER, discount_code TEXT, final_price INTEGER,
    receipt_file_id TEXT, payment_status TEXT DEFAULT 'pending',
    confirmed_by_admin INTEGER DEFAULT 0, tracking_code TEXT,
    shipped INTEGER DEFAULT 0, delivered INTEGER DEFAULT 0,
    rating INTEGER, feedback TEXT, notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS discount_codes (
    user_id INTEGER PRIMARY KEY, code TEXT UNIQUE, used INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
''')
conn.commit()

PRODUCTS = {
    "p1": {"name": "Gon Honey 800g", "price": 95},
    "p2": {"name": "Barberry Honey 800g", "price": 95}
}

user_cart = {}
user_states = {}
admin_pending_tracking = {}

def generate_unique_code(user_id: int) -> str:
    r = cursor.execute('SELECT code FROM discount_codes WHERE user_id = ?', (user_id,)).fetchone()
    if r and r['code']: return r['code']
    for _ in range(5):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        try:
            cursor.execute('INSERT INTO discount_codes (user_id, code) VALUES (?, ?)', (user_id, code))
            conn.commit()
            return code
        except sqlite3.IntegrityError:
            continue
    return cursor.execute('SELECT code FROM discount_codes WHERE user_id = ?', (user_id,)).fetchone()['code']

def is_code_used(user_id: int) -> bool:
    r = cursor.execute('SELECT used FROM discount_codes WHERE user_id = ?', (user_id,)).fetchone()
    return bool(r and r['used'])

def mark_code_used_for_user(user_id: int):
    cursor.execute('UPDATE discount_codes SET used = 1 WHERE user_id = ?', (user_id,))
    conn.commit()

def calculate_cart_total(cart: list, user_id: int, code: str):
    total = sum(it['price'] * it['qty'] for it in cart)
    discount = int(total * 0.10) if code and not is_code_used(user_id) else 0
    return total, discount, total - discount

def save_invoice_to_json(order_row):
    try:
        invoices = json.load(open(INVOICES_JSON, 'r', encoding='utf-8')) if os.path.exists(INVOICES_JSON) else []
        data = dict(order_row)
        data['items'] = json.loads(order_row['items_json'])
        invoices.append(data)
        json.dump(invoices, open(INVOICES_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=4)
    except Exception as e:
        logger.exception(f"JSON save error: {e}")

bot = telebot.TeleBot(BOT_TOKEN)

WELCOME_MESSAGE = """
Welcome to *{shop_name}*, {name}!

Thank you for choosing premium natural honey.

Browse products and enjoy shopping!
"""

CUSTOMER_FINAL_MESSAGE = """
Thank you, {name}!

Order confirmed.  
Invoice: `#{order_id}`  
Paid: `{final:,} {currency}`

Full invoice in next message.

Shipped within 24 hours.

Support: `+1-234-567-890`
"""

SHIPPING_MESSAGE = """
Order Shipped!

Invoice: `#{order_id}`  
Tracking: `{tracking}`

[Track here]({url})

Confirm delivery below:
"""

def send_main_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Products", callback_data="show_products"),
        types.InlineKeyboardButton("Track Order", callback_data="track_order")
    )
    markup.add(
        types.InlineKeyboardButton("Support", callback_data="support"),
        types.InlineKeyboardButton("Cart", callback_data="show_cart")
    )
    bot.send_message(chat_id, "Main Menu:", reply_markup=markup)

@bot.message_handler(commands=['start'])
def cmd_start(m):
    uid = m.from_user.id
    name = m.from_user.first_name or "Customer"
    user_states[uid] = {'step': 'main_menu'}
    user_cart[uid] = []
    code = generate_unique_code(uid)
    user_states[uid]['discount_code'] = None if is_code_used(uid) else code

    bot.send_message(m.chat.id, WELCOME_MESSAGE.format(shop_name=SHOP_NAME, name=name), parse_mode='Markdown')
    if user_states[uid]['discount_code']:
        bot.send_message(m.chat.id, f"10% Discount Code: `{user_states[uid]['discount_code']}`", parse_mode='Markdown')
    send_main_menu(m.chat.id)

def send_products_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for pid, info in PRODUCTS.items():
        markup.add(types.InlineKeyboardButton(
            f"{info['name']} — {info['price']:,} {CURRENCY}",
            callback_data=f"add:{pid}:1"
        ))
    markup.add(types.InlineKeyboardButton("View Cart", callback_data="show_cart"))
    markup.add(types.InlineKeyboardButton("Back", callback_data="main_menu"))
    bot.send_message(chat_id, "Available Products:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == 'show_products')
def cb_show_products(c):
    send_products_menu(c.message.chat.id)
    try: bot.delete_message(c.message.chat.id, c.message.message_id)
    except: pass

# ... (rest of bot logic - full code in previous message)

if __name__ == '__main__':
    logger.info("HoneyShopBot v15.0 started")
    bot.infinity_polling()
