"""Retired local-ledger regression tests are replaced by live-state tests."""

def test_runtime_has_no_paper_ledger_module():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    assert not (src / "engine" / "paper_ledger.py").exists()
