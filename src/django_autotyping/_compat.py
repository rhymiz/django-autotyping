import sys

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
    from typing import override
else:
    from typing_extensions import override  # noqa: F401
