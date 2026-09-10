import json
import hmac
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
DB_PATH = os.environ.get("DB_PATH", "customer_agent.db").strip()
PORT = int(os.environ.get("PORT", "10000"))

API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
app = Flask(__name__)
TELEGRAM_REQUEST_ERROR = "telegram request failed"


DEFAULT_PRODUCTS = {
    "الجهاز": {
        "price": 30.0,
        "currency": "$",
        "available": True,
        "aliases": ["الجهاز", "جهاز", "أجهزة", "اجهزة", "الأجهزة", "الاجهزة"],
    },
    "منتج تجريبي": {
        "price": 30.0,
        "currency": "$",
        "available": True,
        "aliases": ["منتج تجريبي", "التجريبي"],
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


def _json_env(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else default
    except json.JSONDecodeError:
        return default


PRODUCTS = _json_env("PRODUCTS_JSON", DEFAULT_PRODUCTS)
DELIVERY = _json_env("DELIVERY_JSON", DEFAULT_DELIVERY)


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

        CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders(customer_phone);
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
    return contains_any(text, [
        "بدي اشتري", "اريد شراء", "أريد شراء", "بدي اخد", "بدي آخذ", "حابب اشتري",
        "حابه اشتري", "حاب اشتري", "بدي اطلب", "اريد الطلب", "أريد الطلب", "يلزمني",
        "بدي جهاز", "بدي منتج", "تسجيل طلب", "سجل طلب", "سجلي طلب", "اطلب", "اشتري",
    ])


def is_products_question(text):
    return contains_any(text, [
        "شو في عندكم", "شو عندكم", "شو المنتجات", "ما هي المنتجات", "ماهي المنتجات",
        "عندكم منتجات", "المنتجات المتوفره", "المنتجات المتاحة", "اعرض المنتجات", "عرض المنتجات",
        "المنتجات", "شو بتبيعوا", "شو تبيعوا",
    ])


def is_product_count_question(text):
    return contains_any(text, ["كم منتج", "عدد المنتجات", "قديش منتج", "كم نوع", "قديش نوع"])


def is_price_question(text):
    return contains_any(text, ["سعر", "بكم", "قديش", "كم حق", "شو حق", "حقه", "ثمن"])


def is_delivery_question(text):
    return contains_any(text, ["توصيل", "شحن", "يوصل", "التوصيل", "مدة التوصيل"])


def money(value):
    value = float(value)
    return int(value) if value.is_integer() else round(value, 2)


def parse_order_limit(value, default=50, maximum=200):
    try:
        parsed = int(default if value is None else value)
    except (TypeError, ValueError):
        return None
    return min(max(parsed, 1), maximum)


def product_list_text():
    lines = []
    for name, data in PRODUCTS.items():
        status = "متوفر" if data.get("available", True) else "غير متوفر"
        lines.append(f"• {name}: {money(data['price'])}{data['currency']} — {status}")
    return "المنتجات المتوفرة حالياً:\n" + "\n".join(lines)


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
    conn.commit()
    conn.close()
    return order_id


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

    if contains_any(text, ["الغاء الطلب", "إلغاء الطلب", "الغي الطلب", "ابدأ من جديد", "بداية جديدة"]):
        reset(chat_id)
        return "✅ تمام، لغيت المحادثة الحالية. فيك تبدأ من جديد."

    if contains_any(text, ["مرحبا", "اهلا", "أهلا", "هلا", "السلام عليكم", "هاي", "hello", "hi"]):
        if not state["buying"]:
            save_session(chat_id, state)
            return "أهلاً وسهلاً 👋\nفيني أعرض المنتجات والأسعار، أخبرك عن التوصيل، أو أسجّل لك طلب مباشرة."

    if is_product_count_question(text):
        available = [p for p in PRODUCTS.values() if p.get("available", True)]
        save_session(chat_id, state)
        return f"عندنا حالياً {len(available)} منتج/نوع متوفر.\n\n{product_list_text()}"

    if is_products_question(text):
        save_session(chat_id, state)
        return product_list_text() + "\n\nإذا بدك واحد منهم، قلي مثلاً: بدي أطلب الجهاز."

    if is_price_question(text) and not is_buy_intent(text):
        save_session(chat_id, state)
        if product:
            data = product[1]
            return f"سعر {product[0]} هو {money(data['price'])}{data['currency']} ✅"
        return "أكيد 👍 لأي منتج بدك السعر؟\n" + "\n".join(f"• {name}" for name in PRODUCTS)

    if is_delivery_question(text) and not is_buy_intent(text):
        save_session(chat_id, state)
        if city:
            return f"التوصيل إلى {city}: {DELIVERY.get(city, '2-4 أيام')} 🚚"
        return "أكيد 🚚 لأي مدينة بدك تعرف مدة التوصيل؟"

    if n in {"المنتج", "منتج", "الجهاز", "جهاز"} and not state["buying"]:
        save_session(chat_id, state)
        if product:
            data = product[1]
            return f"{product[0]} متوفر ✅ وسعره {money(data['price'])}{data['currency']}.\nإذا بدك تطلبه قلي: بدي أطلبه."
        return product_list_text()

    if is_buy_intent(text):
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
                return "تمام 👍 شو المنتج اللي بدك تطلبه؟\n" + "\n".join(f"• {name}" for name in available_names)

        if not state["name"]:
            save_session(chat_id, state)
            return "تمام 👍 شو اسمك حتى أسجل الطلب؟"
        if not state["phone"]:
            save_session(chat_id, state)
            return f"تمام {state['name']} 👍 ابعتلي رقم الهاتف."
        if not state["city"]:
            save_session(chat_id, state)
            return "ممتاز 👍 بقي بس أعرف المدينة للتوصيل."
        if state["done"]:
            save_session(chat_id, state)
            return f"طلبك مسجل مسبقاً ✅ رقم الطلب: {state['order_id']}"

        order_id = create_order(chat_id, state, text)
        state["done"] = True
        state["order_id"] = order_id
        save_session(chat_id, state)

        data = PRODUCTS[state["product"]]
        total = float(data["price"]) * int(state["qty"])
        return (
            "✅ تم تسجيل طلبك بنجاح\n\n"
            f"رقم الطلب: {order_id}\n"
            f"الاسم: {state['name']}\n"
            f"المنتج: {state['product']}\n"
            f"الكمية: {state['qty']}\n"
            f"الإجمالي: {money(total)}{data['currency']}\n"
            f"المدينة: {state['city']}\n"
            f"التوصيل: {DELIVERY.get(state['city'], '2-4 أيام')}"
        )

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


@app.get("/")
def root():
    return jsonify({"name": "Customer Agent", "version": "7.0", "status": "ok"})


@app.get("/health")
def health():
    try:
        conn = db_connect()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({
        "ok": db_ok,
        "database": "ok" if db_ok else "error",
        "telegram_configured": bool(BOT_TOKEN),
        "webhook_url_configured": bool(WEBHOOK_URL),
    }), 200 if db_ok else 500


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
    conn = db_connect()
    if status:
        rows = conn.execute(
            "SELECT * FROM orders WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify({"ok": True, "orders": [dict(row) for row in rows]})


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
    conn = db_connect()
    cursor = conn.execute(
        "UPDATE orders SET status=?, updated_at=? WHERE id=?", (status, utc_now(), order_id)
    )
    conn.commit()
    changed = cursor.rowcount
    conn.close()
    if not changed:
        return jsonify({"ok": False, "error": "order not found"}), 404
    return jsonify({"ok": True, "order_id": order_id, "status": status})


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
        log_external_failure("Telegram update failed", exc)
        return jsonify({"ok": False, "error": "handled"}), 200

    return jsonify({"ok": True})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
