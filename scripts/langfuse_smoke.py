"""Submit one synthetic trace to verify the Langfuse connection."""

import pathlib
import sys


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from observability import verify_langfuse_connection


def main():
    try:
        verify_langfuse_connection()
    except Exception as exc:
        print(
            "Langfuse connection check failed: "
            f"{type(exc).__name__}",
            file=sys.stderr,
        )
        return 1

    print(
        "Langfuse credentials verified and synthetic trace submitted."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
