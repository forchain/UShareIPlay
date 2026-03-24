"""
Thin shim for running via `python main.py` directly.
Prefer: uv run ushareiplay  (or: python -m ushareiplay)
"""
from ushareiplay.__main__ import run

if __name__ == "__main__":
    run()
