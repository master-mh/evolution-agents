import sqlite3

import pytest

from mitosis import db


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = db.connect_and_migrate()
    yield connection
    connection.close()
