"""Regression tests proving the service boots without the retired ledger."""
import ast
from pathlib import Path

from fastapi.testclient import TestClient

from src.api import app


ROOT = Path(__file__).resolve().parents[1]


def test_no_src_module_imports_paper_ledger():
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "paper_ledger" not in (node.module or ""), path
            elif isinstance(node, ast.Import):
                assert all("paper_ledger" not in name.name for name in node.names), path


def test_health_boots_without_a_database_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "ibkr-paper"}
    assert list(tmp_path.rglob("*.db")) == []
    assert list(tmp_path.rglob("paper.db")) == []
