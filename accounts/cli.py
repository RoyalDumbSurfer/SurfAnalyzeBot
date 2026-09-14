"""Run with python -m accounts.cli. Secrets are read only through hidden prompts."""
import argparse
import getpass
import sqlite3
import warnings

from config import settings
from .migration import import_legacy
from .store import AccountStore


def read_secret(prompt):
    # Refuse getpass's echoing fallback when no suitable terminal is available.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def main():
    parser = argparse.ArgumentParser(description="SurfAnalyze account administration")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin")
    admin.add_argument("--username", required=True)
    invite = commands.add_parser("create-invite")
    invite.add_argument("--max-uses", type=int, default=1)
    invite.add_argument("--unlimited", action="store_true")
    invite.add_argument("--label")
    invite.add_argument("--expiry-days", type=int, choices=(1, 7, 30), default=7)
    invite.add_argument("--no-expiry", action="store_true")
    disable = commands.add_parser("disable-invite")
    disable.add_argument("--id", type=int, required=True)
    migrate = commands.add_parser("import-legacy")
    migrate.add_argument("--source", default="jobs_db.json")
    migrate.add_argument("--owner", required=True)
    migrate.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        store = AccountStore(settings.DATABASE_PATH, initialize=args.command == "create-admin")
        if args.command == "create-admin":
            password = read_secret("Admin password (15-128 characters): ")
            if password != read_secret("Confirm password: "):
                raise ValueError("Passwords do not match.")
            user = store.create_admin(args.username, password)
            print(f"Admin created: ID {user.id}")
        elif args.command == "create-invite":
            code = read_secret("Paste a random invite code (24-256 characters; hidden): ")
            if code != read_secret("Confirm invite code: "):
                raise ValueError("Invite codes do not match.")
            invite_id = store.create_invite(code, max_uses=None if args.unlimited else args.max_uses, label=args.label,
                                           expiry_days=None if args.no_expiry else args.expiry_days)
            print(f"Invite created: ID {invite_id}. The code is not displayed or recoverable.")
        elif args.command == "disable-invite":
            with store.database.connect(write=True) as db:
                cursor = db.execute("UPDATE invites SET is_active=0 WHERE id=?", (args.id,))
                print(f"Invites disabled: {cursor.rowcount}")
        else:
            result = import_legacy(settings.DATABASE_PATH, args.source, args.owner, apply=args.apply)
            print(f"Jobs: {result['jobs']}; applied: {result['applied']}; already imported: {result['already_imported']}")
    except (ValueError, KeyError, TypeError, RuntimeError, OSError, sqlite3.Error, getpass.GetPassWarning, EOFError):
        # Never echo sqlite values, password hashes, paths, or malformed source content.
        parser.exit(1, "Operation failed. Check inputs, permissions, and the migration instructions. No secrets were printed.\n")


if __name__ == "__main__":
    main()
