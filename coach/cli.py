"""Maintenance-only CLI; OS access to the private database is required."""
import argparse
import json
import os
from pathlib import Path
import sqlite3

from config import settings
from storage.database import Database
from coach.migration import migrate
from coach.store import export_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default=settings.DATABASE_PATH)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('migrate')
    export = commands.add_parser('export-coach-dataset')
    export.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        database = Database(args.database, initialize=False)
        if args.command == 'migrate':
            migrate(database)
            print('Coach schema version 1 ready.')
        else:
            # Exclusive creation: never overwrite a database, backup, or export.
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as output:
                    for record in export_records(database):
                        output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
            except Exception:
                args.output.unlink(missing_ok=True)
                raise
            print('Coach dataset exported. Treat it as private training data.')
    except (OSError, sqlite3.Error, RuntimeError, ValueError):
        parser.exit(1, 'Operation failed. Check migration, permissions and output path. No private data printed.\n')


if __name__ == '__main__':
    main()
