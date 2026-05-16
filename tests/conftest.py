from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from radaragent.storage.db import Database


@pytest.fixture
def db(tmp_path) -> Iterator[Database]:
    database = Database(tmp_path / "test.db")
    database.init_schema()
    yield database
    database.close()


@pytest.fixture
def raw_conn(db: Database) -> sqlite3.Connection:
    return db.connection
