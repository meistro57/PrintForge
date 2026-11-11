from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def minimal_book() -> Path:
    return FIXTURES / "minimal-book"


@pytest.fixture
def print_book() -> Path:
    return FIXTURES / "print-book"


@pytest.fixture
def bookforge_root() -> Path:
    return FIXTURES / "bookforge-root"
