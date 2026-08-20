"""Дочекатись Postgres перед міграціями. Compose-healthcheck ловить не все:
база вже приймає з'єднання, але може ще перезапускати ініціалізацію."""

import sys
import time

from sqlalchemy import text

from app.db import engine

DEADLINE_SECONDS = 60


def main() -> int:
    started = time.monotonic()
    while time.monotonic() - started < DEADLINE_SECONDS:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("db: ready")
            return 0
        except Exception as exc:  # noqa: BLE001 — тут важливий сам факт недоступності
            print(f"db: waiting ({exc.__class__.__name__})")
            time.sleep(1)
    print("db: not reachable, giving up", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
