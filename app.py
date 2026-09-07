import os
import re
import sqlite3
from datetime import datetime

import requests
from flask import Flask, jsonify, request


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
DB_PATH = os.environ.get("DB_PATH", "customer_agent.db").strip()

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

SESSIONS = {}


# =========================================================
# PRODUCTS
# =========================================================

PRODUCTS = {
    "الجهاز": {
        "price": 30.0,
        "currency": "$",
        "available": True,
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
        "aliases": [
            "منتج تجريبي",
            "التجريبي",
        ],
    },
}


# =========================================================
# DELIVERY
# =========================================================

DELIVERY = {
    "حلب": "2-3 أيام",
    "دمشق": "3-5 أيام",
    "حمص": "2-4 أيام",
    "اللاذقية": "2-4 أيام",
    "الحسكة": "2-4 أيام",
}


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

def init_db():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=20,
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    conn.commit()
    conn.close()


# =========================================================
# SESSION
# =========================================================

def session(chat_id):

    return SESSIONS.setdefault(
        str(chat_id),
        {
            "name": None,
            "phone": None,
            "city": None,
            "product": None,
            "qty": 1,
            "buying": False,
            "done": False,
            "order_id": None,
        },
    )


def reset(chat_id):

    SESSIONS.pop(
        str(chat_id),
        None,
    )


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
            "بدي منتج",
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

    conn = sqlite3.connect(
        DB_PATH,
        timeout=20,
    )

    cursor = conn.execute(
        """
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
        """,
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

    order_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return order_id


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

def handle_message(
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

    # -----------------------------------------
    # CANCEL / RESET
    # -----------------------------------------

    if contains_any(
        text,
        [
            "الغاء الطلب",
            "إلغاء الطلب",
            "الغي الطلب",
            "ابدأ من جديد",
            "بداية جديدة",
        ],
    ):

        reset(chat_id)

        return (
            "✅ تمام، لغيت المحادثة الحالية. "
            "فيك تبدأ من جديد."
        )

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

        # Duplicate protection
        if state["done"]:

            return (
                "طلبك مسجل مسبقاً ✅ "
                f"رقم الطلب: "
                f"{state['order_id']}"
            )

        # Create order
        order_id = create_order(
            state,
            text,
        )

        state["done"] = True

        state["order_id"] = order_id

        data = PRODUCTS[
            state["product"]
        ]

        total = (
            data["price"]
            * state["qty"]
        )

        if float(total).is_integer():
            total = int(total)

        return (
            "✅ تم تسجيل طلبك بنجاح\n\n"
            f"رقم الطلب: {order_id}\n"
            f"الاسم: {state['name']}\n"
            f"المنتج: {state['product']}\n"
            f"الكمية: {state['qty']}\n"
            f"الإجمالي: "
            f"{total}{data['currency']}\n"
            f"المدينة: {state['city']}\n"
            f"التوصيل: "
            f"{DELIVERY.get(state['city'], '2-4 أيام')}"
        )

    return (
        "فهمت عليك جزئياً 👌\n"
        "جرب اسألني مثلاً:\n"
        "• شو المنتجات؟\n"
        "• كم سعر الجهاز؟\n"
        "• التوصيل للحسكة؟\n"
        "• بدي أسجل طلب."
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
        print(
            "Webhook not registered: "
            "TELEGRAM_BOT_TOKEN is missing"
        )
        return

    if not url:
        print(
            "Webhook not registered: "
            "WEBHOOK_URL is missing"
        )
        return

    try:
        response = requests.post(
            f"{API}/setWebhook",
            json={
                "url": url,
                "drop_pending_updates": True,
            },
            timeout=20,
        )

        response.raise_for_status()

        print(
            "Telegram webhook registered:",
            url,
            response.text,
        )

    except Exception as exc:
        print(
            "Webhook registration failed:",
            repr(exc),
        )


@app.get("/")
def health():

    return jsonify(
        {
            "status": "ok",
        }
    )


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
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 500


@app.post("/telegram")
def telegram_webhook():

    update = (
        request.get_json(
            silent=True
        )
        or {}
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

        print(
            "Telegram update error:",
            repr(exc),
            "update=",
            update,
        )

        return jsonify(
            {
                "ok": False,
                "error": "handled",
            }
        ), 200

    return jsonify(
        {
            "ok": True,
        }
    )


init_db()

register_webhook()
