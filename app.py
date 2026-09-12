import json
import hmac
import math
import os
import re
import sqlite3
from datetime import datetime, timezone
from functools import wraps

import requests
from flask import Flask, jsonify, request


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "").strip()
DASHBOARD_SESSION_SECRET = os.environ.get("DASHBOARD_SESSION_SECRET", "").strip()
DB_PATH = os.environ.get("DB_PATH", "customer_agent.db").strip()
PORT = int(os.environ.get("PORT", "10000"))

API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
app = Flask(__name__)
TELEGRAM_REQUEST_ERROR = "telegram request failed"
MAX_REQUEST_BYTES = 256 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES


DEFAULT_PRODUCTS = {
    "الجهاز": {
        "price": 30.0,
        "currency": "$",
        "available": True,
        "aliases": ["الجهاز", "جهاز", "أجهزة", "اجهزة", "الأجهزة", "الاجهزة"],
        "colors": ["أسود", "أبيض"],
        "payment_methods": ["الدفع عند الاستلام"],
    },
    "منتج تجريبي": {
        "price": 30.0,
        "currency": "$",
        "available": True,
        "aliases": ["منتج تجريبي", "التجريبي"],
        "colors": ["أسود"],
        "payment_methods": ["الدفع عند الاستلام"],
    },
}

DEFAULT_DELIVERY = {
    "حلب": "2-3 أيام",
    "دمشق": "3-5 أيام",
    "حمص": "2-4 أيام",
    "اللاذقية": "2-4 أيام",
    "الحسكة": "2-4 أيام",
}

ORDER_STATUSES = frozenset({
    "new", "confirmed", "processing", "shipped", "delivered", "cancelled",
})

CITIES = [
    "ريف دمشق", "أشرفية صحنايا", "معضمية الشام", "دير عطية", "رأس العين",
    "جسر الشغور", "معرة النعمان", "معرة مصرين", "بصرى الشام", "تل أبيض",
    "خان أرنبة", "عين العرب", "تل رفعت", "دمشق", "دوما", "حرستا", "عربين",
    "سقبا", "حمورية", "زملكا", "جرمانا", "صحنايا", "داريا", "قدسيا", "الهامة",
    "التل", "يبرود", "النبك", "القطيفة", "الزبداني", "مضايا", "بلودان", "قطنا",
    "الكسوة", "حلب", "منبج", "الباب", "اعزاز", "أعزاز", "عفرين", "جرابلس",
    "السفيرة", "دير حافر", "مسكنة", "كوباني", "مارع", "الاتارب", "الأتارب",
    "حمص", "تدمر", "الرستن", "تلبيسة", "القصير", "تلكلخ", "المخرم", "القريتين",
    "الحولة", "حماة", "سلمية", "مصياف", "محردة", "السقيلبية", "صوران", "كفرزيتا",
    "اللاذقية", "جبلة", "القرداحة", "الحفة", "كسب", "طرطوس", "بانياس", "صافيتا",
    "الدريكيش", "الشيخ بدر", "القدموس", "إدلب", "أريحا", "اريحا", "سراقب", "بنش",
    "سرمين", "الدانا", "كفرنبل", "الحسكة", "القامشلي", "المالكية", "ديريك", "راس العين",
    "عامودا", "الدرباسية", "الشدادي", "تل تمر", "القحطانية", "اليعربية", "الرقة", "الطبقة",
    "تل ابيض", "معدان", "المنصورة", "دير الزور", "الميادين", "البوكمال", "العشارة", "القورية",
    "موحسن", "درعا", "نوى", "الصنمين", "طفس", "جاسم", "ازرع", "إزرع", "داعل", "الحراك",
    "السويداء", "شهبا", "صلخد", "القريا", "القنيطرة", "خان ارنبة", "البعث",
]

CONFIGURATION_ERRORS = []


def _valid_text_list(value, allow_text=False):
    if allow_text and isinstance(value, str):
        return bool(value.strip())
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _valid_products(value):
    for name, data in value.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(data, dict):
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


def _json_env(name, default, validator=None):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        CONFIGURATION_ERRORS.append(f"{name} must be valid JSON")
        return default
    if not isinstance(value, dict):
        CONFIGURATION_ERRORS.append(f"{name} must be a JSON object")
        return default
    if not value:
        CONFIGURATION_ERRORS.append(f"{name} must not be empty")
        return default
    if validator and not validator(value):
        CONFIGURATION_ERRORS.append(f"{name} has an invalid schema")
        return default
    return value


PRODUCTS = _json_env("PRODUCTS_JSON", DEFAULT_PRODUCTS, _valid_products)
DELIVERY = _json_env("DELIVERY_JSON", DEFAULT_DELIVERY, _valid_delivery)


# =========================================================
# DATABASE
# =========================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = db_connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            customer_name TEXT,
            customer_phone TEXT,
            product_name TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL DEFAULT 0,
            total_price REAL NOT NULL DEFAULT 0,
            currency TEXT,
            country TEXT,
            city TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            customer_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions(
            chat_id TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS processed_updates(
            update_id INTEGER PRIMARY KEY,
            processed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_status_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            old_status TEXT,
            new_status TEXT NOT NULL,
            source TEXT NOT NULL,
            changed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders(customer_phone);
        CREATE INDEX IF NOT EXISTS idx_order_status_events_order_id
            ON order_status_events(order_id, id);
        """
    )
    conn.commit()
    conn.close()


DEFAULT_STATE = {
    "name": None,
    "phone": None,
    "city": None,
    "product": None,
    "qty": 1,
    "buying": False,
    "done": False,
    "order_id": None,
}


def session(chat_id):
    key = str(chat_id)
    conn = db_connect()
    row = conn.execute("SELECT state_json FROM sessions WHERE chat_id=?", (key,)).fetchone()
    conn.close()
    if not row:
        return dict(DEFAULT_STATE)
    try:
        value = json.loads(row["state_json"])
        state = dict(DEFAULT_STATE)
        state.update(value if isinstance(value, dict) else {})
        return state
    except json.JSONDecodeError:
        return dict(DEFAULT_STATE)


def save_session(chat_id, state):
    key = str(chat_id)
    payload = json.dumps(state, ensure_ascii=False)
    conn = db_connect()
    conn.execute(
        """
        INSERT INTO sessions(chat_id, state_json, updated_at)
        VALUES(?,?,?)
        ON CONFLICT(chat_id) DO UPDATE SET
          state_json=excluded.state_json,
          updated_at=excluded.updated_at
        """,
        (key, payload, utc_now()),
    )
    conn.commit()
    conn.close()


def reset(chat_id):
    conn = db_connect()
    conn.execute("DELETE FROM sessions WHERE chat_id=?", (str(chat_id),))
    conn.commit()
    conn.close()


def claim_update(update_id):
    """Atomically reserve a Telegram update so concurrent deliveries run once."""
    if update_id is None:
        return True
    conn = db_connect()
    cursor = conn.execute(
        "INSERT OR IGNORE INTO processed_updates(update_id, processed_at) VALUES(?,?)",
        (update_id, utc_now()),
    )
    conn.execute(
        "DELETE FROM processed_updates WHERE update_id < ?",
        (update_id - 10000,),
    )
    conn.commit()
    claimed = cursor.rowcount == 1
    conn.close()
    return claimed


def release_update(update_id):
    """Allow Telegram to retry an update whose processing did not complete."""
    if update_id is None:
        return
    conn = db_connect()
    conn.execute("DELETE FROM processed_updates WHERE update_id=?", (update_id,))
    conn.commit()
    conn.close()


# =========================================================
# TEXT / INTENT HELPERS
# =========================================================

def norm(value):
    text = str(value or "").strip().lower()
    for old, new in {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"}.items():
        text = text.replace(old, new)
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_any(text, phrases):
    n = norm(text)
    return any(norm(phrase) in n for phrase in phrases)


def detect_phone(text):
    match = re.search(r"(?<!\d)(\+?\d[\d\s\-]{6,16}\d)(?!\d)", str(text))
    if not match:
        return None
    phone = re.sub(r"[^\d+]", "", match.group(1))
    return phone if len(re.sub(r"\D", "", phone)) >= 8 else None


def detect_city(text):
    n = norm(text)
    for city in sorted(CITIES, key=lambda x: len(norm(x)), reverse=True):
        if norm(city) in n:
            return city
    return None


def detect_products(text):
    n = norm(text)
    found = []
    for name, data in PRODUCTS.items():
        aliases = set(data.get("aliases", []))
        aliases.add(name)
        if any(norm(alias) and norm(alias) in n for alias in aliases):
            found.append((name, data))
    return found


def detect_product(text):
    found = detect_products(text)
    return found[0] if len(found) == 1 else None


def detect_quantity(text):
    n = norm(text)
    match = re.search(r"\b(\d+)\b", n)
    if match and int(match.group(1)) > 0:
        return min(int(match.group(1)), 999)
    mapping = {
        "واحد": 1, "واحده": 1, "جهازين": 2, "قطعتين": 2, "منتجين": 2,
        "اثنين": 2, "اتنين": 2, "ثلاث": 3, "ثلاثه": 3, "اربع": 4,
        "اربعه": 4, "خمس": 5, "خمسه": 5,
    }
    for word, qty in mapping.items():
        if norm(word) in n:
            return qty
    return 1


def explicit_name(text):
    match = re.search(
        r"(?:اسمي|الاسم)\s*[:\-]?\s*([\u0600-\u06FF]{2,20}(?:\s+[\u0600-\u06FF]{2,20})?)",
        str(text),
    )
    return match.group(1).strip() if match else None


def is_buy_intent(text):
    n = norm(text)
    if re.search(r"(?:^|\s)(?:ما|مو|مش)\s+(?:بدي|بدنا|اريد|نريد|حاب|حابب|حابه)(?:\s|$)", n):
        return False
    if contains_any(text, [
        "بدي اشتري", "اريد شراء", "أريد شراء", "بدي اخد", "بدي آخذ", "حابب اشتري",
        "حابه اشتري", "حاب اشتري", "بدي اطلب", "اريد الطلب", "أريد الطلب", "يلزمني",
        "بدي جهاز", "بدي منتج", "تسجيل طلب", "سجل طلب", "سجلي طلب", "اطلب", "اشتري",
    ]):
        return True

    # Accept natural phrases where a quantity or filler words separate the
    # purchase verb from a configured product, e.g. "بدي 4 أجهزة". Limit the
    # gap and reject information-seeking words so "بدي أعرف سعر الجهاز" does
    # not accidentally start an order.
    purchase_words = (
        "بدي", "بدنا", "اريد", "نريد", "حاب", "حابب", "حابه", "يلزمني",
        "عطيني", "اعطيني",
    )
    information_words = {
        "اعرف", "اسال", "استفسر", "خبرني", "معلومات", "سعر", "لون",
        "الوان", "توصيل", "شحن", "دفع",
    }
    aliases = {
        norm(alias)
        for name, data in PRODUCTS.items()
        for alias in [name, *data.get("aliases", [])]
        if norm(alias)
    }
    for word in purchase_words:
        for match in re.finditer(rf"(?:^|\s){re.escape(word)}(?:\s|$)", n):
            tail = n[match.end():].strip()
            alias_positions = [tail.find(alias) for alias in aliases if alias in tail]
            if not alias_positions:
                continue
            between = tail[:min(alias_positions)].split()
            if len(between) <= 4 and not information_words.intersection(between):
                return True
    return False


def is_products_question(text):
    return contains_any(text, [
        "شو في عندكم", "شو عندكم", "شو المنتجات", "ما هي المنتجات", "ماهي المنتجات",
        "عندكم منتجات", "المنتجات المتوفره", "المنتجات المتاحة", "اعرض المنتجات", "عرض المنتجات",
        "المنتجات", "شو بتبيعوا", "شو تبيعوا",
    ])


def is_product_count_question(text):
    return contains_any(text, ["كم منتج", "عدد المنتجات", "قديش منتج", "كم نوع", "قديش نوع"])


def is_price_question(text):
    return contains_any(text, [
        "سعر", "بكم", "قديش السعر", "قديش سعر", "قديش حق", "كم حق",
        "شو حق", "حقه", "ثمن",
    ])


def is_delivery_question(text):
    return contains_any(text, ["توصيل", "شحن", "يوصل", "التوصيل", "مدة التوصيل"])


def is_color_question(text):
    return contains_any(text, [
        "كم لون", "عدد الالوان", "ما هو اللون", "ماهي الالوان", "ما هي الالوان",
        "شو اللون", "شو الالوان", "لون الجهاز", "لون المنتج", "اللون المتوفر",
        "الوان", "ألوان",
    ])


def is_payment_question(text):
    return contains_any(text, [
        "طرق الدفع", "طريقه الدفع", "طريقة الدفع", "كيف الدفع", "كيف ادفع",
        "كيف أدفع", "كيف فيني ادفع", "شلون ادفع", "متى لازم ادفع",
        "امتى لازم ادفع", "وقت الدفع", "وين ادفع", "وسائل الدفع",
        "خيارات الدفع", "دفع عند الاستلام",
    ])


def is_cancel_command(text):
    n = norm(text)
    if n == "الغاء":
        return True
    return any(command in n for command in {
        "الغاء الطلب", "الغي الطلب", "ابدأ من جديد", "بدايه جديده",
    })


def money(value):
    value = float(value)
    return int(value) if value.is_integer() else round(value, 2)


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


def product_list_text():
    lines = []
    for name, data in PRODUCTS.items():
        status = "متوفر" if data.get("available", True) else "غير متوفر"
        lines.append(f"• {name}: {money(data['price'])}{data['currency']} — {status}")
    return "المنتجات المتوفرة حالياً:\n" + "\n".join(lines)


def configured_list(data, key):
    values = data.get(key, [])
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def selected_product(state, detected_product):
    if detected_product:
        return detected_product
    name = state.get("product")
    if name in PRODUCTS:
        return name, PRODUCTS[name]
    return None


def product_color_text(name, data):
    colors = configured_list(data, "colors")
    if not colors:
        return f"ألوان {name} غير محددة حالياً؛ خبرني إذا بدك أتأكد من المتجر."
    return f"عدد ألوان {name}: {len(colors)}\nالألوان المتوفرة: {'، '.join(colors)}"


def catalog_colors_text():
    lines = []
    for name, data in PRODUCTS.items():
        if not data.get("available", True):
            continue
        colors = configured_list(data, "colors")
        if colors:
            lines.append(f"• {name}: {len(colors)} — {'، '.join(colors)}")
    if not lines:
        return "الألوان غير محددة حالياً؛ لأي منتج بدك أتأكد؟"
    return "الألوان المتوفرة حسب المنتج:\n" + "\n".join(lines)


def payment_methods_text(product=None):
    products = [product] if product else [
        (name, data) for name, data in PRODUCTS.items() if data.get("available", True)
    ]
    methods = []
    for _, data in products:
        for method in configured_list(data, "payment_methods"):
            if method not in methods:
                methods.append(method)
    if not methods:
        return "طرق الدفع غير محددة حالياً؛ خبرني إذا بدك أتأكد من المتجر."
    prefix = f"طرق الدفع المتاحة للمنتج {product[0]}" if product else "طرق الدفع المتاحة"
    return prefix + ":\n" + "\n".join(f"• {method}" for method in methods)


def informational_answers(text, state, detected_product, city):
    answers = []
    product = selected_product(state, detected_product)

    if is_product_count_question(text):
        available = [data for data in PRODUCTS.values() if data.get("available", True)]
        answers.append(
            f"عندنا حالياً {len(available)} منتج/نوع متوفر.\n\n{product_list_text()}"
        )
    elif is_products_question(text):
        answers.append(
            product_list_text() + "\n\nإذا بدك واحد منهم، قلي مثلاً: بدي أطلب الجهاز."
        )

    if is_price_question(text):
        if product:
            name, data = product
            answers.append(f"سعر {name} هو {money(data['price'])}{data['currency']} ✅")
        else:
            answers.append(
                "أكيد 👍 لأي منتج بدك السعر؟\n" +
                "\n".join(f"• {name}" for name in PRODUCTS)
            )

    if is_delivery_question(text):
        if city:
            answers.append(f"التوصيل إلى {city}: {DELIVERY.get(city, '2-4 أيام')} 🚚")
        else:
            answers.append("أكيد 🚚 لأي مدينة بدك تعرف مدة التوصيل؟")

    if is_color_question(text):
        answers.append(product_color_text(*product) if product else catalog_colors_text())

    if is_payment_question(text):
        answers.append(payment_methods_text(product))

    return answers


def combine_answers(answers, next_message):
    return "\n\n".join([*answers, next_message]) if answers else next_message


def order_resume_prompt(state):
    if not state.get("buying"):
        return None
    if state.get("done"):
        return f"طلبك مسجل مسبقاً ✅ رقم الطلب: {state.get('order_id')}"
    if not state.get("product"):
        return "وطلبك الحالي ما زال محفوظاً؛ شو المنتج اللي بدك تطلبه؟"
    if not state.get("name"):
        return "وطلبك الحالي ما زال محفوظاً؛ شو اسمك حتى نكمله؟"
    if not state.get("phone"):
        return f"وطلبك الحالي ما زال محفوظاً يا {state['name']}؛ ابعتلي رقم الهاتف."
    if not state.get("city"):
        return "وطلبك الحالي ما زال محفوظاً؛ بقي بس أعرف مدينة التوصيل."
    return "وطلبك الحالي ما زال محفوظاً وجاهزاً للإكمال."


# =========================================================
# ORDERS
# =========================================================

def create_order(chat_id, state, original_text):
    product = PRODUCTS[state["product"]]
    unit_price = float(product["price"])
    total_price = unit_price * int(state["qty"])
    now = utc_now()
    conn = db_connect()
    cursor = conn.execute(
        """
        INSERT INTO orders(
            chat_id, customer_name, customer_phone, product_name, quantity,
            unit_price, total_price, currency, country, city, status,
            customer_message, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            str(chat_id), state["name"], state["phone"], state["product"], int(state["qty"]),
            unit_price, total_price, product["currency"], "سوريا", state["city"], "new",
            original_text, now, now,
        ),
    )
    order_id = cursor.lastrowid
    conn.execute(
        """
        INSERT INTO order_status_events(
            order_id, old_status, new_status, source, changed_at
        ) VALUES(?,?,?,?,?)
        """,
        (order_id, None, "new", "telegram", now),
    )
    conn.commit()
    conn.close()
    return order_id


def set_order_status(order_id, new_status, source):
    conn = db_connect()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT status FROM orders WHERE id=?", (order_id,)
    ).fetchone()
    if not row:
        conn.rollback()
        conn.close()
        return None

    old_status = row["status"]
    changed_at = utc_now()
    conn.execute(
        "UPDATE orders SET status=?, updated_at=? WHERE id=?",
        (new_status, changed_at, order_id),
    )
    conn.execute(
        """
        INSERT INTO order_status_events(
            order_id, old_status, new_status, source, changed_at
        ) VALUES(?,?,?,?,?)
        """,
        (order_id, old_status, new_status, source, changed_at),
    )
    conn.commit()
    conn.close()
    return {
        "old_status": old_status,
        "new_status": new_status,
        "changed_at": changed_at,
    }


def maybe_capture_name(state, text):
    if state["name"]:
        return
    explicit = explicit_name(text)
    if explicit:
        state["name"] = explicit
        return
    if state["buying"] and not detect_phone(text) and not detect_city(text) and not detect_product(text):
        words = norm(text).split()
        blocked = {
            "مرحبا", "هلا", "اهلا", "السلام", "عليكم", "بدي", "اريد", "طلب", "منتج",
            "جهاز", "سعر", "توصيل", "شحن", "نعم", "اي", "ايوه",
        }
        if 1 <= len(words) <= 3 and not any(word in blocked for word in words):
            if all(re.fullmatch(r"[\u0600-\u06FF]+", word) for word in words):
                state["name"] = text.strip()


# =========================================================
# SALES AGENT LOGIC
# =========================================================

def handle_message(chat_id, text):
    state = session(chat_id)
    text = str(text or "").strip()
    if not text:
        return "اكتبلي رسالتك حتى أساعدك 👌"

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

    if is_cancel_command(text):
        reset(chat_id)
        return "✅ تمام، لغيت المحادثة الحالية. فيك تبدأ من جديد."

    buy_intent = is_buy_intent(text)
    answers = informational_answers(text, state, product, city)
    if not buy_intent:
        if answers:
            resume_prompt = order_resume_prompt(state)
            if resume_prompt:
                answers.append(resume_prompt)
            save_session(chat_id, state)
            return "\n\n".join(answers)

    if contains_any(text, ["مرحبا", "اهلا", "أهلا", "هلا", "السلام عليكم", "هاي", "hello", "hi"]):
        if not state["buying"] and not buy_intent:
            save_session(chat_id, state)
            return "أهلاً وسهلاً 👋\nفيني أعرض المنتجات والأسعار، أخبرك عن التوصيل، أو أسجّل لك طلب مباشرة."

    if n in {"المنتج", "منتج", "الجهاز", "جهاز"} and not state["buying"]:
        save_session(chat_id, state)
        if product:
            data = product[1]
            return f"{product[0]} متوفر ✅ وسعره {money(data['price'])}{data['currency']}.\nإذا بدك تطلبه قلي: بدي أطلبه."
        return product_list_text()

    if buy_intent:
        state["buying"] = True
        state["done"] = False
        state["qty"] = detect_quantity(text)

    if state["buying"]:
        maybe_capture_name(state, text)

        if not state["product"]:
            available_names = [name for name, data in PRODUCTS.items() if data.get("available", True)]
            if len(available_names) == 1:
                state["product"] = available_names[0]
            else:
                save_session(chat_id, state)
                return combine_answers(
                    answers,
                    "تمام 👍 شو المنتج اللي بدك تطلبه؟\n" +
                    "\n".join(f"• {name}" for name in available_names),
                )

        if not state["name"]:
            save_session(chat_id, state)
            return combine_answers(answers, "تمام 👍 شو اسمك حتى أسجل الطلب؟")
        if not state["phone"]:
            save_session(chat_id, state)
            return combine_answers(answers, f"تمام {state['name']} 👍 ابعتلي رقم الهاتف.")
        if not state["city"]:
            save_session(chat_id, state)
            return combine_answers(answers, "ممتاز 👍 بقي بس أعرف المدينة للتوصيل.")
        if state["done"]:
            save_session(chat_id, state)
            return combine_answers(
                answers,
                f"طلبك مسجل مسبقاً ✅ رقم الطلب: {state['order_id']}",
            )

        order_id = create_order(chat_id, state, text)
        state["done"] = True
        state["order_id"] = order_id
        save_session(chat_id, state)

        data = PRODUCTS[state["product"]]
        total = float(data["price"]) * int(state["qty"])
        confirmation = (
            "✅ تم تسجيل طلبك بنجاح\n\n"
            f"رقم الطلب: {order_id}\n"
            f"الاسم: {state['name']}\n"
            f"المنتج: {state['product']}\n"
            f"الكمية: {state['qty']}\n"
            f"الإجمالي: {money(total)}{data['currency']}\n"
            f"المدينة: {state['city']}\n"
            f"التوصيل: {DELIVERY.get(state['city'], '2-4 أيام')}"
        )
        return combine_answers(answers, confirmation)

    save_session(chat_id, state)
    return (
        "فهمت عليك جزئياً 👌\n"
        "جرب اسألني مثلاً:\n"
        "• شو المنتجات؟\n"
        "• كم سعر الجهاز؟\n"
        "• التوصيل للحسكة؟\n"
        "• بدي أسجل طلب."
    )


# =========================================================
# TELEGRAM
# =========================================================

def telegram_api(method, **data):
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    response = requests.post(f"{API}/{method}", json=data, timeout=20)
    response.raise_for_status()
    return response.json()


def log_external_failure(context, exc):
    """Log only the exception class so request URLs cannot expose bot tokens."""
    print(f"{context}: {type(exc).__name__}")


def resolved_webhook_url():
    if not WEBHOOK_URL:
        return ""
    url = WEBHOOK_URL.rstrip("/")
    return url if url.endswith("/telegram") else url + "/telegram"


def register_webhook():
    url = resolved_webhook_url()
    if not BOT_TOKEN or not url:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN or WEBHOOK_URL missing"}
    payload = {"url": url, "drop_pending_updates": False}
    if WEBHOOK_SECRET:
        payload["secret_token"] = WEBHOOK_SECRET
    response = requests.post(f"{API}/setWebhook", json=payload, timeout=20)
    response.raise_for_status()
    return response.json()


def webhook_authorized():
    if not WEBHOOK_SECRET:
        return True
    provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    return hmac.compare_digest(provided, WEBHOOK_SECRET)


# =========================================================
# ADMIN API
# =========================================================

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not ADMIN_API_KEY:
            return jsonify({"ok": False, "error": "ADMIN_API_KEY is not configured"}), 503
        provided = request.headers.get("X-Admin-Key", "")
        if not hmac.compare_digest(provided, ADMIN_API_KEY):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapped


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({
        "ok": False,
        "error": "request payload too large",
        "max_bytes": MAX_REQUEST_BYTES,
    }), 413


@app.get("/")
def root():
    return jsonify({"name": "Customer Agent", "version": "7.0", "status": "ok"})


def database_available():
    try:
        conn = db_connect()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except Exception:
        return False


def deployment_configuration_errors():
    settings = {
        "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
        "WEBHOOK_URL": WEBHOOK_URL,
        "ADMIN_API_KEY": ADMIN_API_KEY,
        "WEBHOOK_SECRET": WEBHOOK_SECRET,
        "DASHBOARD_SESSION_SECRET": DASHBOARD_SESSION_SECRET,
    }
    errors = [
        f"{name} is not configured"
        for name, value in settings.items()
        if not value
    ]
    if WEBHOOK_URL and not WEBHOOK_URL.lower().startswith("https://"):
        errors.append("WEBHOOK_URL must use HTTPS")
    return errors


@app.get("/health")
def health():
    db_ok = database_available()
    config_ok = not CONFIGURATION_ERRORS
    healthy = db_ok and config_ok
    return jsonify({
        "ok": healthy,
        "database": "ok" if db_ok else "error",
        "configuration": "ok" if config_ok else "error",
        "configuration_errors": list(CONFIGURATION_ERRORS),
        "telegram_configured": bool(BOT_TOKEN),
        "webhook_url_configured": bool(WEBHOOK_URL),
    }), 200 if healthy else 503


@app.get("/ready")
def ready():
    db_ok = database_available()
    errors = [*CONFIGURATION_ERRORS, *deployment_configuration_errors()]
    ready_for_traffic = db_ok and not errors
    return jsonify({
        "ok": ready_for_traffic,
        "database": "ok" if db_ok else "error",
        "configuration": "ok" if not errors else "error",
        "configuration_errors": errors,
    }), 200 if ready_for_traffic else 503


@app.post("/admin/setup-webhook")
@admin_required
def setup_webhook():
    try:
        return jsonify(register_webhook())
    except Exception as exc:
        log_external_failure("Telegram webhook setup failed", exc)
        return jsonify({"ok": False, "error": TELEGRAM_REQUEST_ERROR}), 502


@app.get("/admin/orders")
@admin_required
def admin_orders():
    status = request.args.get("status", "").strip()
    if status and status not in ORDER_STATUSES:
        return jsonify({
            "ok": False,
            "error": "invalid status",
            "allowed": sorted(ORDER_STATUSES),
        }), 400
    limit = parse_order_limit(request.args.get("limit"))
    if limit is None:
        return jsonify({
            "ok": False,
            "error": "limit must be an integer",
            "minimum": 1,
            "maximum": 200,
        }), 400
    offset = parse_order_offset(request.args.get("offset"))
    if offset is None:
        return jsonify({
            "ok": False,
            "error": "offset must be an integer between 0 and 1000000",
            "minimum": 0,
            "maximum": 1_000_000,
        }), 400
    conn = db_connect()
    if status:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM orders WHERE status=?", (status,)
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT * FROM orders WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        ).fetchall()
    else:
        total = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    conn.close()
    return jsonify({
        "ok": True,
        "orders": [dict(row) for row in rows],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total": total,
            "has_more": offset + len(rows) < total,
        },
    })


@app.get("/admin/stats")
@admin_required
def admin_stats():
    conn = db_connect()
    total_orders = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
    revenue = conn.execute("SELECT COALESCE(SUM(total_price),0) AS s FROM orders WHERE status != 'cancelled'").fetchone()["s"]
    by_status = conn.execute("SELECT status, COUNT(*) AS count FROM orders GROUP BY status").fetchall()
    conn.close()
    return jsonify({
        "ok": True,
        "total_orders": total_orders,
        "recorded_revenue": round(float(revenue), 2),
        "orders_by_status": {row["status"]: row["count"] for row in by_status},
    })


@app.patch("/admin/orders/<int:order_id>/status")
@admin_required
def update_order_status(order_id):
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status", "")).strip().lower()
    if status not in ORDER_STATUSES:
        return jsonify({
            "ok": False,
            "error": "invalid status",
            "allowed": sorted(ORDER_STATUSES),
        }), 400
    change = set_order_status(order_id, status, "admin_api")
    if change is None:
        return jsonify({"ok": False, "error": "order not found"}), 404
    return jsonify({
        "ok": True,
        "order_id": order_id,
        "status": status,
        "previous_status": change["old_status"],
        "changed_at": change["changed_at"],
    })


@app.get("/admin/orders/<int:order_id>/history")
@admin_required
def order_status_history(order_id):
    conn = db_connect()
    order = conn.execute("SELECT id FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({"ok": False, "error": "order not found"}), 404
    rows = conn.execute(
        """
        SELECT id, old_status, new_status, source, changed_at
        FROM order_status_events
        WHERE order_id=?
        ORDER BY id ASC
        """,
        (order_id,),
    ).fetchall()
    conn.close()
    return jsonify({
        "ok": True,
        "order_id": order_id,
        "events": [dict(row) for row in rows],
    })


@app.get("/webhook-info")
def webhook_info():
    if not BOT_TOKEN:
        return jsonify({"ok": False, "error": "TELEGRAM_BOT_TOKEN missing"}), 500
    try:
        response = requests.get(f"{API}/getWebhookInfo", timeout=20)
        data = response.json()
        result = data.get("result", {}) if isinstance(data, dict) else {}
        return jsonify({
            "ok": bool(data.get("ok")),
            "url": result.get("url", ""),
            "pending_update_count": result.get("pending_update_count", 0),
            "last_error_message": result.get("last_error_message", ""),
        })
    except Exception as exc:
        log_external_failure("Telegram webhook info failed", exc)
        return jsonify({"ok": False, "error": TELEGRAM_REQUEST_ERROR}), 500


@app.post("/telegram")
def telegram_webhook():
    if not webhook_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    update = request.get_json(silent=True) or {}
    update_id = update.get("update_id")

    if not claim_update(update_id):
        return jsonify({"ok": True, "duplicate": True})

    message = update.get("message", {})
    text = message.get("text")
    chat_id = message.get("chat", {}).get("id")

    if not text or chat_id is None:
        return jsonify({"ok": True})

    try:
        if text == "/start":
            answer = (
                "أهلاً وسهلاً 👋\nأنا مساعد المتجر.\n"
                "اسألني عن المنتجات والأسعار والتوصيل، أو قلي بدي أسجل طلب."
            )
        elif text == "/reset":
            reset(chat_id)
            answer = "✅ تم بدء محادثة جديدة."
        elif text == "/products":
            answer = product_list_text()
        else:
            answer = handle_message(chat_id, text)

        telegram_api("sendMessage", chat_id=chat_id, text=answer)
    except Exception as exc:
        release_update(update_id)
        log_external_failure("Telegram update failed", exc)
        return jsonify({"ok": False, "error": "handled"}), 200

    return jsonify({"ok": True})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
