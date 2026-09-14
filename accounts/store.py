from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
import sqlite3
import time

from storage.database import Database
from .security import hash_password, normalize_username, token_hash, verify_password


class InviteError(ValueError):
    """Safe, localizable invite failure; never contains caller input."""


def invite_status(invite, now):
    if invite['max_uses'] is not None and invite['used_count'] >= invite['max_uses']:
        return 'Used'
    if not invite['is_active']:
        return 'Disabled'
    if invite['expires_at'] is not None and invite['expires_at'] <= now:
        return 'Expired'
    return 'Active'


def check_invite(invite, now):
    if invite is None:
        raise InviteError('This invite is not valid.')
    message = {'Used': 'This invite has already been used.',
               'Disabled': 'This invite has been disabled.',
               'Expired': 'This invite has expired.'}.get(invite_status(invite, now))
    if message:
        raise InviteError(message)


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

    def create_invite(self, code, *, max_uses=1, label=None, expiry_days=7):
        if not 24 <= len(code) <= 256:
            raise ValueError("Use a randomly generated invite code with 24-256 characters.")
        if max_uses is not None and max_uses < 1:
            raise ValueError("Maximum uses must be positive.")
        if expiry_days not in (None, 1, 7, 30):
            raise ValueError('Invalid expiry.')
        if label is not None and len(label) > 100:
            raise ValueError('Label is too long.')
        expires_at = None if expiry_days is None else int(time.time()) + expiry_days * 86400
        with self.database.connect(write=True) as db:
            cursor = db.execute("INSERT INTO invites(code_hash,max_uses,created_at,label,expires_at) VALUES (?,?,?,?,?)",
                                (token_hash(code), max_uses, datetime.now(timezone.utc).isoformat(), label, expires_at))
            return cursor.lastrowid

    def invite_error(self, code):
        with self.database.connect() as db:
            invite = db.execute('SELECT * FROM invites WHERE code_hash=?', (token_hash(code),)).fetchone()
            try:
                check_invite(invite, int(time.time()))
            except InviteError as error:
                return str(error)
        return None

    def list_invites(self, *, before=None, limit=50):
        with self.database.connect() as db:
            rows = db.execute('SELECT i.id,i.label,i.created_at,i.expires_at,i.used_count,i.max_uses,'
                              'i.is_active,i.used_at,u.username AS used_by FROM invites i '
                              'LEFT JOIN users u ON u.id=i.used_by_user_id '
                              'WHERE (? IS NULL OR i.id < ?) ORDER BY i.id DESC LIMIT ?',
                              (before, before, limit)).fetchall()
        now = int(time.time())
        return [dict(row, status=invite_status(row, now)) for row in rows]

    def disable_invite(self, invite_id):
        # Activation and revocation take the same write lock. Neither can
        # invalidate a successful registration or erase its history.
        with self.database.connect(write=True) as db:
            return db.execute('UPDATE invites SET is_active=0 WHERE id=? AND used_count=0 AND is_active=1',
                              (invite_id,)).rowcount == 1

    def register(self, username, password, invite_code):
        username = normalize_username(username)
        encoded = hash_password(password)
        # One transaction prevents invite overuse and duplicate registration races.
        try:
            with self.database.connect(write=True) as db:
                invite = db.execute("SELECT * FROM invites WHERE code_hash=?",
                                    (token_hash(invite_code),)).fetchone()
                check_invite(invite, int(time.time()))
                activated_at = datetime.now(timezone.utc).isoformat()
                cursor = db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES (?,?,'user',?)",
                                    (username, encoded, activated_at))
                db.execute("UPDATE invites SET used_count=used_count+1,used_by_user_id=?,used_at=? WHERE id=?",
                           (cursor.lastrowid, activated_at, invite["id"]))
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
