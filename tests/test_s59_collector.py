"""Cycle collection belongs to the application's thread."""
import gc
import threading

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest

from annotshot import app as app_setup


def test_t1_worker_allocations_leave_cycle_for_window_thread(qapp):
    app_setup.collect_on_this_thread(qapp)
    main_ident = threading.get_ident()
    collected, worker_ident, dictionaries = [], [], []

    class Cycle:
        def __del__(self):
            collected.append(threading.get_ident())

    def allocate():
        worker_ident.append(threading.get_ident())
        # Keep the allocations alive through the timer's threshold check.
        dictionaries.extend({} for _ in range(200_000))
        assert len(dictionaries) == 200_000

    worker = threading.Thread(target=allocate)
    gc.collect()  # Reset counts before creating the cycle, on this thread.
    cycle = Cycle()
    cycle.self = cycle
    del cycle
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert collected == [], f"collected={collected}, worker_ident={worker_ident}"
    QTest.qWait(1200)
    assert collected == [main_ident]


def test_t2_make_app_reuses_one_collector(qapp):
    assert app_setup.make_app([]) is qapp
    assert app_setup.make_app([]) is qapp
    timers = qapp.findChildren(QTimer, "annotshotCollector")
    assert len(timers) == 1
    assert timers[0].parent() is qapp
    assert timers[0].thread() == qapp.thread()
    assert timers[0].isActive() and timers[0].interval() == 1000
    assert gc.isenabled() is False


def test_t3_under_threshold_collects_nothing(qapp, monkeypatch):
    app_setup.collect_on_this_thread(qapp)
    timer = qapp.findChild(QTimer, "annotshotCollector")
    collected = []
    monkeypatch.setattr(gc, "get_threshold", lambda: (700, 10, 10))
    monkeypatch.setattr(gc, "collect", lambda generation: collected.append(generation))
    for count in ((699, 11, 11), (700, 11, 11)):
        monkeypatch.setattr(gc, "get_count", lambda: count)
        timer.timeout.emit()
    assert collected == []
