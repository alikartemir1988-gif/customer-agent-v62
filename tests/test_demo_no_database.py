"""Fresh-process checks for demo isolation and production persistence."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DatabaseIsolationTests(unittest.TestCase):
    def run_isolated(self, script, database_url=""):
        with tempfile.TemporaryDirectory() as directory:
            env = {
                key: value for key, value in os.environ.items()
                if not key.startswith(("LANGFUSE_", "TELEGRAM_", "GEMINI_"))
                and key not in {"DATABASE_URL", "DB_PATH", "WEBHOOK_URL", "WEBHOOK_SECRET"}
            }
            env.update(DATABASE_URL=database_url, DB_PATH=str(Path(directory) / "agent.db"))
            result = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(script)],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_demo_boot_conversations_and_resets_never_connect_to_database(self):
        for database_url in ("", "postgresql://unused:unused@127.0.0.1:1/unavailable"):
            with self.subTest(database_url=database_url):
                self.run_isolated('''
                    import os
                    from pathlib import Path
                    import runpy
                    from unittest.mock import Mock, patch

                    forbidden = AssertionError("demo attempted database access")
                    with (
                        patch("sqlite3.connect", side_effect=forbidden) as sqlite,
                        patch("psycopg.connect", side_effect=forbidden) as postgres,
                    ):
                        import app as agent
                        from demo_app import demo_app

                        hook = runpy.run_path("gunicorn.conf.py")["post_worker_init"]
                        hook(Mock())
                        demo_app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
                        with (
                            patch.object(agent, "init_db", side_effect=forbidden),
                            patch.object(agent, "load_session", side_effect=forbidden),
                            patch.object(agent, "save_session", side_effect=forbidden),
                            patch.object(agent, "delete_session", side_effect=forbidden),
                            patch.object(agent, "create_order", side_effect=forbidden),
                        ):
                            for language, order, faq, human, back, confirm, cancel in (
                                ("ar", ("بدي جهازين لون أبيض", "أحمد خالد", "0933123456", "دمشق"),
                                 "في ضمان؟", "بدي موظف", "ارجع للبوت", "تأكيد", "إلغاء الطلب"),
                                ("en", ("I want 2 white devices", "John Smith", "+447700900123", "Damascus"),
                                 "Is there a warranty?", "talk to a human", "back to bot", "confirm", "cancel order"),
                            ):
                                client = demo_app.test_client()
                                assert client.get("/?lang=" + language).status_code == 200
                                health = client.get("/health")
                                assert health.status_code == 200
                                assert health.get_json()["data_persistence"] is False
                                assert client.post("/api/reset").status_code == 200
                                # The API also creates a memory-only session without language metadata.
                                first = client.post("/api/message", json={"message": order[0]})
                                assert first.status_code == 200
                                assert client.post("/api/reset").status_code == 200

                                def send(text):
                                    response = client.post("/api/message", json={"message": text, "language": language})
                                    assert response.status_code == 200, response.get_data(as_text=True)
                                    return response.get_json()["reply"]

                                assert ("Source:" if language == "en" else "المصدر:") in send(faq)
                                send("Does it sing?" if language == "en" else "هل يغني؟")
                                for text in order:
                                    send(text)
                                assert ("simulated" if language == "en" else "لا يُحفظ") in send(human)
                                send("Additional details" if language == "en" else "تفاصيل إضافية")
                                send(back)
                                assert "DEMO-" in send(confirm)
                                assert "DEMO-" in send(confirm)
                                send(order[0])  # A second order resets the completed session.
                                send(cancel)
                                send(order[0])
                                with client.session_transaction() as cookie:
                                    old_id = "demo:" + cookie["demo_conversation_id"]
                                agent.SESSIONS.clear()  # Reset must also work after memory loss.
                                assert client.post("/api/reset").status_code == 200
                                send(order[0])
                                with client.session_transaction() as cookie:
                                    new_id = "demo:" + cookie["demo_conversation_id"]
                                assert new_id != old_id
                                assert agent.SESSIONS[new_id]["name"] is None
                                assert agent.SESSIONS[new_id]["source"] == "demo"
                                assert client.post("/api/reset").status_code == 200
                                assert new_id not in agent.SESSIONS

                        sqlite.assert_not_called()
                        postgres.assert_not_called()
                        assert not Path(os.environ["DB_PATH"]).exists()
                ''', database_url)

    def test_production_worker_keeps_durable_orders_sessions_and_reset(self):
        self.run_isolated('''
            import os
            from pathlib import Path
            import runpy
            import sqlite3
            from unittest.mock import Mock

            import app as agent

            hook = runpy.run_path("gunicorn.conf.py")["post_worker_init"]
            hook(Mock())
            assert Path(os.environ["DB_PATH"]).exists()
            for text in ("بدي جهازين لون أبيض", "أحمد خالد", "0933123456", "دمشق"):
                agent.handle_message("production-customer", text, source="telegram")
            before = dict(agent.session("production-customer"))
            assert before["awaiting_confirmation"]
            agent.SESSIONS.clear()
            assert agent.session("production-customer") == before
            agent.handle_message("production-customer", "تأكيد", source="telegram")
            agent.SESSIONS.clear()
            assert agent.session("production-customer")["done"]
            agent.handle_message("production-customer", "تأكيد", source="telegram")
            with sqlite3.connect(agent.DB_PATH) as conn:
                assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
                assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
            agent.reset("production-customer")
            with sqlite3.connect(agent.DB_PATH) as conn:
                assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
                assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        ''')


if __name__ == "__main__":
    unittest.main()
