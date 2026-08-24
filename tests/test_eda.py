"""Chapter 2: eda.py must run against output/filings/ and state its findings."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_eda_runs_and_states_findings():
    result = subprocess.run(
        [sys.executable, str(ROOT / "submission" / "eda.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "files: 40" in out
    assert "FINDINGS" in out
    assert "13F-NT" in out
    assert "Pershing" in out
    assert "CINS" in out
    assert "accession_number" in out
    assert "filing_date" in out
    assert "otherManagers2Info" in out
    assert "do not deduplicate" in out.lower() or "Duplicate CUSIPs" in out
    assert "thirteenffiler" in out
    # Empty notice totals are a parser trap; the script must distinguish them.
    assert "present+empty" in out
