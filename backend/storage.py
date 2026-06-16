import logging
import os
import secrets
import shutil
from typing import Protocol


logger = logging.getLogger(__name__)


class Storage(Protocol):
    root_dir: str
    url_prefix: str

    def save(self, src_path: str, suffix: str) -> str: ...
    def delete(self, rel_path: str) -> None: ...
    def open_path(self, rel_path: str) -> str: ...
    def url_for(self, rel_path: str) -> str: ...


class LocalStorage:
    def __init__(self, root_dir: str, url_prefix: str = '/uploads'):
        self.root_dir = os.path.abspath(root_dir)
        self.url_prefix = url_prefix.rstrip('/')
        os.makedirs(self.root_dir, exist_ok=True)

    def _new_rel_path(self, suffix: str) -> str:
        token = secrets.token_hex(16)
        return os.path.join(token[:2], f'{token}{suffix}')

    def save(self, src_path: str, suffix: str) -> str:
        rel_path = self._new_rel_path(suffix)
        abs_path = os.path.join(self.root_dir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        shutil.move(src_path, abs_path)
        return rel_path

    def delete(self, rel_path: str) -> None:
        if not rel_path:
            return
        abs_path = os.path.join(self.root_dir, rel_path)
        try:
            os.remove(abs_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning('failed to delete upload %s: %s', rel_path, exc)
            return
        # Best-effort prune empty parent directory
        try:
            os.rmdir(os.path.dirname(abs_path))
        except OSError:
            pass

    def open_path(self, rel_path: str) -> str:
        return os.path.join(self.root_dir, rel_path)

    def url_for(self, rel_path: str) -> str:
        return f"{self.url_prefix}/{rel_path.replace(os.sep, '/')}"


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        from db import DB_DIR
        _storage = LocalStorage(os.path.join(DB_DIR, 'uploads'))
    return _storage
