from __future__ import annotations

import runpy
import sys
from pathlib import Path


def test_config_surface_script_passes() -> None:
    project_root = Path(__file__).resolve().parents[3]
    script_path = project_root / "backend/scripts/check_config_surface.py"
    previous_argv = sys.argv[:]
    try:
        sys.argv = [str(script_path)]
        namespace = runpy.run_path(str(script_path), run_name="config_surface_check")
        assert "main" in namespace
        assert namespace["main"]() == 0
    finally:
        sys.argv = previous_argv
