"""Find saved files that no longer belong to anything, and optionally delete them.

    cd backend
    python -m scripts.cleanup_storage            # report only
    python -m scripts.cleanup_storage --delete   # remove the stray files

A stray file is one in the storage folder with no library item pointing at it. They are harmless
(a few KB) and only appear if the server stopped between deleting a database row and its file.
The reverse is reported too: library items whose file is missing (a restore from an older backup
of the files is the usual cause). Those are never deleted automatically.
"""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models.library import LibraryItem
from app.services.file_store import FileStore, get_file_store


def scan(session: Session, store: FileStore) -> tuple[list[str], list[str]]:
    """(stray file keys, ids of items whose file is missing)."""
    wanted: dict[str, str] = {}
    for item in session.scalars(select(LibraryItem).where(LibraryItem.file_size > 0)):
        wanted[store.key(item.user_id, item.id)] = str(item.id)
    on_disk = set(store.keys())
    stray = sorted(on_disk - set(wanted))
    missing = sorted(wanted[k] for k in set(wanted) - on_disk)
    return stray, missing


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--delete", action="store_true", help="remove the stray files")
    args = parser.parse_args(argv)
    store = get_file_store()
    session = next(get_session())
    try:
        stray, missing = scan(session, store)
    finally:
        session.close()
    print(f"stray files: {len(stray)}")
    for key in stray:
        print(f"  {key}")
        if args.delete:
            store.delete(key)
    if args.delete and stray:
        print("deleted.")
    print(f"items with a missing file: {len(missing)}")
    for item_id in missing:
        print(f"  {item_id}")


if __name__ == "__main__":
    main()
