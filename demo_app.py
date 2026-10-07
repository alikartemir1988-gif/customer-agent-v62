import os
import secrets

from flask import Flask, jsonify, render_template, request, session

import app as customer_agent


demo_app = Flask(__name__)
demo_app.config.update(
    SECRET_KEY=(
        os.environ.get("DEMO_SESSION_SECRET")
        or secrets.token_hex(32)
    ),
    MAX_CONTENT_LENGTH=32 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        os.environ.get("DEMO_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}
        or os.environ.get("RENDER", "").lower() == "true"
    ),
)


def demo_conversation_id():
    conversation_id = session.get("demo_conversation_id")

    if not conversation_id:
        conversation_id = secrets.token_urlsafe(18)
        session["demo_conversation_id"] = conversation_id

    return f"demo:{conversation_id}"


@demo_app.after_request
def add_security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@demo_app.get("/")
def demo_home():
    language = "en" if request.args.get("lang") == "en" else "ar"
    return render_template(
        "demo.html",
        version=customer_agent.APP_VERSION,
        language=language,
        t=lambda arabic, english: english if language == "en" else arabic,
    )


@demo_app.get("/health")
def demo_health():
    return jsonify(
        {
            "ok": True,
            "service": "customer-agent-v6-demo",
            "version": customer_agent.APP_VERSION,
            "commit": customer_agent.GIT_COMMIT,
            "data_persistence": False,
        }
    )


@demo_app.post("/api/message")
def demo_message():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()

    if not message:
        return jsonify({"ok": False, "error": "اكتب رسالة أولاً."}), 400

    if len(message) > 500:
        return jsonify({"ok": False, "error": "الرسالة طويلة جداً."}), 400

    message_count = int(session.get("demo_message_count", 0))
    if message_count >= 60:
        return jsonify(
            {
                "ok": False,
                "error": "انتهت هذه الجولة التجريبية. اضغط بدء تجربة جديدة.",
            }
        ), 429

    session["demo_message_count"] = message_count + 1

    conversation_id = demo_conversation_id()
    language = payload.get("language")
    if (
        isinstance(language, str)
        and language in {"ar", "en"}
        and customer_agent.session(conversation_id, source="demo")["language"] != language
    ):
        customer_agent.handle_message(
            conversation_id, "English" if language == "en" else "العربية", source="demo"
        )

    reply = customer_agent.handle_message(
        conversation_id,
        message,
        source="demo",
    )

    return jsonify({"ok": True, "reply": reply})


@demo_app.post("/api/reset")
def demo_reset():
    conversation_id = session.get("demo_conversation_id")
    if conversation_id:
        customer_agent.reset(f"demo:{conversation_id}", source="demo")

    session.clear()
    return jsonify({"ok": True})


if __name__ == "__main__":
    demo_app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
