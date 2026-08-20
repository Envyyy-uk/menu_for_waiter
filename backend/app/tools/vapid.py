"""Ключи для Web Push.

Пара ключей заводится один раз на заведение и живёт в `.env`. Сменить их
можно, но тогда все телефоны придётся подписать заново: старые подписки
станут недействительными.

    python -m app.tools.vapid
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid


def _b64(raw: bytes) -> str:
    """base64url без хвостовых знаков «=» — в таком виде ключи ждут и
    браузер, и push-сервисы."""
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def generate() -> tuple[str, str]:
    vapid = Vapid()
    vapid.generate_keys()
    private = _b64(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))
    public = _b64(
        vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    )
    return public, private


def main() -> None:
    public, private = generate()
    print("Скопируйте в .env:\n")
    print("VAPID_PUBLIC_KEY=" + public)
    print("VAPID_PRIVATE_KEY=" + private)


if __name__ == "__main__":
    main()
