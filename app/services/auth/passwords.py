from __future__ import annotations

import hashlib
import hmac
import secrets

__all__ = ["MIN_PASSWORD_LENGTH", "PasswordError", "hash_password", "validate_password", "verify_password"]

MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 128
_ALGORITHM = "scrypt"
_COST_N = 2**14
_BLOCK_SIZE = 8
_PARALLELISM = 1
_KEY_LENGTH = 32


class PasswordError(ValueError):
    """Пароль не проходит минимальные требования."""


def validate_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов.")
    if len(password) > _MAX_PASSWORD_LENGTH:
        raise PasswordError(f"Пароль должен быть не длиннее {_MAX_PASSWORD_LENGTH} символов.")
    return password


def hash_password(password: str) -> str:
    """Склеенный scrypt-дайджест: параметры стоимости записаны в нём самом, их можно поднять."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        validate_password(password).encode("utf-8"),
        salt=salt,
        n=_COST_N,
        r=_BLOCK_SIZE,
        p=_PARALLELISM,
        dklen=_KEY_LENGTH,
    )
    return f"{_ALGORITHM}${_COST_N}${_BLOCK_SIZE}${_PARALLELISM}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Сравнение пароля с дайджестом за постоянное время."""
    if not stored:
        return False
    try:
        algorithm, cost_n, block_size, parallelism, salt_hex, digest_hex = stored.split("$")
        if algorithm != _ALGORITHM:
            return False
        expected = bytes.fromhex(digest_hex)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(cost_n),
            r=int(block_size),
            p=int(parallelism),
            dklen=len(expected),
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest, expected)
