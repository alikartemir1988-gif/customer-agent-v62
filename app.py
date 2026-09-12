import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, jsonify, request

try:
    import psycopg
except ImportError:  # Optional for local SQLite development.
    psycopg = None


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = (
    os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    or os.environ.get("WEBHOOK_SECRET", "")
).strip()
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "").strip()
DASHBOARD_SESSION_SECRET = os.environ.get("DASHBOARD_SESSION_SECRET", "").strip()
META_PAGE_ACCESS_TOKEN = os.environ.get("META_PAGE_ACCESS_TOKEN", "").strip()
META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "").strip()
META_APP_SECRET = os.environ.get("META_APP_SECRET", "").strip()
META_GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v23.0").strip()
DB_PATH = os.environ.get("DB_PATH", "customer_agent.db").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
APP_VERSION = "6.3.1"
GIT_COMMIT = os.environ.get("RENDER_GIT_COMMIT", "").strip()

API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

app = Flask(__name__)
MAX_REQUEST_BYTES = 256 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES

SESSIONS = {}

ORDER_STATUSES = frozenset({
    "new", "confirmed", "processing", "shipped", "delivered", "cancelled",
})
CONFIGURATION_ERRORS = []


# =========================================================
# PRODUCTS
# =========================================================

DEFAULT_PRODUCTS = {
    "الجهاز": {
        "price": 30.0,
        "currency": "$",
        "available": True,
        "colors": ["أسود", "أبيض"],
        "payment_methods": ["الدفع عند الاستلام"],
        "aliases": [
            "الجهاز",
            "جهاز",
            "أجهزة",
            "اجهزة",
            "الأجهزة",
            "الاجهزة",
        ],
    },

    "منتج تجريبي": {
        "price": 30.0,
        "currency": "$",
        "available": True,
        "colors": ["أسود"],
        "payment_methods": ["الدفع عند الاستلام"],
        "aliases": [
            "منتج تجريبي",
            "التجريبي",
        ],
    },
}


# =========================================================
# DELIVERY
# =========================================================

DEFAULT_DELIVERY = {
    "حلب": "2-3 أيام",
    "دمشق": "3-5 أيام",
    "حمص": "2-4 أيام",
    "اللاذقية": "2-4 أيام",
    "الحسكة": "2-4 أيام",
}


def _valid_text_list(value, allow_text=False):

    if allow_text and isinstance(value, str):
        return bool(value.strip())

    return (
        isinstance(value, list)
        and all(
            isinstance(item, str) and item.strip()
            for item in value
        )
    )


def _valid_products(value):

    for name, data in value.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(data, dict)
        ):
            return False

        price = data.get("price")
        if (
            isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not math.isfinite(float(price))
            or price < 0
        ):
            return False

        if not isinstance(data.get("currency"), str) or not data["currency"].strip():
            return False

        if "available" in data and not isinstance(data["available"], bool):
            return False

        if "aliases" in data and not _valid_text_list(data["aliases"]):
            return False

        for key in ("colors", "payment_methods"):
            if key in data and not _valid_text_list(data[key], allow_text=True):
                return False

    return True


def _valid_delivery(value):

    return all(
        isinstance(city, str)
        and city.strip()
        and isinstance(duration, str)
        and duration.strip()
        for city, duration in value.items()
    )


def _json_env(name, default, validator):

    raw = os.environ.get(name, "").strip()
    if not raw:
        return default

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        CONFIGURATION_ERRORS.append(f"{name} must be valid JSON")
        return default

    if not isinstance(value, dict) or not value or not validator(value):
        CONFIGURATION_ERRORS.append(f"{name} has an invalid schema")
        return default

    return value


PRODUCTS = _json_env("PRODUCTS_JSON", DEFAULT_PRODUCTS, _valid_products)
DELIVERY = _json_env("DELIVERY_JSON", DEFAULT_DELIVERY, _valid_delivery)


CITIES = [
    "ريف دمشق",
    "أشرفية صحنايا",
    "معضمية الشام",
    "دير عطية",
    "رأس العين",
    "جسر الشغور",
    "معرة النعمان",
    "معرة مصرين",
    "بصرى الشام",
    "تل أبيض",
    "خان أرنبة",
    "عين العرب",
    "تل رفعت",

    "دمشق",
    "دوما",
    "حرستا",
    "عربين",
    "سقبا",
    "حمورية",
    "زملكا",
    "جرمانا",
    "صحنايا",
    "داريا",
    "قدسيا",
    "الهامة",
    "التل",
    "يبرود",
    "النبك",
    "القطيفة",
    "الزبداني",
    "مضايا",
    "بلودان",
    "قطنا",
    "الكسوة",

    "حلب",
    "منبج",
    "الباب",
    "اعزاز",
    "أعزاز",
    "عفرين",
    "جرابلس",
    "السفيرة",
    "دير حافر",
    "مسكنة",
    "كوباني",
    "مارع",
    "الاتارب",
    "الأتارب",

    "حمص",
    "تدمر",
    "الرستن",
    "تلبيسة",
    "القصير",
    "تلكلخ",
    "المخرم",
    "القريتين",
    "الحولة",

    "حماة",
    "سلمية",
    "مصياف",
    "محردة",
    "السقيلبية",
    "صوران",
    "كفرزيتا",

    "اللاذقية",
    "جبلة",
    "القرداحة",
    "الحفة",
    "كسب",

    "طرطوس",
    "بانياس",
    "صافيتا",
    "الدريكيش",
    "الشيخ بدر",
    "القدموس",

    "إدلب",
    "أريحا",
    "اريحا",
    "سراقب",
    "بنش",
    "سرمين",
    "الدانا",
    "كفرنبل",

    "الحسكة",
    "القامشلي",
    "المالكية",
    "ديريك",
    "راس العين",
    "عامودا",
    "الدرباسية",
    "الشدادي",
    "تل تمر",
    "القحطانية",
    "اليعربية",

    "الرقة",
    "الطبقة",
    "تل ابيض",
    "معدان",
    "المنصورة",

    "دير الزور",
    "الميادين",
    "البوكمال",
    "العشارة",
    "القورية",
    "موحسن",

    "درعا",
    "نوى",
    "الصنمين",
    "طفس",
    "جاسم",
    "ازرع",
    "إزرع",
    "داعل",
    "الحراك",

    "السويداء",
    "شهبا",
    "صلخد",
    "القريا",

    "القنيطرة",
    "خان ارنبة",
    "البعث",
]


# =========================================================
# TEXT HELPERS
# =========================================================

def norm(value):

    text = str(value or "").strip().lower()

    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ة": "ه",
        "ى": "ي",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(
        r"[^\w\s\u0600-\u06FF]",
        " ",
        text,
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def contains_any(text, phrases):

    n = norm(text)

    return any(
        norm(phrase) in n
        for phrase in phrases
    )


# =========================================================
# DATABASE
# =========================================================

def using_postgres():

    return bool(DATABASE_URL)


def db_connect():

    if using_postgres():
        if psycopg is None:
            raise RuntimeError(
                "DATABASE_URL is configured but psycopg is not installed"
            )
        return psycopg.connect(DATABASE_URL)

    return sqlite3.connect(
        DB_PATH,
        timeout=20,
    )


def db_sql(statement):

    if using_postgres():
        return statement.replace("?", "%s")

    return statement


def init_db():

    conn = db_connect()

    order_id_type = (
        "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
        if using_postgres()
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )

    event_id_type = (
        "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
        if using_postgres()
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS orders(
            id {order_id_type},
            customer_name TEXT,
            customer_phone TEXT,
            product_name TEXT,
            quantity INTEGER,
            price REAL,
            currency TEXT,
            country TEXT,
            city TEXT,
            status TEXT DEFAULT 'new',
            customer_message TEXT,
            created_at TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_updates(
            update_id INTEGER PRIMARY KEY,
            processed_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_messages(
            message_id TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions(
            chat_id TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS order_status_events(
            id {event_id_type},
            order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            old_status TEXT,
            new_status TEXT NOT NULL,
            source TEXT NOT NULL,
            changed_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_orders_status
        ON orders(status)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_order_status_events_order_id
        ON order_status_events(order_id, id)
        """
    )

    conn.commit()
    conn.close()


def update_was_processed(update_id):

    if update_id is None:
        return False

    conn = db_connect()

    row = conn.execute(
        db_sql("""
        SELECT 1
        FROM processed_updates
        WHERE update_id = ?
        """),
        (update_id,),
    ).fetchone()

    conn.close()

    return row is not None


def remember_update(update_id):

    if update_id is None:
        return

    conn = db_connect()

    conn.execute(
        db_sql("""
        INSERT INTO processed_updates(
            update_id,
            processed_at
        )
        VALUES(?,?)
        ON CONFLICT(update_id) DO NOTHING
        """),
        (
            update_id,
            datetime.now().isoformat(
                timespec="seconds"
            ),
        ),
    )

    conn.execute(
        db_sql("""
        DELETE FROM processed_updates
        WHERE update_id < ?
        """),
        (update_id - 10000,),
    )

    conn.commit()
    conn.close()


def claim_update(update_id):

    if update_id is None:
        return True

    conn = db_connect()
    cursor = conn.execute(
        db_sql("""
        INSERT INTO processed_updates(update_id, processed_at)
        VALUES(?,?)
        ON CONFLICT(update_id) DO NOTHING
        """),
        (update_id, datetime.now().isoformat(timespec="seconds")),
    )
    claimed = cursor.rowcount == 1

    if claimed:
        conn.execute(
            db_sql("DELETE FROM processed_updates WHERE update_id < ?"),
            (update_id - 10000,),
        )

    conn.commit()
    conn.close()
    return claimed


def release_update(update_id):

    if update_id is None:
        return

    conn = db_connect()
    conn.execute(
        db_sql("DELETE FROM processed_updates WHERE update_id = ?"),
        (update_id,),
    )
    conn.commit()
    conn.close()


def message_was_processed(message_id):

    if not message_id:
        return False

    conn = db_connect()
    row = conn.execute(
        db_sql("""
        SELECT 1
        FROM processed_messages
        WHERE message_id = ?
        """),
        (str(message_id),),
    ).fetchone()
    conn.close()

    return row is not None


def remember_message(message_id):

    if not message_id:
        return

    conn = db_connect()
    conn.execute(
        db_sql("""
        INSERT INTO processed_messages(message_id, processed_at)
        VALUES(?,?)
        ON CONFLICT(message_id) DO NOTHING
        """),
        (
            str(message_id),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


# =========================================================
# SESSION
# =========================================================

def default_session_state():

    return {
        "name": None,
        "phone": None,
        "city": None,
        "product": None,
        "qty": 1,
        "buying": False,
        "done": False,
        "order_id": None,
        "awaiting_confirmation": False,
        "customer_message": None,
    }


def load_session(chat_id):

    conn = db_connect()

    row = conn.execute(
        db_sql("""
        SELECT state_json
        FROM sessions
        WHERE chat_id = ?
        """),
        (str(chat_id),),
    ).fetchone()

    conn.close()

    if not row:
        return None

    try:
        saved = json.loads(row[0])
    except (TypeError, ValueError):
        return None

    if not isinstance(saved, dict):
        return None

    state = default_session_state()

    for key in state:
        if key in saved:
            state[key] = saved[key]

    return state


def save_session(chat_id, state):

    conn = db_connect()

    conn.execute(
        db_sql("""
        INSERT INTO sessions(
            chat_id,
            state_json,
            updated_at
        )
        VALUES(?,?,?)
        ON CONFLICT(chat_id) DO UPDATE SET
            state_json = excluded.state_json,
            updated_at = excluded.updated_at
        """),
        (
            str(chat_id),
            json.dumps(
                state,
                ensure_ascii=False,
            ),
            datetime.now().isoformat(
                timespec="seconds"
            ),
        ),
    )

    conn.commit()
    conn.close()


def delete_session(chat_id):

    conn = db_connect()

    conn.execute(
        db_sql("""
        DELETE FROM sessions
        WHERE chat_id = ?
        """),
        (str(chat_id),),
    )

    conn.commit()
    conn.close()


def session(chat_id):

    key = str(chat_id)

    if key not in SESSIONS:
        SESSIONS[key] = (
            load_session(key)
            or default_session_state()
        )

    return SESSIONS[key]


def reset(chat_id):

    SESSIONS.pop(
        str(chat_id),
        None,
    )

    delete_session(chat_id)


# =========================================================
# DETECT PHONE
# =========================================================

def detect_phone(text):

    match = re.search(
        r"(?<!\d)(\+?\d[\d\s\-]{6,16}\d)(?!\d)",
        str(text),
    )

    if not match:
        return None

    phone = re.sub(
        r"[^\d+]",
        "",
        match.group(1),
    )

    digits = re.sub(
        r"\D",
        "",
        phone,
    )

    if len(digits) >= 8:
        return phone

    return None


# =========================================================
# DETECT CITY
# =========================================================

def detect_city(text):

    n = norm(text)

    cities = sorted(
        CITIES,
        key=lambda x: len(norm(x)),
        reverse=True,
    )

    for city in cities:

        if norm(city) in n:
            return city

    return None


# =========================================================
# DETECT PRODUCTS
# =========================================================

def detect_products(text):

    n = norm(text)

    found = []

    for name, data in PRODUCTS.items():

        aliases = set(
            data.get("aliases", [])
        )

        aliases.add(name)

        for alias in aliases:

            alias_n = norm(alias)

            if alias_n and alias_n in n:

                found.append(
                    (name, data)
                )

                break

    return found


def detect_product(text):

    found = detect_products(text)

    if len(found) == 1:
        return found[0]

    return None


# =========================================================
# QUANTITY
# =========================================================

def detect_quantity(text):

    n = norm(text)

    match = re.search(
        r"\b(\d+)\b",
        n,
    )

    if match:

        qty = int(
            match.group(1)
        )

        if qty > 0:
            return qty

    mapping = {
        "واحد": 1,
        "واحده": 1,

        "جهازين": 2,
        "قطعتين": 2,
        "منتجين": 2,
        "اثنين": 2,
        "اتنين": 2,

        "ثلاث": 3,
        "ثلاثه": 3,

        "اربع": 4,
        "اربعه": 4,

        "خمس": 5,
        "خمسه": 5,
    }

    for word, qty in mapping.items():

        if norm(word) in n:
            return qty

    return 1


# =========================================================
# NAME
# =========================================================

def explicit_name(text):

    match = re.search(
        r"(?:اسمي|الاسم)\s*[:\-]?\s*"
        r"([\u0600-\u06FF]{2,20}"
        r"(?:\s+[\u0600-\u06FF]{2,20})?)",
        str(text),
    )

    if match:
        return match.group(1).strip()

    return None


# =========================================================
# INTENTS
# =========================================================

def is_buy_intent(text):

    n = norm(text)

    purchase_prefix = (
        r"(?:بدي|بدنا|اريد|حابب|حابه|حاب)"
    )
    quantity = (
        r"(?:\d+|واحد|واحده|اثنين|اتنين|ثلاث|ثلاثه|اربع|اربعه|خمس|خمسه)"
    )

    for name, data in PRODUCTS.items():

        aliases = {
            norm(name),
            *(norm(alias) for alias in data.get("aliases", [])),
        }

        for alias in aliases:

            if alias and re.search(
                rf"(?:^|\s){purchase_prefix}\s+(?:{quantity}\s+)?"
                rf"{re.escape(alias)}(?:\s|$)",
                n,
            ):
                return True

    return contains_any(
        text,
        [
            "بدي اشتري",
            "اريد شراء",
            "أريد شراء",
            "بدي اخد",
            "بدي آخذ",
            "حابب اشتري",
            "حابه اشتري",
            "حاب اشتري",
            "بدي اطلب",
            "اريد الطلب",
            "أريد الطلب",
            "يلزمني",
            "بدي جهاز",
            "بدي الجهاز",
            "بدي منتج",
            "بدي المنتج",
            "اريد الجهاز",
            "أريد الجهاز",
            "اريد المنتج",
            "أريد المنتج",
            "تسجيل طلب",
            "سجل طلب",
            "سجلي طلب",
            "اطلب",
            "اشتري",
        ],
    )


def is_products_question(text):

    return contains_any(
        text,
        [
            "شو في عندكم",
            "شو عندكم",
            "شو المنتجات",
            "ما هي المنتجات",
            "ماهي المنتجات",
            "عندكم منتجات",
            "المنتجات المتوفره",
            "المنتجات المتاحة",
            "اعرض المنتجات",
            "عرض المنتجات",
            "المنتجات",
            "شو بتبيعوا",
            "شو تبيعوا",
        ],
    )


def is_product_count_question(text):

    return contains_any(
        text,
        [
            "كم منتج",
            "عدد المنتجات",
            "قديش منتج",
            "كم نوع",
            "قديش نوع",
        ],
    )


def is_price_question(text):

    return contains_any(
        text,
        [
            "سعر",
            "بكم",
            "قديش",
            "كم حق",
            "شو حق",
            "حقه",
            "ثمن",
        ],
    )


def is_delivery_question(text):

    return contains_any(
        text,
        [
            "توصيل",
            "شحن",
            "يوصل",
            "التوصيل",
            "مدة التوصيل",
        ],
    )


def is_color_question(text):

    return contains_any(
        text,
        [
            "كم لون",
            "ما هو لون",
            "ماهو لون",
            "ما هي الالوان",
            "ماهي الالوان",
            "ما هي الألوان",
            "ماهي الألوان",
            "الألوان المتوفرة",
            "الالوان المتوفرة",
            "شو اللون",
            "شو الألوان",
            "شو الالوان",
            "لون الجهاز",
        ],
    )


def is_payment_question(text):

    return contains_any(
        text,
        [
            "طرق الدفع",
            "طريقة الدفع",
            "ما هي طرق الدفع",
            "ماهي طرق الدفع",
            "كيف ادفع",
            "كيف أدفع",
            "كيف فيني ادفع",
            "كيف فيني أدفع",
            "شلون ادفع",
            "شلون أدفع",
            "متى لازم ادفع",
            "متى لازم أدفع",
            "امتى ادفع",
            "إمتى أدفع",
            "وقت الدفع",
            "الدفع عند الاستلام",
        ],
    )


def product_for_answer(state, detected_product=None):

    if detected_product:
        return detected_product

    product_name = state.get("product")

    if product_name in PRODUCTS:
        return product_name, PRODUCTS[product_name]

    if len(PRODUCTS) == 1:
        return next(iter(PRODUCTS.items()))

    return None


def product_information_answers(text, state, detected_product=None):

    selected = product_for_answer(state, detected_product)
    answers = []

    if is_color_question(text):
        if selected:
            product_name, data = selected
            colors = data.get("colors", [])
            if colors:
                answers.append(
                    f"ألوان {product_name} المتوفرة: "
                    + "، ".join(colors)
                    + " ✅"
                )
            else:
                answers.append(f"ألوان {product_name} غير محددة حالياً.")
        else:
            answers.append(
                "لأي منتج تريد معرفة الألوان؟ "
                + "، ".join(PRODUCTS)
            )

    if is_payment_question(text):
        if selected:
            product_name, data = selected
            methods = data.get("payment_methods", [])
            if methods:
                answers.append(
                    f"طرق الدفع لـ{product_name}: "
                    + "، ".join(methods)
                    + "."
                )
            else:
                answers.append("طرق الدفع المتاحة غير محددة حالياً.")
        else:
            methods = []
            for data in PRODUCTS.values():
                for method in data.get("payment_methods", []):
                    if method not in methods:
                        methods.append(method)
            answers.append(
                "طرق الدفع المتاحة: "
                + ("، ".join(methods) if methods else "غير محددة حالياً")
                + "."
            )

    return answers


# =========================================================
# PRODUCT LIST
# =========================================================

def product_list_text():

    lines = []

    for name, data in PRODUCTS.items():

        if data.get("available", True):
            status = "متوفر"
        else:
            status = "غير متوفر"

        price = data["price"]

        if float(price).is_integer():
            price = int(price)

        lines.append(
            f"• {name}: "
            f"{price}{data['currency']} "
            f"— {status}"
        )

    return (
        "المنتجات المتوفرة حالياً:\n"
        + "\n".join(lines)
    )


# =========================================================
# CREATE ORDER
# =========================================================

def create_order(state, original_text):

    product = PRODUCTS[
        state["product"]
    ]

    conn = db_connect()

    insert_sql = """
        INSERT INTO orders(
            customer_name,
            customer_phone,
            product_name,
            quantity,
            price,
            currency,
            country,
            city,
            status,
            customer_message,
            created_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
    """

    if using_postgres():
        insert_sql += " RETURNING id"

    cursor = conn.execute(
        db_sql(insert_sql),
        (
            state["name"],
            state["phone"],
            state["product"],
            state["qty"],
            product["price"],
            product["currency"],
            "سوريا",
            state["city"],
            "new",
            original_text,
            datetime.now().isoformat(
                timespec="seconds"
            ),
        ),
    )

    order_id = (
        cursor.fetchone()[0]
        if using_postgres()
        else cursor.lastrowid
    )

    conn.execute(
        db_sql("""
        INSERT INTO order_status_events(
            order_id,
            old_status,
            new_status,
            source,
            changed_at
        )
        VALUES(?,?,?,?,?)
        """),
        (
            order_id,
            None,
            "new",
            "telegram_or_messenger",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )

    conn.commit()
    conn.close()

    return order_id


def rows_as_dicts(cursor):

    columns = [
        getattr(column, "name", column[0])
        for column in cursor.description
    ]

    return [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def escape_like(value):

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_orders(status="", search="", limit=50, offset=0):

    clauses = []
    params = []

    if status:
        clauses.append("status = ?")
        params.append(status)

    if search:
        pattern = f"%{escape_like(search)}%"
        clauses.append(
            "(CAST(id AS TEXT) = ? OR customer_name LIKE ? ESCAPE '\\' "
            "OR customer_phone LIKE ? ESCAPE '\\' "
            "OR product_name LIKE ? ESCAPE '\\' "
            "OR city LIKE ? ESCAPE '\\')"
        )
        params.extend([search, pattern, pattern, pattern, pattern])

    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
    conn = db_connect()

    count_cursor = conn.execute(
        db_sql("SELECT COUNT(*) FROM orders" + where_sql),
        tuple(params),
    )
    total = count_cursor.fetchone()[0]

    cursor = conn.execute(
        db_sql(
            "SELECT id, customer_name, customer_phone, product_name, quantity, "
            "price AS unit_price, (price * quantity) AS total_price, currency, "
            "country, city, status, customer_message, created_at "
            "FROM orders" + where_sql + " ORDER BY id DESC LIMIT ? OFFSET ?"
        ),
        tuple([*params, limit, offset]),
    )
    orders = rows_as_dicts(cursor)
    conn.close()

    return orders, total


def order_metrics():

    conn = db_connect()
    total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    active_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status NOT IN ('delivered','cancelled')"
    ).fetchone()[0]
    delivered_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status = 'delivered'"
    ).fetchone()[0]
    revenue_cursor = conn.execute(
        """
        SELECT currency, COALESCE(SUM(price * quantity), 0) AS total
        FROM orders
        WHERE status != 'cancelled'
        GROUP BY currency
        ORDER BY currency
        """
    )
    revenue_by_currency = {
        str(row[0] or "غير محددة"): float(row[1])
        for row in revenue_cursor.fetchall()
    }
    status_cursor = conn.execute(
        "SELECT status, COUNT(*) FROM orders GROUP BY status"
    )
    orders_by_status = {
        str(row[0]): row[1]
        for row in status_cursor.fetchall()
    }
    conn.close()

    return {
        "total_orders": total_orders,
        "active_orders": active_orders,
        "delivered_orders": delivered_orders,
        "recorded_revenue_by_currency": revenue_by_currency,
        "orders_by_status": orders_by_status,
    }


def set_order_status(order_id, new_status, source):

    if new_status not in ORDER_STATUSES:
        raise ValueError("invalid order status")

    conn = db_connect()
    row = conn.execute(
        db_sql("SELECT status FROM orders WHERE id = ?"),
        (order_id,),
    ).fetchone()

    if not row:
        conn.close()
        return None

    old_status = row[0]
    changed_at = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        db_sql("UPDATE orders SET status = ? WHERE id = ?"),
        (new_status, order_id),
    )
    conn.execute(
        db_sql("""
        INSERT INTO order_status_events(
            order_id, old_status, new_status, source, changed_at
        )
        VALUES(?,?,?,?,?)
        """),
        (order_id, old_status, new_status, source, changed_at),
    )
    conn.commit()
    conn.close()

    return {
        "old_status": old_status,
        "new_status": new_status,
        "changed_at": changed_at,
    }


def order_status_history_rows(order_id):

    conn = db_connect()
    exists = conn.execute(
        db_sql("SELECT 1 FROM orders WHERE id = ?"),
        (order_id,),
    ).fetchone()

    if not exists:
        conn.close()
        return None

    cursor = conn.execute(
        db_sql("""
        SELECT id, old_status, new_status, source, changed_at
        FROM order_status_events
        WHERE order_id = ?
        ORDER BY id ASC
        """),
        (order_id,),
    )
    events = rows_as_dicts(cursor)
    conn.close()
    return events


def parse_order_limit(value, default=50, maximum=200):

    try:
        parsed = int(default if value is None else value)
    except (TypeError, ValueError):
        return None

    return min(max(parsed, 1), maximum)


def parse_order_offset(value, default=0, maximum=1_000_000):

    try:
        parsed = int(default if value is None else value)
    except (TypeError, ValueError):
        return None

    return parsed if 0 <= parsed <= maximum else None


# =========================================================
# ORDER REVIEW / CONFIRMATION
# =========================================================

CONFIRM_WORDS = {
    "تاكيد",
    "تاكيد الطلب",
    "اكد",
    "اكد الطلب",
    "نعم",
    "اي",
    "ايوه",
    "تمام",
}

EDIT_WORDS = {
    "تعديل",
    "عدل",
    "بدي عدل",
}


def money_text(value):

    if float(value).is_integer():
        return str(int(value))

    return f"{value:.2f}".rstrip("0").rstrip(".")


def order_review_text(state):

    data = PRODUCTS[
        state["product"]
    ]

    total = (
        data["price"]
        * state["qty"]
    )

    return (
        "🧾 راجع طلبك قبل التسجيل:\n\n"
        f"الاسم: {state['name']}\n"
        f"المنتج: {state['product']}\n"
        f"الكمية: {state['qty']}\n"
        f"الإجمالي: "
        f"{money_text(total)}"
        f"{data['currency']}\n"
        f"الهاتف: {state['phone']}\n"
        f"المدينة: {state['city']}\n\n"
        "إذا المعلومات صحيحة اكتب: تأكيد\n"
        "للتعديل اكتب المعلومة الجديدة مباشرة، "
        "مثلاً: الكمية 3 أو المدينة حلب\n"
        "وللإلغاء اكتب: إلغاء الطلب"
    )


def complete_order(state, confirmation_text):

    if state["done"]:

        return (
            "طلبك مسجل مسبقاً ✅ "
            f"رقم الطلب: "
            f"{state['order_id']}"
        )

    order_id = create_order(
        state,
        state.get("customer_message")
        or confirmation_text,
    )

    state["done"] = True
    state["order_id"] = order_id
    state["awaiting_confirmation"] = False
    state["buying"] = False

    data = PRODUCTS[
        state["product"]
    ]

    total = (
        data["price"]
        * state["qty"]
    )

    return (
        "✅ تم تسجيل طلبك بنجاح\n\n"
        f"رقم الطلب: {order_id}\n"
        f"الاسم: {state['name']}\n"
        f"المنتج: {state['product']}\n"
        f"الكمية: {state['qty']}\n"
        f"الإجمالي: "
        f"{money_text(total)}"
        f"{data['currency']}\n"
        f"المدينة: {state['city']}\n"
        f"التوصيل: "
        f"{DELIVERY.get(state['city'], '2-4 أيام')}"
    )


# =========================================================
# CAPTURE NAME DURING ORDER
# =========================================================

def maybe_capture_name(
    state,
    text,
):

    if state["name"]:
        return

    explicit = explicit_name(text)

    if explicit:

        state["name"] = explicit

        return

    if (
        state["buying"]
        and not detect_phone(text)
        and not detect_city(text)
        and not detect_product(text)
    ):

        words = norm(text).split()

        blocked = {
            "مرحبا",
            "هلا",
            "اهلا",
            "السلام",
            "عليكم",
            "بدي",
            "اريد",
            "طلب",
            "منتج",
            "جهاز",
            "سعر",
            "توصيل",
            "شحن",
            "نعم",
            "اي",
            "ايوه",
        }

        if (
            1 <= len(words) <= 3
            and not any(
                word in blocked
                for word in words
            )
        ):

            if all(
                re.fullmatch(
                    r"[\u0600-\u06FF]+",
                    word,
                )
                for word in words
            ):

                state["name"] = (
                    text.strip()
                )


# =========================================================
# MAIN AI / SALES LOGIC
# =========================================================

def _handle_message(
    chat_id,
    text,
):

    state = session(chat_id)

    text = str(
        text or ""
    ).strip()

    if not text:

        return (
            "اكتبلي رسالتك حتى أساعدك 👌"
        )

    # -----------------------------------------
    # Capture useful information
    # -----------------------------------------

    phone = detect_phone(text)

    city = detect_city(text)

    product = detect_product(text)

    name = explicit_name(text)

    if phone:
        state["phone"] = phone

    if city:
        state["city"] = city

    if product:
        state["product"] = product[0]

    if name:
        state["name"] = name

    n = norm(text)

    if (
        state["buying"]
        and not phone
        and contains_any(
            text,
            [
                "الكمية",
                "الكميه",
                "العدد",
            ],
        )
    ):

        state["qty"] = detect_quantity(
            text
        )

    # -----------------------------------------
    # CANCEL / RESET
    # -----------------------------------------

    if (
        n in {"الغاء", "الغي"}
        or contains_any(
            text,
            [
                "الغاء الطلب",
                "إلغاء الطلب",
                "الغي الطلب",
                "ابدأ من جديد",
                "بداية جديدة",
            ],
        )
    ):

        reset(chat_id)

        return (
            "✅ تمام، لغيت المحادثة الحالية. "
            "فيك تبدأ من جديد."
        )

    # -----------------------------------------
    # CONFIRM / EDIT ORDER
    # -----------------------------------------

    if (
        state["done"]
        and n in CONFIRM_WORDS
    ):

        return (
            "طلبك مسجل مسبقاً ✅ "
            f"رقم الطلب: "
            f"{state['order_id']}"
        )

    information_answers = product_information_answers(
        text,
        state,
        product,
    )

    if state["awaiting_confirmation"]:

        if n in CONFIRM_WORDS:

            return complete_order(
                state,
                text,
            )

        if n in EDIT_WORDS:

            return (
                "تمام 👍 ابعت المعلومة الجديدة "
                "مباشرة، مثلاً:\n"
                "• الاسم: أحمد\n"
                "• الهاتف: 09xxxxxxxx\n"
                "• المدينة: حلب\n"
                "• الكمية: 3"
            )

        if information_answers:

            return (
                "\n".join(information_answers)
                + "\n\nطلبك ما زال جاهزاً للتأكيد؛ "
                "اكتب: تأكيد لإكماله، أو تعديل لتغييره."
            )

        if (
            phone
            or city
            or product
            or name
            or contains_any(
                text,
                [
                    "الكمية",
                    "الكميه",
                    "العدد",
                ],
            )
        ):

            return order_review_text(
                state
            )

        return (
            "طلبك جاهز للتأكيد 👍\n\n"
            + order_review_text(state)
        )

    if information_answers:

        return "\n".join(information_answers)

    # -----------------------------------------
    # GREETING
    # -----------------------------------------

    if contains_any(
        text,
        [
            "مرحبا",
            "اهلا",
            "أهلا",
            "هلا",
            "السلام عليكم",
            "هاي",
            "hello",
            "hi",
        ],
    ):

        if not state["buying"]:

            return (
                "أهلاً وسهلاً 👋\n"
                "فيني أعرض المنتجات والأسعار، "
                "أخبرك عن التوصيل، "
                "أو أسجّل لك طلب مباشرة."
            )

    # -----------------------------------------
    # HOW MANY PRODUCTS?
    # -----------------------------------------

    if is_product_count_question(text):

        available = [
            p
            for p in PRODUCTS.values()
            if p.get(
                "available",
                True,
            )
        ]

        return (
            f"عندنا حالياً "
            f"{len(available)} "
            "منتج/نوع متوفر.\n\n"
            + product_list_text()
        )

    # -----------------------------------------
    # SHOW PRODUCTS
    # -----------------------------------------

    if is_products_question(text):

        return (
            product_list_text()
            + "\n\n"
            + "إذا بدك واحد منهم، "
            + "قلي مثلاً: بدي أطلب الجهاز."
        )

    # -----------------------------------------
    # PRICE
    # -----------------------------------------

    if (
        is_price_question(text)
        and not is_buy_intent(text)
    ):

        if product:

            data = product[1]

            price = data["price"]

            if float(price).is_integer():
                price = int(price)

            return (
                f"سعر {product[0]} "
                f"هو {price}"
                f"{data['currency']} ✅"
            )

        if len(PRODUCTS) == 1:

            only_name, data = next(
                iter(
                    PRODUCTS.items()
                )
            )

            price = data["price"]

            if float(price).is_integer():
                price = int(price)

            return (
                f"سعر {only_name} "
                f"هو {price}"
                f"{data['currency']} ✅"
            )

        return (
            "أكيد 👍 لأي منتج بدك السعر؟\n"
            + "\n".join(
                f"• {name}"
                for name in PRODUCTS
            )
        )

    # -----------------------------------------
    # DELIVERY
    # -----------------------------------------

    if (
        is_delivery_question(text)
        and not is_buy_intent(text)
    ):

        if city:

            return (
                f"التوصيل إلى {city}: "
                f"{DELIVERY.get(city, '2-4 أيام')} 🚚"
            )

        return (
            "أكيد 🚚 لأي مدينة بدك "
            "تعرف مدة التوصيل؟"
        )

    # -----------------------------------------
    # GENERIC PRODUCT WORD
    # -----------------------------------------

    if (
        n in {
            "المنتج",
            "منتج",
            "الجهاز",
            "جهاز",
        }
        and not state["buying"]
    ):

        if product:

            data = product[1]

            price = data["price"]

            if float(price).is_integer():
                price = int(price)

            return (
                f"{product[0]} متوفر ✅ "
                f"وسعره {price}"
                f"{data['currency']}.\n"
                "إذا بدك تطلبه قلي: "
                "بدي أطلبه."
            )

        return product_list_text()

    # -----------------------------------------
    # START ORDER
    # -----------------------------------------

    if is_buy_intent(text):

        state["buying"] = True

        state["done"] = False

        state["awaiting_confirmation"] = False

        state["customer_message"] = text

        state["qty"] = (
            detect_quantity(text)
        )

    # -----------------------------------------
    # ORDER FLOW
    # -----------------------------------------

    if state["buying"]:

        maybe_capture_name(
            state,
            text,
        )

        # Product missing
        if not state["product"]:

            if len(PRODUCTS) == 1:

                state["product"] = next(
                    iter(PRODUCTS)
                )

            else:

                return (
                    "تمام 👍 شو المنتج "
                    "اللي بدك تطلبه؟\n"
                    + "\n".join(
                        f"• {name}"
                        for name in PRODUCTS
                    )
                )

        # Name missing
        if not state["name"]:

            return (
                "تمام 👍 شو اسمك "
                "حتى أسجل الطلب؟"
            )

        # Phone missing
        if not state["phone"]:

            return (
                f"تمام {state['name']} 👍 "
                "ابعتلي رقم الهاتف."
            )

        # City missing
        if not state["city"]:

            return (
                "ممتاز 👍 بقي بس "
                "أعرف المدينة للتوصيل."
            )

        # Review before writing the order
        state["awaiting_confirmation"] = True

        return order_review_text(
            state
        )

    return (
        "فهمت عليك جزئياً 👌\n"
        "جرب اسألني مثلاً:\n"
        "• شو المنتجات؟\n"
        "• كم سعر الجهاز؟\n"
        "• التوصيل للحسكة؟\n"
        "• بدي أسجل طلب."
    )


def handle_message(
    chat_id,
    text,
):

    try:
        return _handle_message(
            chat_id,
            text,
        )
    finally:
        state = SESSIONS.get(
            str(chat_id)
        )

        if state is not None:
            save_session(
                chat_id,
                state,
            )


def telegram_api(method, **data):

    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    response = requests.post(
        f"{API}/{method}",
        json=data,
        timeout=20,
    )

    response.raise_for_status()
    return response.json()


def log_external_failure(context, exc):

    print(f"{context}: {type(exc).__name__}")


def messenger_signature_is_valid(raw_body, signature):

    if not META_APP_SECRET or not signature:
        return False

    expected = "sha256=" + hmac.new(
        META_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def messenger_send_text(recipient_id, text):

    if not META_PAGE_ACCESS_TOKEN:
        raise RuntimeError("META_PAGE_ACCESS_TOKEN is missing")

    response = requests.post(
        f"https://graph.facebook.com/{META_GRAPH_VERSION}/me/messages",
        params={"access_token": META_PAGE_ACCESS_TOKEN},
        json={
            "messaging_type": "RESPONSE",
            "recipient": {"id": str(recipient_id)},
            "message": {"text": text},
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def resolved_webhook_url():

    if not WEBHOOK_URL:
        return ""

    url = WEBHOOK_URL.rstrip("/")

    if not url.endswith("/telegram"):
        url += "/telegram"

    return url


def register_webhook():

    url = resolved_webhook_url()

    if not BOT_TOKEN:
        return {
            "ok": False,
            "error": "TELEGRAM_BOT_TOKEN or WEBHOOK_URL missing",
        }

    if not url:
        return {
            "ok": False,
            "error": "TELEGRAM_BOT_TOKEN or WEBHOOK_URL missing",
        }

    try:
        response = requests.post(
            f"{API}/setWebhook",
            json={
                "url": url,
                "drop_pending_updates": False,
                **(
                    {
                        "secret_token":
                        WEBHOOK_SECRET,
                    }
                    if WEBHOOK_SECRET
                    else {}
                ),
            },
            timeout=20,
        )

        response.raise_for_status()

        return response.json()

    except Exception as exc:
        log_external_failure("Telegram webhook setup failed", exc)
        raise


def database_is_available():

    try:
        conn = db_connect()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except Exception:
        return False


def deployment_configuration_errors():

    errors = list(CONFIGURATION_ERRORS)

    required = {
        "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
        "WEBHOOK_URL": WEBHOOK_URL,
        "TELEGRAM_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "ADMIN_API_KEY": ADMIN_API_KEY,
        "DASHBOARD_SESSION_SECRET": DASHBOARD_SESSION_SECRET,
    }

    for name, value in required.items():
        if not value:
            errors.append(f"{name} is not configured")

    if WEBHOOK_URL and not WEBHOOK_URL.lower().startswith("https://"):
        errors.append("WEBHOOK_URL must use HTTPS")

    return errors


def admin_required(fn):

    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not ADMIN_API_KEY:
            return jsonify({"ok": False, "error": "admin API is not configured"}), 503

        provided = request.headers.get("X-Admin-Key", "")
        if not provided or not hmac.compare_digest(provided, ADMIN_API_KEY):
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        return fn(*args, **kwargs)

    return wrapped


@app.errorhandler(413)
def request_too_large(_error):

    return jsonify(
        {
            "ok": False,
            "error": "request body too large",
            "max_bytes": MAX_REQUEST_BYTES,
        }
    ), 413


@app.get("/")
def health():

    return jsonify(
        {
            "status": "ok",
            "service": "customer-agent-v62",
            "version": APP_VERSION,
            "commit": GIT_COMMIT[:7],
            "session_store": (
                "postgresql"
                if using_postgres()
                else "sqlite"
            ),
        }
    )


@app.get("/health")
def service_health():

    database_ok = database_is_available()
    configuration_ok = not CONFIGURATION_ERRORS

    return jsonify(
        {
            "ok": database_ok and configuration_ok,
            "service": "customer-agent-v62",
            "version": APP_VERSION,
            "database": "ok" if database_ok else "error",
            "configuration": "ok" if configuration_ok else "error",
            "configuration_errors": list(CONFIGURATION_ERRORS),
        }
    ), (200 if database_ok and configuration_ok else 503)


@app.get("/ready")
def service_readiness():

    database_ok = database_is_available()
    errors = deployment_configuration_errors()
    ready = database_ok and not errors

    return jsonify(
        {
            "ok": ready,
            "service": "customer-agent-v62",
            "version": APP_VERSION,
            "database": "ok" if database_ok else "error",
            "configuration": "ok" if not errors else "error",
            "configuration_errors": errors,
        }
    ), (200 if ready else 503)


@app.post("/admin/setup-webhook")
@admin_required
def admin_setup_webhook():

    try:
        return jsonify(register_webhook())
    except Exception:
        return jsonify({"ok": False, "error": "telegram request failed"}), 502


@app.get("/admin/orders")
@admin_required
def admin_orders():

    status = request.args.get("status", "").strip().lower()
    search = request.args.get("q", "").strip()[:100]
    limit = parse_order_limit(request.args.get("limit"))
    offset = parse_order_offset(request.args.get("offset"))

    if status and status not in ORDER_STATUSES:
        return jsonify({"ok": False, "error": "invalid status"}), 400
    if limit is None:
        return jsonify({"ok": False, "error": "limit must be an integer"}), 400
    if offset is None:
        return jsonify({"ok": False, "error": "invalid offset"}), 400

    orders, total = list_orders(status, search, limit, offset)
    return jsonify(
        {
            "ok": True,
            "orders": orders,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "has_more": offset + len(orders) < total,
            },
        }
    )


@app.get("/admin/stats")
@admin_required
def admin_stats():

    return jsonify({"ok": True, **order_metrics()})


@app.patch("/admin/orders/<int:order_id>/status")
@admin_required
def admin_change_order_status(order_id):

    body = request.get_json(silent=True) or {}
    status = str(body.get("status", "")).strip().lower()

    if status not in ORDER_STATUSES:
        return jsonify({"ok": False, "error": "invalid status"}), 400

    change = set_order_status(order_id, status, "admin_api")
    if change is None:
        return jsonify({"ok": False, "error": "order not found"}), 404

    return jsonify({"ok": True, "order_id": order_id, **change})


@app.get("/admin/orders/<int:order_id>/history")
@admin_required
def admin_order_history(order_id):

    events = order_status_history_rows(order_id)
    if events is None:
        return jsonify({"ok": False, "error": "order not found"}), 404

    return jsonify({"ok": True, "order_id": order_id, "events": events})


@app.get("/webhook-info")
def webhook_info():

    if not BOT_TOKEN:
        return jsonify(
            {
                "ok": False,
                "error": "TELEGRAM_BOT_TOKEN missing",
            }
        ), 500

    try:
        response = requests.get(
            f"{API}/getWebhookInfo",
            timeout=20,
        )

        data = response.json()

        result = (
            data.get("result", {})
            if isinstance(data, dict)
            else {}
        )

        return jsonify(
            {
                "ok": bool(
                    data.get("ok")
                ),
                "url": result.get(
                    "url",
                    "",
                ),
                "pending_update_count":
                result.get(
                    "pending_update_count",
                    0,
                ),
                "last_error_message":
                result.get(
                    "last_error_message",
                    "",
                ),
            }
        )

    except Exception as exc:
        log_external_failure("Telegram webhook info failed", exc)
        return jsonify(
            {
                "ok": False,
                "error": "telegram request failed",
            }
        ), 500


@app.post("/telegram")
def telegram_webhook():

    provided_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token",
        "",
    )

    if (
        WEBHOOK_SECRET
        and not hmac.compare_digest(provided_secret, WEBHOOK_SECRET)
    ):

        return jsonify(
            {
                "ok": False,
                "error": "unauthorized",
            }
        ), 403

    update = (
        request.get_json(
            silent=True
        )
        or {}
    )

    update_id = update.get(
        "update_id"
    )

    if not claim_update(update_id):

        return jsonify(
            {
                "ok": True,
                "duplicate": True,
            }
        )

    message = update.get(
        "message",
        {},
    )

    text = message.get("text")

    chat_id = (
        message.get(
            "chat",
            {},
        ).get("id")
    )

    if (
        not text
        or chat_id is None
    ):
        return jsonify(
            {
                "ok": True,
            }
        )

    try:

        if text == "/start":

            answer = (
                "أهلاً وسهلاً 👋\n"
                "أنا مساعد المتجر.\n"
                "اسألني عن المنتجات "
                "والأسعار والتوصيل، "
                "أو قلي بدي أسجل طلب."
            )

        elif text == "/reset":

            reset(chat_id)

            answer = (
                "✅ تم بدء محادثة جديدة."
            )

        elif text == "/products":

            answer = (
                product_list_text()
            )

        else:

            answer = handle_message(
                chat_id,
                text,
            )

        telegram_api(
            "sendMessage",
            chat_id=chat_id,
            text=answer,
        )

    except Exception as exc:
        release_update(update_id)
        log_external_failure("Telegram update failed", exc)

        return jsonify(
            {
                "ok": False,
                "error": "temporary failure",
            }
        ), 503

    return jsonify(
        {
            "ok": True,
        }
    )


@app.get("/messenger")
def messenger_verify_webhook():

    if not META_VERIFY_TOKEN:
        return "Messenger webhook is not configured", 503

    if (
        request.args.get("hub.mode") == "subscribe"
        and request.args.get("hub.verify_token") == META_VERIFY_TOKEN
    ):
        return request.args.get("hub.challenge", ""), 200

    return "Forbidden", 403


@app.post("/messenger")
def messenger_webhook():

    raw_body = request.get_data(cache=True)
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not messenger_signature_is_valid(raw_body, signature):
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    payload = request.get_json(silent=True) or {}

    if payload.get("object") != "page":
        return jsonify({"ok": True, "ignored": True})

    try:
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = (event.get("sender") or {}).get("id")
                message = event.get("message") or {}
                message_id = message.get("mid")
                text = message.get("text")

                if (
                    not sender_id
                    or not text
                    or message.get("is_echo")
                    or message_was_processed(message_id)
                ):
                    continue

                answer = handle_message(
                    f"messenger:{sender_id}",
                    text,
                )
                messenger_send_text(sender_id, answer)
                remember_message(message_id)

    except Exception as exc:
        log_external_failure("Messenger update failed", exc)
        return jsonify({"ok": False, "error": "handled"}), 500

    return jsonify({"ok": True})


init_db()


if __name__ == "__main__":

    port = int(os.environ.get("PORT", "8000"))

    app.run(
        host="0.0.0.0",
        port=port,
    )
