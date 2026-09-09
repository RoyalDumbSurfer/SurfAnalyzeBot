from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
import sqlite3
import time

from storage.database import Database
from .security import hash_password, normalize_username, token_hash, verify_password


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str
    created_at: str
    is_active: bool


def user_from_row(row):
    return User(row["id"], row["username"], row["role"], row["created_at"], bool(row["is_active"])) if row else None


class AccountStore:
    def __init__(self, path, *, initialize=True):
        self.database = Database(path, initialize=initialize)

    def create_admin(self, username, password):
        username = normalize_username(username)
        encoded = hash_password(password)
        with self.database.connect(write=True) as db:
            if db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
                raise ValueError("An admin already exists. Bootstrap is only for the first admin.")
            db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES (?,?,'admin',?)",
                       (username, encoded, datetime.now(timezone.utc).isoformat()))
            return user_from_row(db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone())

    def create_invite(self, code, *, max_uses=1, label=None):
        if not 24 <= len(code) <= 256:
            raise ValueError("Use a randomly generated invite code with 24-256 characters.")
        if max_uses is not None and max_uses < 1:
            raise ValueError("Maximum uses must be positive.")
        with self.database.connect(write=True) as db:
            cursor = db.execute("INSERT INTO invites(code_hash,max_uses,created_at,label) VALUES (?,?,?,?)",
                                (token_hash(code), max_uses, datetime.now(timezone.utc).isoformat(), label))
            return cursor.lastrowid

    def register(self, username, password, invite_code):
        username = normalize_username(username)
        encoded = hash_password(password)
        # One transaction prevents invite overuse and duplicate registration races.
        try:
            with self.database.connect(write=True) as db:
                invite = db.execute("SELECT * FROM invites WHERE code_hash=? AND is_active=1 "
                                    "AND (max_uses IS NULL OR used_count < max_uses)",
                                    (token_hash(invite_code),)).fetchone()
                if invite is None:
                    raise ValueError("Unable to register. Check your invite code and username.")
                cursor = db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES (?,?,'user',?)",
                                    (username, encoded, datetime.now(timezone.utc).isoformat()))
                db.execute("UPDATE invites SET used_count=used_count+1 WHERE id=?", (invite["id"],))
                return user_from_row(db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())
        except sqlite3.IntegrityError:
            raise ValueError("Unable to register. Check your invite code and username.") from None

    def authenticate(self, username, password):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
        valid = verify_password(password, row["password_hash"] if row else None)
        return user_from_row(row) if valid and row["is_active"] else None

    def new_session(self, user_id):
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.database.connect(write=True) as db:
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (token_hash(token), user_id, now + 7 * 86400))
        return token

    def session_user(self, token):
        if not isinstance(token, str) or len(token) > 128:
            return None
        with self.database.connect() as db:
            row = db.execute("SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id "
                             "WHERE token_hash=? AND expires_at>? AND is_active=1",
                             (token_hash(token), int(time.time()))).fetchone()
        return user_from_row(row)

    def revoke_session(self, token):
        if isinstance(token, str):
            with self.database.connect(write=True) as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))

    def allow_attempt(self, address, username):
        """Persistent limits shared across local web processes; no raw addresses/usernames."""
        now = int(time.time())
        buckets = [(token_hash("ip:" + address), 30), (token_hash("name:" + username.strip().lower()), 10)]
        with self.database.connect(write=True) as db:
            db.execute("DELETE FROM auth_attempts WHERE expires_at<=?", (now,))
            for key, limit in buckets:
                row = db.execute("SELECT count FROM auth_attempts WHERE bucket=?", (key,)).fetchone()
                if row and row["count"] >= limit:
                    return False
            for key, _ in buckets:
                db.execute("INSERT INTO auth_attempts VALUES (?,1,?) ON CONFLICT(bucket) "
                           "DO UPDATE SET count=count+1", (key, now + 900))
        return True
