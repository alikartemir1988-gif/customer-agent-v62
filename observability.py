"""Privacy-safe, fail-open Langfuse observability for customer messages."""

import hashlib
import hmac
import logging
import os
from contextlib import contextmanager


LOGGER = logging.getLogger(__name__)
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_REQUIRED_ENV = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)

_langfuse_client = None
_langfuse_unavailable = False


def _flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def langfuse_is_configured():
    return all(
        os.environ.get(name, "").strip()
        for name in _REQUIRED_ENV
    )


def content_capture_enabled():
    return _flag("LANGFUSE_CAPTURE_CONTENT", False)


def _content_payload(value, field_name):
    text = str(value or "")
    if content_capture_enabled():
        return {field_name: text[:4000]}
    return {
        "content_redacted": True,
        "character_count": len(text),
    }


def _anonymous_session_id(chat_id, source):
    secret = os.environ.get(
        "LANGFUSE_SECRET_KEY",
        "local-observability-fallback",
    )
    message = f"{source or 'unknown'}:{chat_id}".encode("utf-8")
    digest = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return digest[:24]


def _get_langfuse_client():
    global _langfuse_client
    global _langfuse_unavailable

    if not langfuse_is_configured() or _langfuse_unavailable:
        return None

    if _langfuse_client is not None:
        return _langfuse_client

    try:
        from langfuse import get_client

        _langfuse_client = get_client()
    except Exception as exc:
        _langfuse_unavailable = True
        LOGGER.warning(
            "Langfuse tracing unavailable during initialization (%s)",
            type(exc).__name__,
        )
        return None

    return _langfuse_client


def _close_context_safely(manager, exc_info):
    if manager is None:
        return

    try:
        manager.__exit__(*exc_info)
    except Exception as exc:
        LOGGER.warning(
            "Langfuse tracing context could not close (%s)",
            type(exc).__name__,
        )


@contextmanager
def customer_message_span(
    chat_id,
    text,
    source,
    version="",
):
    """Yield a Langfuse span or None without risking the customer reply."""

    client = _get_langfuse_client()
    if client is None:
        yield None
        return

    span_manager = None
    attribute_manager = None

    try:
        from langfuse import propagate_attributes

        span_manager = client.start_as_current_observation(
            name="customer-message",
            as_type="span",
            input=_content_payload(text, "message"),
            metadata={
                "source": str(source or "unknown")[:80],
                "content_capture": content_capture_enabled(),
            },
            version=str(version or "")[:80] or None,
        )
        span = span_manager.__enter__()

        attribute_manager = propagate_attributes(
            session_id=_anonymous_session_id(chat_id, source),
            trace_name="customer-message",
            tags=[
                "customer-agent-v62",
                f"channel:{str(source or 'unknown')[:60]}",
            ],
            version=str(version or "")[:80] or None,
            metadata={
                "source": str(source or "unknown")[:80],
            },
        )
        attribute_manager.__enter__()
    except Exception as exc:
        _close_context_safely(
            attribute_manager,
            (None, None, None),
        )
        _close_context_safely(
            span_manager,
            (None, None, None),
        )
        LOGGER.warning(
            "Langfuse tracing skipped for this message (%s)",
            type(exc).__name__,
        )
        yield None
        return

    try:
        yield span
    except BaseException as exc:
        exc_info = (
            type(exc),
            exc,
            exc.__traceback__,
        )
        _close_context_safely(
            attribute_manager,
            exc_info,
        )
        _close_context_safely(
            span_manager,
            exc_info,
        )
        raise
    else:
        _close_context_safely(
            attribute_manager,
            (None, None, None),
        )
        _close_context_safely(
            span_manager,
            (None, None, None),
        )


def finish_customer_message(span, response_text, state=None):
    """Attach privacy-safe result metadata to a message span."""

    if span is None:
        return

    state = state or {}
    metadata = {
        "response_character_count": len(str(response_text or "")),
        "buying": bool(state.get("buying")),
        "awaiting_confirmation": bool(
            state.get("awaiting_confirmation")
        ),
        "done": bool(state.get("done")),
        "order_created": bool(state.get("order_id")),
    }

    try:
        span.update(
            output=_content_payload(
                response_text,
                "reply",
            ),
            metadata=metadata,
        )
    except Exception as exc:
        LOGGER.warning(
            "Langfuse trace update skipped (%s)",
            type(exc).__name__,
        )


def verify_langfuse_connection():
    """Strict CI-only credential check followed by one synthetic trace."""

    if not langfuse_is_configured():
        raise RuntimeError(
            "Langfuse connection values are incomplete"
        )

    client = _get_langfuse_client()
    if client is None:
        raise RuntimeError(
            "Langfuse client could not initialize"
        )

    if client.auth_check() is not True:
        raise RuntimeError(
            "Langfuse credentials were rejected"
        )

    with client.start_as_current_observation(
        name="customer-agent-connection-check",
        as_type="span",
        input={
            "synthetic": True,
            "message": "safe-ci-connection-check",
        },
        metadata={
            "synthetic": True,
            "contains_customer_data": False,
        },
        version="6.3.2",
    ) as span:
        span.update(
            output={
                "status": "connected",
                "synthetic": True,
            }
        )

    client.flush()
    return True
