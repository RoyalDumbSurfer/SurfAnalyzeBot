"""Additive invite metadata. Run explicitly before upgrading an existing web app."""
from storage.database import Database


def migrate(database):
    with database.connect(write=True) as db:
        version = db.execute("SELECT value FROM metadata WHERE key='invite_schema_version'").fetchone()
        if version and version[0] != '1':
            raise RuntimeError('Unsupported invite schema version')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(invites)')}
        for name, definition in (
            ('expires_at', 'INTEGER'),
            ('used_by_user_id', 'INTEGER REFERENCES users(id)'),
            ('used_at', 'TEXT'),
        ):
            if name not in columns:
                db.execute(f'ALTER TABLE invites ADD COLUMN {name} {definition}')
        # Existing invites keep their expiry and usage semantics. Historical
        # activators cannot be inferred; NULL means not recorded before migration.
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('invite_schema_version','1')")
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key integrity check failed')


if __name__ == '__main__':
    from config import settings
    migrate(Database(settings.DATABASE_PATH, initialize=False))
    print('Invite schema ready.')
