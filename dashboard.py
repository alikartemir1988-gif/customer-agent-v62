import hashlib
import hmac
import os
import secrets
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for

from app import ORDER_STATUSES, database_is_available, list_orders, order_metrics, set_order_status


ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "").strip()
DASHBOARD_SESSION_SECRET = os.environ.get("DASHBOARD_SESSION_SECRET", "").strip()

dashboard_app = Flask(__name__, template_folder="templates")
if DASHBOARD_SESSION_SECRET:
    dashboard_app.secret_key = DASHBOARD_SESSION_SECRET
elif ADMIN_API_KEY:
    dashboard_app.secret_key = hashlib.sha256(
        f"customer-agent-dashboard:{ADMIN_API_KEY}".encode("utf-8")
    ).digest()
else:
    dashboard_app.secret_key = os.urandom(32)

dashboard_app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("WEBHOOK_URL", "").lower().startswith("https://"),
)


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_valid():
    expected = session.get("csrf_token", "")
    provided = request.form.get("csrf_token", "")
    return bool(expected and hmac.compare_digest(expected, provided))


@dashboard_app.after_request
def secure_dashboard_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'unsafe-inline'"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def dashboard_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("dashboard_authenticated") is not True:
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)

    return wrapped


@dashboard_app.get("/login")
def login():
    return render_template("login.html", error=None, csrf_token=csrf_token())


@dashboard_app.post("/login")
def login_post():
    if not csrf_valid():
        return "Invalid CSRF token", 400

    password = request.form.get("password", "")
    if not ADMIN_API_KEY:
        return render_template(
            "login.html",
            error="ADMIN_API_KEY غير مضبوط على الخادم.",
            csrf_token=csrf_token(),
        ), 503
    if not hmac.compare_digest(password, ADMIN_API_KEY):
        return render_template(
            "login.html",
            error="كلمة المرور غير صحيحة.",
            csrf_token=csrf_token(),
        ), 401

    session.clear()
    session["dashboard_authenticated"] = True
    return redirect(url_for("dashboard"))


@dashboard_app.post("/logout")
def logout():
    if not csrf_valid():
        return "Invalid CSRF token", 400
    session.clear()
    return redirect(url_for("login"))


@dashboard_app.get("/")
@dashboard_required
def dashboard():
    status_filter = request.args.get("status", "").strip().lower()
    if status_filter and status_filter not in ORDER_STATUSES:
        status_filter = ""
    search_query = request.args.get("q", "").strip()[:100]

    orders, _total = list_orders(
        status=status_filter,
        search=search_query,
        limit=200,
        offset=0,
    )
    metrics = order_metrics()

    return render_template(
        "dashboard.html",
        orders=orders,
        status_filter=status_filter,
        search_query=search_query,
        allowed_statuses=sorted(ORDER_STATUSES),
        csrf_token=csrf_token(),
        **metrics,
    )


@dashboard_app.post("/orders/<int:order_id>/status")
@dashboard_required
def change_order_status(order_id):
    if not csrf_valid():
        return "Invalid CSRF token", 400

    status = request.form.get("status", "").strip().lower()
    if status not in ORDER_STATUSES:
        return "Invalid status", 400

    change = set_order_status(order_id, status, "dashboard")
    if change is None:
        return "Order not found", 404
    return redirect(request.referrer or url_for("dashboard"))


@dashboard_app.get("/health")
def health():
    ok = database_is_available()
    return {"ok": ok, "service": "customer-agent-dashboard"}, (200 if ok else 503)


if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", "10001"))
    dashboard_app.run(host="0.0.0.0", port=port)
