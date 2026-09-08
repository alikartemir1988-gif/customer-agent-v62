import os
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for

from app import db_connect, utc_now


dashboard_app = Flask(__name__, template_folder="templates")
dashboard_app.secret_key = os.environ.get("DASHBOARD_SESSION_SECRET", "").strip() or os.urandom(32)

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "").strip()


def dashboard_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("dashboard_authenticated") is not True:
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


@dashboard_app.get("/login")
def login():
    return render_template("login.html", error=None)


@dashboard_app.post("/login")
def login_post():
    password = request.form.get("password", "")
    if not ADMIN_API_KEY:
        return render_template(
            "login.html",
            error="ADMIN_API_KEY غير مضبوط على الخادم.",
        ), 503
    if password != ADMIN_API_KEY:
        return render_template(
            "login.html",
            error="كلمة المرور غير صحيحة.",
        ), 401
    session.clear()
    session["dashboard_authenticated"] = True
    return redirect(url_for("dashboard"))


@dashboard_app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@dashboard_app.get("/")
@dashboard_required
def dashboard():
    status_filter = request.args.get("status", "").strip().lower()
    allowed = {"new", "confirmed", "processing", "shipped", "delivered", "cancelled"}
    if status_filter and status_filter not in allowed:
        status_filter = ""

    conn = db_connect()
    if status_filter:
        orders = conn.execute(
            "SELECT * FROM orders WHERE status=? ORDER BY id DESC LIMIT 200",
            (status_filter,),
        ).fetchall()
    else:
        orders = conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT 200"
        ).fetchall()

    total_orders = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
    active_orders = conn.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE status NOT IN ('delivered','cancelled')"
    ).fetchone()["c"]
    delivered_orders = conn.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE status='delivered'"
    ).fetchone()["c"]
    recorded_revenue = conn.execute(
        "SELECT COALESCE(SUM(total_price),0) AS s FROM orders WHERE status != 'cancelled'"
    ).fetchone()["s"]
    conn.close()

    return render_template(
        "dashboard.html",
        orders=[dict(row) for row in orders],
        status_filter=status_filter,
        allowed_statuses=sorted(allowed),
        total_orders=total_orders,
        active_orders=active_orders,
        delivered_orders=delivered_orders,
        recorded_revenue=round(float(recorded_revenue), 2),
    )


@dashboard_app.post("/orders/<int:order_id>/status")
@dashboard_required
def change_order_status(order_id):
    allowed = {"new", "confirmed", "processing", "shipped", "delivered", "cancelled"}
    status = request.form.get("status", "").strip().lower()
    if status not in allowed:
        return "Invalid status", 400

    conn = db_connect()
    cursor = conn.execute(
        "UPDATE orders SET status=?, updated_at=? WHERE id=?",
        (status, utc_now(), order_id),
    )
    conn.commit()
    changed = cursor.rowcount
    conn.close()

    if not changed:
        return "Order not found", 404
    return redirect(request.referrer or url_for("dashboard"))


@dashboard_app.get("/health")
def health():
    try:
        conn = db_connect()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return {"ok": True, "service": "dashboard"}
    except Exception:
        return {"ok": False, "service": "dashboard"}, 500


if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", "10001"))
    dashboard_app.run(host="0.0.0.0", port=port)
