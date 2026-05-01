#!/usr/bin/env python3
from pathlib import Path
import runpy


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[4] / ".agents" / "skills" / "agent-e2e-test" / "scripts" / "e2e_toolbelt.py"
    runpy.run_path(str(target), run_name="__main__")
