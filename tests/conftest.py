"""Shared pytest fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skein.app import create_app
from skein.config import Config
from skein.db import open_db


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "traces"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
def db(tmp_path):
    """Fresh on-disk SQLite per test (in tmp dir)."""
    return open_db(tmp_path / "test.db")


@pytest.fixture
def app(tmp_path, db):
    cfg = Config(db_path=str(tmp_path / "test.db"))
    app = create_app(cfg, db_conn=db)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()
