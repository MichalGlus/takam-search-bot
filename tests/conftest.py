from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from takam_search.config import PROJECT_ROOT, Settings
from takam_search.ingest import build
from takam_search.retriever import Retriever

RAW = PROJECT_ROOT / "data" / "raw"
TODAY = date(2026, 11, 23)  # fixed "today" so validity tests do not drift


def make_settings(data_dir: Path, **overrides) -> Settings:
    # _env_file=None: tests must not depend on the developer's .env (or its API key).
    values = {"llm_enabled": False, **overrides}
    return Settings(_env_file=None, data_dir=data_dir, **values)


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    """A private copy of the committed sample, with an index built from it."""
    d = tmp_path_factory.mktemp("data")
    shutil.copytree(RAW, d / "raw")
    shutil.copy(PROJECT_ROOT / "data" / "eval.jsonl", d / "eval.jsonl")
    build(make_settings(d))
    return d


@pytest.fixture(scope="session")
def settings(data_dir) -> Settings:
    return make_settings(data_dir)


@pytest.fixture(scope="session")
def retriever(settings) -> Retriever:
    return Retriever(settings.db_path, today=lambda: TODAY)


@pytest.fixture
def docx_path() -> callable:
    def _path(code: str) -> Path:
        return RAW / "docs" / f"{code}.docx"
    return _path
