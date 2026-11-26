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

from PySide6.QtCore import QEvent, QKeyCombination, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QTabWidget,
                               QVBoxLayout, QWidget, QSpacerItem, QSizePolicy, QStyle)

from . import hotkey, recent, theme
from .help import about_widget
from .shortcut_field import ShortcutField
from .mainwindow import HOTKEY_NAME, SHORTCUT_ROWS

COPY_TEXT = "Copy to the clipboard right after each capture"
MINIMIZE_TEXT = "Then minimize the window"


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("Annotshot settings")
        self.window_ = window
        self._message_owner = "capture"
        self._shown_outcome = None
        self.edits: dict[str, ShortcutField] = {}
        self.resets: dict[str, QPushButton] = {}
        self._guides_to_hide = set()
        self._guide_collapse = QTimer(self)
        self._guide_collapse.setSingleShot(True)
        self._guide_collapse.timeout.connect(self._collapse_guides)
        tabs = QTabWidget(self)
        tabs.addTab(self._keys_tab(), "Shortcuts")
        tabs.addTab(self._capture_tab(), "Capture")
        tabs.addTab(self._look_tab(), "Look")
        tabs.addTab(about_widget(self, on_help=lambda: window._help_from(self)),
                    "About")
        self.tabs = tabs
        self.message = QLabel(self)
        self.message.setWordWrap(True)
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
        window.keyStateChanged.connect(self.refresh_capture_key)
        self.refresh_capture_key()
        tabs.currentChanged.connect(lambda _: self._end_fields('page'))
        QApplication.instance().installEventFilter(self)

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
        if hasattr(self, '_label_hint'):
            self._label_hint.changeSize(max(label.sizeHint().width() for label in self._key_labels),
                                        0, QSizePolicy.Preferred, QSizePolicy.Fixed)
            self.key_scroll.widget().layout().invalidate()

    # -- the Shortcuts tab --------------------------------------------------
    def _edit(self, seq: QKeySequence) -> ShortcutField:
        return ShortcutField(seq, self, owner=self.window_)

    def _keys_tab(self) -> QWidget:
        page = QWidget(self)
        grid = QGridLayout(page)
        grid.setColumnStretch(1, 1)
        grid.setAlignment(Qt.AlignTop)
        w = self.window_
        self._guides = {}
        self._extra_controls = []
        self.hotkey_edit = self._edit(w.hotkey_sequence())
        self.hotkey_edit.setAccessibleName(HOTKEY_NAME)
        self.hotkey_edit.chordEntered.connect(self.commit_hotkey, Qt.DirectConnection)
        self.hotkey_off = QCheckBox("Off", page)
        self.hotkey_off.setAccessibleName(f'{HOTKEY_NAME}: Off')
        self.hotkey_off.setChecked(w.hotkey_off())
        self.hotkey_off.toggled.connect(self._off_toggled)
        label = QLabel(HOTKEY_NAME, page)
        label.setWordWrap(True)
        label.setBuddy(self.hotkey_edit)
        label.setToolTip("Works while Annotshot is not in front")
        labels = [label]
        grid.addWidget(label, 0, 0)
        cell = QWidget(page)
        h = QHBoxLayout(cell)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.hotkey_edit, 1)
        h.addWidget(self.hotkey_off)
        grid.addWidget(cell, 0, 1)
        self.hotkey_reset = QPushButton("Reset", page)
        self.hotkey_reset.setAccessibleName(f'{HOTKEY_NAME}: Reset')
        self.hotkey_reset.clicked.connect(self.reset_hotkey)
        grid.addWidget(self.hotkey_reset, 0, 2)
        self._add_guide(grid, 1, self.hotkey_edit, page)
        if not w.hotkey.available:          # Linux: not built yet
            label.setText(f"{HOTKEY_NAME} — {hotkey.NOT_ON_LINUX}")
            for x in (label, self.hotkey_edit, self.hotkey_off, self.hotkey_reset):
                x.setEnabled(False)
        line = QFrame(page)
        line.setFrameShape(QFrame.HLine)
        grid.addWidget(line, 2, 0, 1, 3)
        row = 3
        common = ('capture', 'copy', 'save')
        rows = [(key, dict(SHORTCUT_ROWS)[key]) for key in common]
        rows.extend((key, name) for key, name in SHORTCUT_ROWS if key not in common)
        for index, (key, name) in enumerate(rows):
            if index == 3:
                self.more_shortcuts = QPushButton('More shortcuts (24)', page)
                self.more_shortcuts.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
                self.more_shortcuts.setCheckable(True)
                self.more_shortcuts.setAccessibleName('More shortcuts')
                self.more_shortcuts.setAccessibleDescription('Show or hide the other 24 shortcut settings')
                self.more_shortcuts.toggled.connect(self._more_toggled)
                grid.addWidget(self.more_shortcuts, row, 0, 1, 3, Qt.AlignLeft)
                row += 1
            a = w.shortcut_actions[key]
            edit = self._edit(a.shortcut())
            edit.setAccessibleName(name)
            edit.chordEntered.connect(lambda seq, k=key: self.commit(k, seq),
                                      Qt.DirectConnection)
            # The field's existing trailing action reports ×. The owner gives
            # ordinary clear its F35 meaning, also for programmatic clear().
            edit.clearButton().defaultAction().triggered.connect(
                lambda _=False, k=key: self.commit(k, QKeySequence()))
            reset = QPushButton("Reset", page)
            reset.setAccessibleName(f'{name}: Reset')
            reset.clicked.connect(lambda _=False, k=key: self.reset(k))
            label = QLabel(name, page)
            label.setWordWrap(True)
            label.setBuddy(edit)
            labels.append(label)
            grid.addWidget(label, row, 0)
            grid.addWidget(edit, row, 1)
            grid.addWidget(reset, row, 2)
            self._add_guide(grid, row + 1, edit, page)
            if index >= 3:
                self._extra_controls.extend((label, edit, reset))
                for control in (label, edit, reset):
                    control.hide()
            self.edits[key], self.resets[key] = edit, reset
            row += 2
        # Preserve the full list's preferred column width while allowing it
        # to shrink on a small dialog. The spacer has no row height.
        self._key_labels = labels
        self._label_hint = QSpacerItem(max(label.sizeHint().width() for label in labels),
                                      0, QSizePolicy.Preferred, QSizePolicy.Fixed)
        grid.addItem(self._label_hint, 0, 0)
        # Widget construction follows the visible order, including the Off cell.
        chain = [self.hotkey_edit, self.hotkey_off, self.hotkey_reset]
        for index, key in enumerate(self.edits):
            if index == 3:
                chain.append(self.more_shortcuts)
            chain.extend((self.edits[key], self.resets[key]))
        for left, right in zip(chain, chain[1:]):
            QWidget.setTabOrder(left, right)
        grid.setRowStretch(row, 1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        # Reserve the existing gutter in both disclosure states. Folding or
        # adding a guide must not change the key box or its clear hit target.
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        self.key_scroll = scroll
        return scroll

    def _add_guide(self, grid, row, field, page):
        guide = QLabel(page)
        guide.setWordWrap(True)
        guide.setObjectName('settingsNote')
        guide.hide()
        grid.addWidget(guide, row, 0, 1, 3)
        self._guides[field] = guide
        def show(text):
            guide.setText(text)
            if text:
                self._guides_to_hide.discard(guide)
                guide.setMinimumHeight(0)
                guide.setMaximumHeight(16777215)
                guide.show()
            elif guide.isVisible() and QApplication.mouseButtons() != Qt.NoButton:
                # Blur may occur during a press on a lower row. Clear the
                # words now; hold its space until that original click ends.
                guide.setFixedHeight(guide.height())
                self._guides_to_hide.add(guide)
            else:
                self._hide_guide(guide)
            if text and hasattr(self, 'key_scroll'):
                self.key_scroll.ensureWidgetVisible(field)
        field.guidanceChanged.connect(show)

    def _hide_guide(self, guide):
        self._guides_to_hide.discard(guide)
        guide.hide()
        guide.setMinimumHeight(0)
        guide.setMaximumHeight(16777215)

    def _collapse_guides(self):
        for guide in tuple(self._guides_to_hide):
            if not guide.text():
                self._hide_guide(guide)

    def _more_toggled(self, expanded):
        focus = QApplication.focusWidget()
        if not expanded and focus in self._extra_controls:
            self.more_shortcuts.setFocus(Qt.OtherFocusReason)
        for control in self._extra_controls:
            control.setVisible(expanded)
        if not expanded:
            for field in self.edits.values():
                if field in self._extra_controls:
                    field.endInput('fold')
        self.more_shortcuts.setAccessibleDescription(
            ('Expanded. Hide' if expanded else 'Collapsed. Show') + ' the other 24 shortcut settings')
        self.more_shortcuts.setIcon(self.style().standardIcon(
            QStyle.SP_ArrowDown if expanded else QStyle.SP_ArrowRight))

    def say(self, text: str | None, owner="local") -> None:
        self._message_owner = owner
        self.message.setText(text or "")

    def _show_key(self, key: str) -> None:
        with QSignalBlocker(self.edits[key]):
            self.edits[key].setKeySequence(
                self.window_.shortcut_actions[key].shortcut())

    def commit(self, key: str, sequence=None) -> str | None:
        """A deliberate row choice, once. A3 keeps the old keypad twin."""
        field = self.edits[key]
        seq = QKeySequence(field.keySequence() if sequence is None else sequence)
        if sequence is not None and not seq.isEmpty():
            combo = seq[0]
            seq = QKeySequence(QKeyCombination(
                combo.keyboardModifiers() & ~Qt.KeypadModifier, combo.key()))
        problem = self.window_.set_shortcut(key, seq)
        taken = problem is None
        self.say(problem or self.window_.key_state()["outcome"])
        self._show_key(key)
        field.settleChord(self.window_.shortcut_actions[key].shortcut(), taken, origin=sequence)
        return problem

    def reset(self, key: str) -> str | None:
        self._end_fields('control')
        problem = self.window_.reset_shortcut(key)
        self.say(problem or self.window_.key_state()["outcome"])
        self._show_key(key)
        return problem

    def refresh_capture_key(self):
        state = self.window_.key_state()
        outcome_changed = self._shown_outcome != state["outcome"]
        self._shown_outcome = state["outcome"]
        # Compare the field's saved presentation, including while X is empty.
        # An identical passive publish must not interrupt preview or a live cap.
        if outcome_changed or self.hotkey_edit._sequence != state["requested"]:
            self._restore_capture_field()
        else:
            with QSignalBlocker(self.hotkey_off):
                self.hotkey_off.setChecked(state["off"])
        if self._message_owner == "capture" or outcome_changed:
            self.say(state["outcome"], "capture")

    def _restore_capture_field(self):
        state = self.window_.key_state()
        with QSignalBlocker(self.hotkey_off):
            self.hotkey_edit.setKeySequence(state["requested"])
            self.hotkey_off.setChecked(state["off"])

    def _end_fields(self, reason):
        for field in (*self.edits.values(), self.hotkey_edit):
            field.endInput(reason)

    def _off_toggled(self, off):
        self._end_fields('control')
        self._message_owner = "capture"
        self.window_.set_hotkey(self.window_.hotkey_sequence(), off, True)
        self.refresh_capture_key()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonRelease and self._guides_to_hide:
            self._guide_collapse.start(0)
        # Observation only: hand off a try before the triggering input. No
        # key identity, flags, field state, ownership or consumption here.
        # A window mouse press arrives before QWidget assigns child focus.
        # A departing FocusAboutToChange may instead be the legitimate Try
        # minimize; it supplies no evidence that the person has returned.
        return_click = event.type() == QEvent.MouseButtonPress and watched is self.windowHandle()
        child_input = (event.type() in (QEvent.WindowActivate, QEvent.FocusIn,
                                       QEvent.KeyPress, QEvent.MouseButtonPress)
                       and isinstance(watched, QWidget)
                       and (watched is self or self.isAncestorOf(watched)))
        if ((return_click or child_input) and self.isVisible()
                and self.window_._key_try is not None):
            self.window_.end_key_try("Try cancelled")
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        self.window_.end_key_try("Try cancelled")
        super().showEvent(event)

    def done(self, result):
        self._end_fields("leave")
        super().done(result)

    def closeEvent(self, event):
        self._end_fields("leave")
        super().closeEvent(event)

    def capture_key_has_focus(self):
        focus = QApplication.focusWidget()
        return (self.isVisible() and QApplication.applicationState() == Qt.ApplicationActive
                and (focus is self.hotkey_edit or self.hotkey_edit.isAncestorOf(focus)))

    def commit_hotkey(self, sequence=None, *, explicit=True) -> str | None:
        if not explicit:
            self.hotkey_edit.endInput('passive')
            self._restore_capture_field()
            return None
        self._message_owner = "capture"
        seq = QKeySequence(self.hotkey_edit.keySequence() if sequence is None else sequence)
        previous_backend = self.window_.hotkey._backend
        problem = self.window_.set_hotkey(seq,
                                         self.hotkey_off.isChecked() if sequence is None else False, True)
        w = self.window_
        # A successful setter return takes the chord. A replacement may also
        # take it and report an old-handle release fault: its primary changed.
        # A validation refusal keeps its primary, even for exact legacy re-entry.
        if problem is None or w.hotkey._backend is not previous_backend:
            taken = (not w.hotkey.cleanup_blocked and w.hotkey.registered
                     and not w.hotkey_off() and w.hotkey.sequence == seq)
        else:
            taken = False
        self.refresh_capture_key()
        self.hotkey_edit.settleChord(w.hotkey_sequence(), bool(taken), origin=sequence)
        return problem

    def reset_hotkey(self) -> str | None:
        self._end_fields('control')
        self._message_owner = "capture"
        problem = self.window_._apply_key(QKeySequence(hotkey.DEFAULT),
                                          self.hotkey_off.isChecked(), reset=True)
        self.refresh_capture_key()
        return problem

    def _reset_all(self) -> None:
        self._end_fields('control')
        self._message_owner = "capture"
        w = self.window_
        problem = w.reset_all_shortcuts()
        for key in self.edits:
            self._show_key(key)
        self.refresh_capture_key()

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
                      f"clipboard and the window waits in {where}. " +
                      ("Click Annotshot in the Dock to bring it back." if sys.platform == "darwin" else
                       "Click Annotshot on the taskbar to bring it back."), page)
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
