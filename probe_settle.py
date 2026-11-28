"""Probe only: the Find tests' settle helper with a long deadline, printing how long Find took."""
import time

import pytest


@pytest.fixture(autouse=True)
def _long_settle(request, monkeypatch):
    mod = request.module
    if hasattr(mod, "settle"):
        from PySide6.QtTest import QTest

        def settle(qapp, pane=None):
            start = time.monotonic()
            deadline = start + 600
            while True:
                qapp.processEvents()
                if pane is None or not pane.find_pending():
                    qapp.processEvents()
                    took = time.monotonic() - start
                    if took > 0.25:
                        print(f"\nSETTLE {took:.2f}s {request.node.name}", flush=True)
                    return
                assert time.monotonic() < deadline, "Find did not settle in 600 seconds"
                QTest.qWait(5)

        monkeypatch.setattr(mod, "settle", settle)
    yield
