# Customer Agent V6.2 — Deploy

Files:
- app.py
- requirements.txt

Required environment variable:
- TELEGRAM_BOT_TOKEN = your NEW Telegram token (never put it in app.py)

Start command:
python app.py

Important:
This package uses SQLite for orders and in-memory conversation sessions.
For a first demo it is fine. For a production customer, use persistent storage
and preferably PostgreSQL/Redis before promising durable 24/7 operation.
