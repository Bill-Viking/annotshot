"""The frozen app's entry point (PyInstaller): the same as `python -m annotshot`,
including --check and --version."""
import sys

from annotshot.__main__ import run

raise SystemExit(run(sys.argv[1:]))
