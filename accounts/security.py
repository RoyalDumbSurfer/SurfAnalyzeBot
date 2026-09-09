import hashlib
import hmac
import re
import secrets
import threading


# Bound concurrent memory-heavy hashes in each web process.
_hash_slots = threading.BoundedSemaphore(2)


def normalize_username(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", value):
        raise ValueError("Use 3-40 letters, numbers, dots, hyphens, or underscores for your username.")
    return value


def validate_password(value):
    if not 15 <= len(value) <= 128:
        raise ValueError("Use a password with 15-128 characters.")


def _derive(password, salt):
    with _hash_slots:
        return hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1,
                              maxmem=256 * 1024 * 1024, dklen=32)


def hash_password(password):
    validate_password(password)
    salt = secrets.token_bytes(16)
    return "scrypt$131072$8$1$" + salt.hex() + "$" + _derive(password, salt).hex()


def verify_password(password, encoded):
    if len(password) > 128:
        return False
    # Unknown users still incur the same password hashing work.
    salt, expected = bytes(16), bytes(32)
    if encoded:
        try:
            algorithm, n, r, p, salt_hex, digest = encoded.split("$")
            if (algorithm, n, r, p) != ("scrypt", "131072", "8", "1"):
                return False
            salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(_derive(password, salt), expected) and bool(encoded)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()
