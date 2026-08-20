from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# /srv/backend/app/core/config.py → /srv
ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pos:pos@localhost:5432/pos"

    secret_key: str = "dev-secret-change-me-in-production"

    # Первый администратор и стартовые столы. PIN печатается в лог один раз.
    seed_admin_name: str = "Администратор"
    seed_admin_pin: str = "1234"
    seed_tables: int = 12

    public_base_url: str = "http://localhost:8000"

    # Сессии. Смена длиннее таймера, поэтому сессия продлевается при
    # активности, а не рвётся посреди заказа.
    staff_session_minutes: int = 720
    manager_session_minutes: int = 720

    pin_max_attempts: int = 5
    pin_lockout_minutes: int = 15

    # Web Push. Пустые ключи = push выключен.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # Сколько секунд станция может не принимать марку, прежде чем это станет
    # видно как просрочка.
    late_ticket_seconds: int = 120

    @property
    def frontend_dir(self) -> Path:
        return ROOT / "frontend"

    @property
    def seed_file(self) -> Path:
        return ROOT / "seed_menu.json"

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
