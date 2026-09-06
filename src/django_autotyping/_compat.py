import sys
from pathlib import Path

try:
    from django.contrib.postgres import fields as _postgres_fields
except ModuleNotFoundError as exc:
    # PostgreSQL's fields import a database driver. SQLite/MySQL projects do
    # not need one merely to generate stubs; other import errors must surface.
    if exc.name not in {"psycopg", "psycopg2"}:
        raise
    postgres_fields = None
else:
    postgres_fields = _postgres_fields

if sys.version_info >= (3, 12):
    from typing import NotRequired, Required, Self, TypeAlias, TypeGuard, Unpack, override
else:
    from typing_extensions import NotRequired, Required, Self, TypeAlias, TypeGuard, Unpack, override  # noqa: F401

if sys.version_info >= (3, 10):
    from types import NoneType
else:
    NoneType = type(None)


def is_relative_to(path: Path, other: Path) -> bool:
    if sys.version_info >= (3, 9):
        return path.is_relative_to(other)
    else:
        try:
            path.relative_to(other)
            return True
        except ValueError:
            return False
