"""Where saved files live: a folder on disk (PIANO_STORAGE_DIR), one file per item.

Names are built only from ids the server made (never from anything the person typed), and every
path is checked to stay inside the folder. Writes go to a temporary file first and are renamed, so
a crash never leaves half a file.
"""

import os
import re
import uuid
from pathlib import Path

from app.core.config import get_settings

_SAFE = re.compile(r"^[0-9a-f-]{36}/[0-9a-f-]{36}$")


class FileStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    @staticmethod
    def key(user_id: uuid.UUID, item_id: uuid.UUID) -> str:
        return f"{user_id}/{item_id}"

    def _path(self, key: str) -> Path:
        if not _SAFE.match(key):
            raise ValueError("bad storage key")
        path = (self._root / "library" / key).resolve()
        if self._root not in path.parents:
            raise ValueError("bad storage key")
        return path

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def read(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    def keys(self) -> list[str]:
        """Every stored key (`user id/item id`). Used only by the cleanup script."""
        base = self._root / "library"
        if not base.is_dir():
            return []
        return sorted(
            f"{u.name}/{f.name}"
            for u in base.iterdir()
            if u.is_dir()
            for f in u.iterdir()
            if f.is_file() and _SAFE.match(f"{u.name}/{f.name}")
        )

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def get_file_store() -> FileStore:
    return FileStore(get_settings().storage_dir)
