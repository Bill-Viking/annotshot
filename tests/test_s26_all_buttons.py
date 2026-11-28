"""s26 guards for every toolbar button, using shown Qt-offscreen windows."""
from contextlib import contextmanager

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QToolBar, QToolButton

from annotshot import theme
from annotshot.app import make_app
from annotshot.mainwindow import FitBar, MainWindow
from annotshot.scene import Document
from test_app_imports import WIDE_FONT_RATIO


AREAS = ((500, 400), (800, 800), (1024, 768), (1366, 768), (1920, 1080))
THEMES = tuple(theme.THEMES)
FONT_CASES = [(name, font) for name in THEMES for font in ("shipped", "wide")]
FONT_CASES.append(("light", "dejavu"))


def settle(window, qapp, width):
    window.resize(width, 720)
    window.layout().activate()
    for _ in range(3):
        qapp.processEvents()


def assert_all_buttons_visible(window):
    for bar in window.findChildren(QToolBar):
        extension = bar.findChild(QToolButton, "qt_toolbar_ext_button")
        assert extension is None or not extension.isVisibleTo(window), bar.objectName()
        if bar.objectName() not in ("main", "tools"):
            continue
        assert bar.sizeHint().width() <= bar.width(), (
            bar.objectName(), bar.sizeHint().width(), bar.width())
        for action in bar.actions():
            if action.isSeparator():
                continue
            widget = bar.widgetForAction(action)
            assert widget.isVisibleTo(window), (bar.objectName(), action.text())
            assert bar.rect().contains(widget.geometry()), (
                bar.objectName(), action.text(), widget.geometry(), bar.rect())


@pytest.fixture
def editor(qapp, white, monkeypatch):
    make_app()

    @contextmanager
    def opened(name, area, font="shipped"):
        with monkeypatch.context() as patch:
            patch.setattr(MainWindow, "_screen_area", lambda self: QRect(0, 0, *area))
            family, ui_px, small_px = theme.FONTS[name]
            if font == "wide":
                patch.setitem(theme.FONTS, name,
                              (family, round(ui_px * WIDE_FONT_RATIO),
                               round(small_px * WIDE_FONT_RATIO)))
            elif font == "dejavu":
                if "DejaVu Sans" not in QFontDatabase.families():
                    pytest.skip("DejaVu Sans is not installed")
                patch.setitem(theme.FONTS, name, ("DejaVu Sans", ui_px, small_px))
            theme._filled.clear()
            theme.apply(qapp, name)
            window = MainWindow()
            try:
                window._bind(Document(white))
                window.show()
                settle(window, qapp, 1100)
                yield window
            finally:
                window.doc.undo_stack.mark_exported()
                window.hide()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                qapp.processEvents()
        theme._filled.clear()
        theme.apply(qapp, theme.DEFAULT)

    yield opened
    theme._filled.clear()


@pytest.mark.parametrize("area", AREAS)
@pytest.mark.parametrize("name,font", FONT_CASES)
def test_g1_rule_at_minimum(editor, qapp, name, font, area):
    with editor(name, area, font) as window:
        window.resize(1, 1)
        for _ in range(3):
            qapp.processEvents()
        assert window.width() == window.minimumWidth()
        if area != (500, 400):
            assert window.minimumWidth() == min(900, int(0.8 * area[0]))
        assert_all_buttons_visible(window)


@pytest.mark.parametrize("area", ((800, 800), (1920, 1080)))
@pytest.mark.parametrize("name", THEMES)
def test_g2_sweep_exact_thresholds_and_retheme(editor, qapp, name, area):
    with editor(name, area) as window:
        minimum = window.minimumWidth()
        for width in range(minimum, 1201, 7):
            settle(window, qapp, width)
            assert_all_buttons_visible(window)
        for bar in (window.main_bar, window.tools_bar):
            needs = bar.needs()
            for level, need in enumerate(needs):
                if need < minimum:
                    continue
                settle(window, qapp, need)
                assert bar.level() == level, (name, bar.objectName(), needs, need)
                assert_all_buttons_visible(window)
                if level + 1 < len(needs) and need - 1 >= minimum:
                    settle(window, qapp, need - 1)
                    assert bar.level() == level + 1, (name, bar.objectName(), needs)
                    assert_all_buttons_visible(window)
        # Refit at the same width when a theme changes the measured needs.
        settle(window, qapp, window.minimumWidth())
        following = THEMES[(THEMES.index(name) + 1) % len(THEMES)]
        theme.apply(qapp, following)
        settle(window, qapp, window.minimumWidth())
        assert_all_buttons_visible(window)
        assert window.main_bar.sizeHint().width() <= window.main_bar.width()
        expected = next((i for i, need in enumerate(window.tools_bar.needs())
                         if need <= window.tools_bar.width()),
                        len(window.tools_bar.needs()) - 1)
        assert window.tools_bar.level() == expected


@pytest.mark.parametrize("name", THEMES)
def test_g3_pinned_look(editor, qapp, name):
    with editor(name, (1920, 1080)) as window:
        needs = (window.main_bar.needs(), window.tools_bar.needs())
        print(f"{name}: Main {needs[0]}, Tools {needs[1]}")
        settle(window, qapp, 900)
        for bar in (window.main_bar, window.tools_bar):
            expected = next((i for i, n in enumerate(bar.needs()) if n <= bar.width()),
                            len(bar.needs()) - 1)
            assert bar.level() == expected, needs
        for action in (window.a_copy, window.a_clear):
            assert window.main_bar.widgetForAction(action).toolButtonStyle() == Qt.ToolButtonTextBesideIcon
        assert_all_buttons_visible(window)
        settle(window, qapp, 1100)
        assert (window.main_bar.level(), window.tools_bar.level()) == (0, 0), needs
        for bar in (window.main_bar, window.tools_bar):
            assert len({bar.widgetForAction(a).geometry().center().y() for a in bar.actions() if a.text()}) == 1
        assert_all_buttons_visible(window)


@pytest.mark.parametrize("area", AREAS)
def test_g4_font_free_compact_measure_and_floor(editor, qapp, area):
    compact_tools = []
    for name in THEMES:
        with editor(name, area) as window:
            needs = (window.main_bar.compact_need(), window.tools_bar.compact_need())
            compact_tools.append(needs[1])
            assert needs[1] <= 640
            assert window.minimumWidth() == min(900, int(.8 * area[0]))
            settle(window, qapp, window.minimumWidth())
            assert_all_buttons_visible(window)
    assert len(set(compact_tools)) == 1, compact_tools


@pytest.mark.parametrize("name", THEMES)
def test_g5_every_icon_is_named(editor, qapp, name):
    with editor(name, (500, 400)) as window:
        settle(window, qapp, window.minimumWidth())
        for bar in (window.main_bar, window.tools_bar):
            for action in bar.actions():
                if action.isSeparator() or not action.text():
                    continue
                label = {"Front": "Bring to front", "Back": "Send to back"}.get(
                    action.text(), action.text())
                word = label.split()[0].rstrip("…")
                if action in (window.a_dup, window.a_front, window.a_back, window.a_delete):
                    assert action.toolTip() == "Select an object first"
                else:
                    assert action.toolTip().startswith(word), action.text()


@pytest.mark.parametrize("name", THEMES)
def test_g6_guard_rejects_disabled_fitting(editor, qapp, monkeypatch, name):
    monkeypatch.setattr(FitBar, "fit", lambda self, width: None)
    with editor(name, (1920, 1080)) as window:
        settle(window, qapp, 900)
        with pytest.raises(AssertionError):
            assert_all_buttons_visible(window)
