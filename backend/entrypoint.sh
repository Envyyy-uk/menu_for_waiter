#!/bin/sh
# Один вход для контейнера: дождаться базы, накатить миграции, залить сидер,
# поднять сервер. Порядок важен — сидер работает по уже мигрированной схеме.
set -e

python -m app.wait_for_db
alembic upgrade head
python -m app.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
