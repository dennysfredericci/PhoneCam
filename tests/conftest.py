import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for `import helpers`


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep certificates, settings and logs out of the real ~/Library/Application Support."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path
