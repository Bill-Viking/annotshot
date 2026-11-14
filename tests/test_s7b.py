"""Tool starting styles survive launches; the strip shows what a pick changes.

All windows remain offscreen and settings use conftest's private ini file.
"""
import pytest
from PySide6.QtCore import QPointF, QSettings
from PySide6.QtGui import QColor

from annotshot.items import (ITEM_TYPES, ArrowItem, CalloutItem, HighlightItem,
                            RectItem, TextBoxItem)
from annotshot.tools import ITEM_FOR_TOOL, Tool


@pytest.fixture
def window(qapp):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    make_app()
    w = MainWindow()
    yield w
    w.deleteLater()


def add(w, *items):
    w.doc.add_items(list(items))
    w.doc.select_only(list(items))


def draw(w, tool):
    """Use the same preview/finish road as a drag, without a shown window."""
    w.doc.end_text_edit()
    w.doc.clearSelection()
    v = w.view
    v.set_tool(tool)
    start, end = QPointF(10, 10), QPointF(200, 100)
    v._start_preview(start)
    item = v._preview
    v._update_preview(start, end)
    v._finish_tool(True, start, end)
    w.doc.end_text_edit()
    return item


def values(settings):
    settings.sync()
    return {key: settings.value(key) for key in settings.allKeys()}


def test_selected_arrow_picks_survive_a_fresh_window(window, monkeypatch):
    from annotshot.mainwindow import MainWindow
    from PySide6.QtWidgets import QColorDialog
    arrow = ArrowItem()
    add(window, arrow)
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor("#FF0000"))
    window.c_border.click()
    window.cb_line.setCurrentIndex(window.cb_line.findData("dashed"))
    window.s_width.setValue(6)
    window.cb_head.setCurrentIndex(window.cb_head.findData("open"))
    window.cb_head_size.setCurrentIndex(window.cb_head_size.findData("large"))
    window.ch_both.setChecked(True)
    expected = {"stroke_color": "#FF0000", "stroke_width": 6,
                "line_style": "dashed", "head": "open", "head_size": "large",
                "both_ends": True}
    for key, value in expected.items():
        assert arrow.props[key] == value
        assert window.settings.value(f"props/arrow/{key}") == value
    snapshot = values(window.settings)
    fresh = MainWindow()
    try:
        assert values(window.settings) == snapshot  # startup only reads
        new = draw(fresh, Tool.ARROW)
        assert all(new.props[k] == v for k, v in expected.items())
    finally:
        fresh.deleteLater()


def test_callouts_keep_their_own_font_fill_and_border(window):
    text, callout = TextBoxItem(), CalloutItem()
    add(window, text)
    window._set({"font_px": 32, "text_color": "#FF0000"}, "Text")
    window.b_nofill.click()
    window.b_noborder.click()
    add(window, callout)
    window._set({"font_px": 48, "text_color": "#0000FF"}, "Callout")
    assert window.settings.value("props/text/font_px") == 32
    assert window.settings.value("props/callout/font_px") == 48
    new_text = draw(window, Tool.TEXT)
    new_callout = draw(window, Tool.CALLOUT)
    assert new_text.props["font_px"] == 32
    assert QColor(new_text.props["fill_color"]).alpha() == 0
    assert QColor(new_text.props["border_color"]).alpha() == 0
    assert new_callout.props["font_px"] == 48
    assert new_callout.props["text_color"] == "#0000FF"
    assert new_callout.props["fill_color"] == CalloutItem.DEFAULTS["fill_color"]


@pytest.mark.parametrize("tool,cls", ITEM_FOR_TOOL.items())
def test_empty_selection_edits_only_the_active_kinds_keys(window, tool, cls):
    window.view.set_tool(tool)
    target = window.view.defaults_item()
    for control, key in window._controls.items():
        assert control.isEnabled() == (target.key_for(key) is not None and
               not (control is window.b_nofill and tool is Tool.HIGHLIGHT))
    count = window.doc.undo_stack.count()
    window._set({"opacity": 0.63, "text": "never remembered"}, "Opacity")
    assert window.settings.value(f"props/{cls.KIND}/opacity") == 0.63
    assert not window.settings.contains(f"props/{cls.KIND}/text")
    assert window.doc.undo_stack.count() == count
    new = draw(window, tool)
    assert new.props["opacity"] == 0.63


def test_arrow_tool_with_no_selection_enables_and_persists_color(window, monkeypatch):
    from PySide6.QtWidgets import QColorDialog
    window.view.set_tool(Tool.ARROW)
    assert window.c_border.isEnabled() and window.s_width.isEnabled()
    assert not window.f_font.isEnabled()
    assert window.sel_heading.text() == "New arrows"
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor("blue"))
    window.c_border.click()
    assert window.settings.value("props/arrow/stroke_color") == "#0000FF"
    assert draw(window, Tool.ARROW).props["stroke_color"] == "#0000FF"


def test_mixed_selection_remembers_each_applicable_kind_and_undo_does_not_erase_it(window):
    text, rect, arrow = TextBoxItem(), RectItem(), ArrowItem()
    add(window, text, rect, arrow)
    window._set({"border_color": "#0000FF", "font_px": 36}, "Mixed")
    assert window.settings.value("props/text/border_color") == "#0000FF"
    assert window.settings.value("props/rect/stroke_color") == "#0000FF"
    assert window.settings.value("props/arrow/stroke_color") == "#0000FF"
    assert not window.settings.contains("props/arrow/font_px")
    window.undo()
    assert arrow.props["stroke_color"] == ArrowItem.DEFAULTS["stroke_color"]
    assert draw(window, Tool.ARROW).props["stroke_color"] == "#0000FF"


def test_remember_off_ignores_saved_styles_and_picks_write_nothing(window):
    from annotshot.mainwindow import MainWindow
    from annotshot.settings_dialog import SettingsDialog
    window.view.set_tool(Tool.ARROW)
    window._set({"border_color": "#0000FF", "border_width": 8}, "Arrow")
    d = SettingsDialog(window)
    assert d.remember_props.isChecked()
    d.remember_props.setChecked(False)
    snapshot = values(window.settings)
    assert window.s_width.value() == ArrowItem.DEFAULTS["stroke_width"]
    window.s_width.setValue(12)  # a pick with nothing selected
    arrow = draw(window, Tool.ARROW)
    assert arrow.props == ArrowItem.DEFAULTS
    window._set({"border_color": "#FF0000"}, "Selected arrow")
    assert arrow.props["stroke_color"] == "#FF0000"  # editing still works
    assert values(window.settings) == snapshot
    fresh = MainWindow()
    try:
        assert not fresh.view.remember_props
        assert draw(fresh, Tool.ARROW).props == ArrowItem.DEFAULTS
        assert values(window.settings) == snapshot
    finally:
        fresh.deleteLater()
    d.remember_props.setChecked(True)
    window.doc.clearSelection()
    window.view.set_tool(Tool.ARROW)
    assert window.s_width.value() == 8
    d.deleteLater()


def test_reset_clears_every_kind_but_keeps_shortcuts_and_remember(window):
    from annotshot.settings_dialog import SettingsDialog
    for kind in ITEM_TYPES:
        window.settings.setValue(f"props/{kind}/opacity", 0.2)
        window.settings.setValue(f"props/{kind}/unknown", "stale")
    window.settings.setValue("shortcuts/save", "Alt+S")
    window.view.load_tool_defaults()
    window.view.set_tool(Tool.ARROW)
    d = SettingsDialog(window)
    d.reset_props.click()
    assert d.message.text() == "Reset"
    assert not any(key.startswith(f"props/{kind}/")
                   for key in window.settings.allKeys() for kind in ITEM_TYPES)
    assert window.settings.value("shortcuts/save") == "Alt+S"
    assert d.remember_props.isChecked()
    for kind in ITEM_TYPES:
        assert window.view.tool_defaults[kind] == window.view.factory_style(kind)
    assert window.sl_opacity.value() == 100
    d.deleteLater()


@pytest.mark.parametrize("tool,label", [
    (Tool.ARROW, "Line colour"), (Tool.PEN, "Line colour"),
    (Tool.RECT, "Border"), (Tool.ELLIPSE, "Border"),
    (Tool.TEXT, "Border"), (Tool.CALLOUT, "Border")])
def test_line_words_and_two_rows_follow_selection_and_active_tool(window, tool, label):
    for selected in (False, True):
        if selected:
            draw(window, tool)
        else:
            window.view.set_tool(tool)
        assert window.border_label.text() == label
        assert window.c_border.toolTip() == ("Line color" if label == "Line colour" else "Border color")
        assert window.b_noborder.isHidden() == (label == "Line colour")
        assert window.prop_strip.layout().count() == 2
        assert not window.line_group.isHidden() if tool in (
            Tool.ARROW, Tool.PEN, Tool.RECT, Tool.ELLIPSE) else window.line_group.isHidden()


def test_arrow_second_row_fits_the_start_width(window):
    window.show_editor()
    window.resize(1100, 720)
    draw(window, Tool.ARROW)
    assert window.prop_row2.sizeHint().width() < window.width()
    assert window.prop_row1.sizeHint().width() < window.width()
    assert window.prop_strip.sizeHint().width() < window.width()
    add(window, RectItem())
    assert window.prop_strip.layout().count() == 2
    assert window.cb_line.isEnabled() and not window.line_group.isHidden()


@pytest.mark.parametrize("key,value", [
    ("stroke_color", "not a color"), ("stroke_width", -1),
    ("stroke_width", 41), ("stroke_width", "nan"),
    ("stroke_width", "inf"), ("head", "bad"), ("head_size", "huge"),
    ("both_ends", "maybe"), ("opacity", 1.5)])
def test_bad_saved_arrow_values_fall_back_without_writing(window, key, value):
    window.settings.setValue(f"props/arrow/{key}", value)
    snapshot = values(window.settings)
    window.view.load_tool_defaults()
    assert window.view.starting_style("arrow")[key] == ArrowItem.DEFAULTS[key]
    assert values(window.settings) == snapshot


def test_settings_strings_parse_and_highlight_keeps_its_alpha(window):
    settings = window.settings
    for key, value in {"font_px": "42", "bold": "false", "italic": "true",
                       "font_family": "VT323", "align": "right"}.items():
        settings.setValue(f"props/text/{key}", value)
    settings.setValue("props/highlight/fill_color", "#00FF0000")
    settings.setValue("props/arrow/both_ends", "true")
    window.view.load_tool_defaults()
    style = window.new_text_style()
    assert (style["font_px"], style["bold"], style["italic"]) == (42, False, True)
    assert style["align"] == "right" and style["font_family"] == "VT323"
    assert window.view.tool_defaults["arrow"]["both_ends"] is True
    new = draw(window, Tool.HIGHLIGHT)
    assert new.props["fill_color"] == "#73FF0000"
    window._set({"fill_color": "#000000FF"}, "Highlight")
    assert settings.value("props/highlight/fill_color") == "#730000FF"


def test_check_is_read_only_for_preferences(qapp, private_settings, monkeypatch):
    from annotshot import __main__, mainwindow
    settings = QSettings(private_settings, QSettings.IniFormat)
    settings.setValue("props/arrow/stroke_width", "broken")
    snapshot = values(settings)

    class ReadOnlySettings:
        def value(self, *a, **k):
            return settings.value(*a, **k)

        def contains(self, *a):
            return settings.contains(*a)

        def setValue(self, *a):
            pytest.fail("--check wrote a preference")

        def remove(self, *a):
            pytest.fail("--check removed a preference")

    monkeypatch.setattr(mainwindow, "QSettings", lambda *a: ReadOnlySettings())
    assert __main__.check() == 0
    assert values(settings) == snapshot
