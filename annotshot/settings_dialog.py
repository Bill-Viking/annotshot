"""Settings…: four tabs. Keys -- every action's shortcut, each with its own
Reset, Reset all, and the capture key that works from anywhere. Capture --
quick capture (copy each capture, then minimize) and whether the last
captures are kept in the Recent pane. Look -- the theme (Light, Dark,
Retro), applied to the whole app the moment it is picked. About -- the
same content as About Annotshot… (help.about_widget builds both).

Every change applies and is saved at once; a key already in use is refused
with one line naming what uses it. The window owns the rules
(MainWindow.set_shortcut / set_hotkey); this page only shows them.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QKeySequenceEdit,
                               QLabel, QPushButton, QScrollArea, QSizePolicy, QTabWidget,
                               QVBoxLayout, QWidget)

from . import hotkey, recent, theme
from .help import about_widget
from .mainwindow import HOTKEY_NAME, SHORTCUT_ROWS

COPY_TEXT = "Copy to the clipboard right after each capture"
MINIMIZE_TEXT = "Then minimize the window"


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("Annotshot settings")
        self.window_ = window
        self.edits: dict[str, QKeySequenceEdit] = {}
        self.resets: dict[str, QPushButton] = {}
        tabs = QTabWidget(self)
        tabs.addTab(self._keys_tab(), "Shortcuts")
        tabs.addTab(self._capture_tab(), "Capture")
        tabs.addTab(self._look_tab(), "Look")
        tabs.addTab(about_widget(self, on_help=lambda: window._help_from(self)),
                    "About")
        self.tabs = tabs
        self.message = QLabel(self)
        self.message.setObjectName("settingsMessage")
        self.retheme()
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        self.reset_all = buttons.addButton("Reset all",
                                           QDialogButtonBox.ResetRole)
        self.reset_all.clicked.connect(self._reset_all)
        box = QVBoxLayout(self)
        box.addWidget(tabs)
        box.addWidget(self.message)
        box.addWidget(buttons)
        self.resize(520, 640)

    def retheme(self) -> None:
        """The refusal line's red, in the current theme (theme.apply calls
        this; the rest of the window follows the app's look by itself)."""
        self.message.setStyleSheet(
            f"color: {theme.color('error').name()};")
        box = getattr(self, "theme_box", None)
        if box is not None and box.currentData() != theme.current():
            box.blockSignals(True)          # shown, not picked again
            box.setCurrentIndex(theme.NAMES.index(theme.current()))
            box.blockSignals(False)

    # -- the Shortcuts tab --------------------------------------------------
    def _edit(self, seq: QKeySequence) -> QKeySequenceEdit:
        e = QKeySequenceEdit(seq, self)
        e.setMaximumSequenceLength(1)
        e.setClearButtonEnabled(True)
        e.setMinimumWidth(80)
        e.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        return e

    def _keys_tab(self) -> QWidget:
        page = QWidget(self)
        grid = QGridLayout(page)
        grid.setColumnStretch(1, 1)
        w = self.window_
        for row, (key, name) in enumerate(SHORTCUT_ROWS):
            a = w.shortcut_actions[key]
            edit = self._edit(a.shortcut())
            edit.editingFinished.connect(lambda k=key: self.commit(k))
            reset = QPushButton("Reset", page)
            reset.clicked.connect(lambda _=False, k=key: self.reset(k))
            label = QLabel(name, page)
            label.setWordWrap(True)
            grid.addWidget(label, row, 0)
            grid.addWidget(edit, row, 1)
            grid.addWidget(reset, row, 2)
            self.edits[key], self.resets[key] = edit, reset
        row = len(SHORTCUT_ROWS)
        line = QFrame(page)
        line.setFrameShape(QFrame.HLine)
        grid.addWidget(line, row, 0, 1, 3)
        self.hotkey_edit = self._edit(w.hotkey_sequence())
        self.hotkey_edit.editingFinished.connect(self.commit_hotkey)
        self.hotkey_off = QCheckBox("Off", page)
        self.hotkey_off.setChecked(w.hotkey_off())
        self.hotkey_off.toggled.connect(lambda _: self.commit_hotkey())
        label = QLabel(HOTKEY_NAME, page)
        label.setWordWrap(True)
        label.setToolTip("Works while Annotshot is not in front")
        grid.addWidget(label, row + 1, 0)
        cell = QWidget(page)
        h = QHBoxLayout(cell)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.hotkey_edit, 1)
        h.addWidget(self.hotkey_off)
        grid.addWidget(cell, row + 1, 1)
        self.hotkey_reset = QPushButton("Reset", page)
        self.hotkey_reset.clicked.connect(self.reset_hotkey)
        grid.addWidget(self.hotkey_reset, row + 1, 2)
        if not w.hotkey.available:          # Linux: not built yet
            label.setText(f"{HOTKEY_NAME} — {hotkey.NOT_ON_LINUX}")
            for x in (label, self.hotkey_edit, self.hotkey_off,
                      self.hotkey_reset):
                x.setEnabled(False)
        grid.setRowStretch(row + 2, 1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def say(self, text: str | None) -> None:
        self.message.setText(text or "")

    def _show_key(self, key: str) -> None:
        self.edits[key].setKeySequence(
            self.window_.shortcut_actions[key].shortcut())

    def commit(self, key: str) -> str | None:
        """Apply the row's key; on a refusal the row shows its key again."""
        problem = self.window_.set_shortcut(key,
                                            self.edits[key].keySequence())
        self.say(problem)
        if problem:
            self._show_key(key)
        return problem

    def reset(self, key: str) -> str | None:
        problem = self.window_.reset_shortcut(key)
        self.say(problem)
        self._show_key(key)
        return problem

    def commit_hotkey(self) -> str | None:
        """Apply the capture key. A key in use is refused and the row shows
        the saved key again; a key the system refuses stays as typed."""
        w = self.window_
        problem = w.set_hotkey(self.hotkey_edit.keySequence(),
                               self.hotkey_off.isChecked())
        self.say(problem)
        saved = w.hotkey_sequence()
        if problem and saved != self.hotkey_edit.keySequence():
            self.hotkey_edit.setKeySequence(saved)
        return problem

    def reset_hotkey(self) -> str | None:
        self.hotkey_edit.setKeySequence(QKeySequence(hotkey.DEFAULT))
        return self.commit_hotkey()

    def _reset_all(self) -> None:
        w = self.window_
        w.reset_all_shortcuts()
        for key in self.edits:
            self._show_key(key)
        self.hotkey_edit.setKeySequence(w.hotkey_sequence())
        self.say(w.apply_hotkey())

    # -- the Capture tab ----------------------------------------------------
    def _capture_tab(self) -> QWidget:
        page = QWidget(self)
        box = QVBoxLayout(page)
        w = self.window_
        self.quick_copy = QCheckBox(COPY_TEXT, page)
        self.quick_minimize = QCheckBox(MINIMIZE_TEXT, page)
        self.quick_copy.setChecked(w.quick_copy())
        self.quick_minimize.setChecked(
            w.settings.value("capture/minimize", False, type=bool))
        self.quick_minimize.setEnabled(self.quick_copy.isChecked())
        self.quick_copy.toggled.connect(self._copy_toggled)
        self.quick_minimize.toggled.connect(
            lambda on: w.settings.setValue("capture/minimize", bool(on)))
        where = "the Dock" if sys.platform == "darwin" else "the taskbar"
        note = QLabel(f"With both on, a capture goes straight to the "
                      f"clipboard and the window waits in {where}; the "
                      f"capture key or a click brings it back.", page)
        note.setWordWrap(True)
        note.setObjectName("settingsNote")
        box.addWidget(self.quick_copy)
        inset = QHBoxLayout()
        inset.addSpacing(22)
        inset.addWidget(self.quick_minimize)
        box.addLayout(inset)
        box.addSpacing(8)
        box.addWidget(note)
        box.addSpacing(16)
        self.keep_recent = QCheckBox(recent.KEEP_TEXT, page)
        self.keep_recent.setChecked(w.keep_recent())
        self.keep_recent.toggled.connect(
            lambda on: w.settings.setValue(recent.SETTING, bool(on)))
        box.addWidget(self.keep_recent)
        self.keep_running = QCheckBox(
            "Keep Annotshot running when its window is closed", page)
        self.keep_running.setChecked(w.keep_running())
        if sys.platform == "linux":
            self.keep_running.setEnabled(False)
            self.keep_running.setToolTip("Not available on Linux yet")
        self.keep_running.toggled.connect(w.set_keep_running)
        box.addWidget(self.keep_running)
        box.addStretch(1)
        return page

    def _copy_toggled(self, on: bool) -> None:
        self.window_.settings.setValue("capture/copy", bool(on))
        self.quick_minimize.setEnabled(on)

    # -- the Look tab -------------------------------------------------------
    def _look_tab(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        self.theme_box = QComboBox(page)
        self.theme_box.setObjectName("themeBox")
        for key, name in theme.CHOICES:
            self.theme_box.addItem(name, key)
        self.theme_box.setCurrentIndex(theme.NAMES.index(theme.current()))
        self.theme_box.setToolTip("Light, Dark or Retro (the pixel font); "
                                  "applied at once")
        self.theme_box.currentIndexChanged.connect(self._theme_picked)
        form.addRow("Theme", self.theme_box)
        self.remember_props = QCheckBox(
            "Start each tool with the settings I used last", page)
        self.remember_props.setChecked(self.window_.view.remember_props)
        self.remember_props.toggled.connect(self.window_.set_remember_props)
        form.addRow(self.remember_props)
        self.reset_props = QPushButton("Reset to factory settings", page)
        self.reset_props.clicked.connect(self._reset_props)
        form.addRow(self.reset_props)
        return page

    def _reset_props(self) -> None:
        self.window_.reset_tool_defaults()
        self.say("Reset")

    def _theme_picked(self, index: int) -> None:
        self.window_.set_theme(self.theme_box.itemData(index))
