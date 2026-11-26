import hashlib
import hmac

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


PASSWORD_ITERATIONS = 310_000
PASSWORD_HASHER = PasswordHasher()


def hash_password(password):
    return PASSWORD_HASHER.hash(password)


def verify_password(password, encoded_hash):
    if not isinstance(encoded_hash, str):
        return False
    if encoded_hash.startswith("pbkdf2_sha256$"):
        return verify_legacy_password(password, encoded_hash)
    try:
        return PASSWORD_HASHER.verify(encoded_hash, password)
    except (InvalidHashError, VerificationError, TypeError):
        return False


def verify_legacy_password(password, encoded_hash):
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
        supplied = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return hmac.compare_digest(supplied, expected)


def password_needs_rehash(encoded_hash):
    if not isinstance(encoded_hash, str) or encoded_hash.startswith("pbkdf2_sha256$"):
        return True
    try:
        return PASSWORD_HASHER.check_needs_rehash(encoded_hash)
    except (InvalidHashError, TypeError):
        return True
