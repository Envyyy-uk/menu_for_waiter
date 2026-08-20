"""Хеширование PIN, токены сессий.

Argon2 для PIN. PIN — слабый фактор по определению (четыре-шесть цифр), и
защищает его ещё блокировка попыток; хеш здесь против утечки таблицы, а не
против перебора.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_secret(raw: str) -> str:
    return _hasher.hash(raw)


def verify_secret(hashed: str | None, raw: str) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, raw)
    except (VerifyMismatchError, VerificationError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_fingerprint(token: str) -> str:
    """Сессионные токены храним хешем: утечка таблицы не даёт входа.
    SHA-256 здесь уместен — токен случайный, словарная атака невозможна."""
    return hashlib.sha256(token.encode()).hexdigest()
