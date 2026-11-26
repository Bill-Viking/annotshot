from key_field_support import field_parts
"""Key wording, offscreen only, with no system-wide key registration."""
import sys
import re
import string
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QKeyCombination, Qt
from PySide6.QtGui import QKeySequence

from annotshot import hotkey
from annotshot.help import shortcuts_markdown
from annotshot.keywords import key_words


MODIFIERS = [
    (Qt.MetaModifier, "Control"),
    (Qt.AltModifier, "Option"),
    (Qt.ShiftModifier, "Shift"),
    (Qt.ControlModifier, "Command"),
]
NAMED_KEYS = [
    ("Space", "Space"), ("Return", "Return"), ("Enter", "Enter"),
    ("Backspace", "Delete"), ("Del", "Forward Delete"),
    ("Esc", "Escape"), ("Tab", "Tab"),
    ("Left", "Left Arrow"), ("Right", "Right Arrow"),
    ("Up", "Up Arrow"), ("Down", "Down Arrow"),
    ("PgUp", "Page Up"), ("PgDown", "Page Down"),
    ("Home", "Home"), ("End", "End"),
    ("C", "C"), ("7", "7"), ("F5", "F5"), ("", ""),
]
NAMED_KEYS[-1:-1] = [
    (",", "Comma"), (".", "Period"), ("+", "Plus"), ("-", "Minus"),
    ("=", "Equals"), ("/", "Slash"), ("\\", "Backslash"),
    (";", "Semicolon"), ("'", "Quote"), ("[", "Left Bracket"),
    ("]", "Right Bracket"), ("`", "Grave Accent"),
]
CASES = [(QKeySequence(portable), words) for portable, words in NAMED_KEYS]
CASES += [
    (QKeySequence("Alt+Shift+Space"), "Option+Shift+Space"),
    (QKeySequence("Ctrl+C"), "Command+C"),
    (QKeySequence("Ctrl+Shift+Z"), "Shift+Command+Z"),
    (QKeySequence("Ctrl+Alt+Shift+Meta+C"), "Control+Option+Shift+Command+C"),
    (QKeySequence("Ctrl+K, Ctrl+C"), "Command+K, Command+C"),
]
# Each modifier by itself and every pair, both with a key and without one.
for size in (1, 2):
    for group in combinations(MODIFIERS, size):
        mods = Qt.NoModifier
        for modifier, _ in group:
            mods |= modifier
        words = "+".join(name for _, name in group)
        CASES.append((QKeySequence(QKeyCombination(mods, Qt.Key_C)), words + "+C"))
        CASES.append((QKeySequence(QKeyCombination(mods, Qt.Key_unknown)),
                      words + "+this key"))
# Exercise named keys with all modifiers too, not only their bare forms.
for portable, words in NAMED_KEYS[:-1]:
    CASES.append((QKeySequence("Ctrl+Alt+Shift+Meta+" + portable),
                  "Control+Option+Shift+Command+" + words))
for key, words in [(Qt.Key_1, "1"), (Qt.Key_Plus, "Plus"),
                   (Qt.Key_Enter, "Enter")]:
    for mods, prefix in [(Qt.KeypadModifier, ""),
                         (Qt.ControlModifier | Qt.KeypadModifier, "Command+")]:
        CASES.append((QKeySequence(QKeyCombination(mods, key)), prefix + "Keypad " + words))


@pytest.mark.parametrize("seq,expected", CASES)
@pytest.mark.parametrize("as_combination", [False, True])
def test_mac_words(seq, expected, as_combination):
    if as_combination and seq.count() != 1:
        pytest.skip("an empty or multi-chord sequence is not one combination")
    value = seq[0] if as_combination else seq
    assert key_words(value, platform="darwin") == expected


@pytest.mark.parametrize("seq,_", CASES)
def test_mac_words_have_only_printable_ascii(seq, _):
    assert all(32 <= ord(ch) <= 126 for ch in key_words(seq, "darwin"))


@pytest.mark.parametrize("seq,_", CASES)
@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize("as_combination", [False, True])
def test_other_platforms_keep_portable_text(seq, _, platform, as_combination):
    if as_combination and seq.count() != 1:
        pytest.skip("an empty or multi-chord sequence is not one combination")
    value = seq[0] if as_combination else seq
    assert key_words(value, platform) == seq.toString(QKeySequence.PortableText)


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
def test_empty_combination(platform):
    assert key_words(QKeyCombination(), platform) == ""


def test_default_platform():
    seq = QKeySequence("Alt+Shift+Space")
    assert key_words(seq) == key_words(seq, sys.platform)


PUNCTUATION = list(zip(string.punctuation, [
    "Exclamation Mark", "Double Quote", "Number Sign", "Dollar", "Percent",
    "Ampersand", "Quote", "Left Parenthesis", "Right Parenthesis", "Asterisk",
    "Plus", "Comma", "Minus", "Period", "Slash", "Colon", "Semicolon",
    "Less Than", "Equals", "Greater Than", "Question Mark", "At Sign",
    "Left Bracket", "Backslash", "Right Bracket", "Caret", "Underscore",
    "Grave Accent", "Left Brace", "Vertical Bar", "Right Brace", "Tilde",
], strict=True))


@pytest.mark.parametrize("symbol,word", PUNCTUATION)
@pytest.mark.parametrize("keypad", [False, True])
@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
def test_every_ascii_punctuation_key(symbol, word, keypad, platform):
    mods = Qt.ControlModifier | (Qt.KeypadModifier if keypad else Qt.NoModifier)
    seq = QKeySequence(QKeyCombination(mods, Qt.Key(ord(symbol))))
    text = key_words(seq, platform)
    if platform == "darwin":
        assert text == "Command+" + ("Keypad " if keypad else "") + word
        assert re.fullmatch(r"[A-Za-z0-9 +]+", text)
    else:
        assert text == seq.toString(QKeySequence.PortableText)


@pytest.mark.parametrize("key,expected", [
    (Qt.Key_MediaPlay, "Media Play"), (Qt.Key_unknown, "this key"),
    (Qt.Key_section, "this key"),
    (Qt.Key_Launch0, "Launch 0"),
    (Qt.Key_MediaTogglePlayPause, "Toggle Media Play Pause"),
])
@pytest.mark.parametrize("keypad", [False, True])
def test_mac_fallback_uses_words_or_this_key(key, expected, keypad):
    mods = Qt.ControlModifier | (Qt.KeypadModifier if keypad else Qt.NoModifier)
    seq = QKeySequence(QKeyCombination(mods, key))
    assert key_words(seq, "darwin") == (
        "Command+" + ("Keypad " if keypad else "") + expected)


@pytest.fixture
def window(qapp, monkeypatch):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow

    class FakeBackend:
        available = True

        def __init__(self, fire):
            self.fire = fire

        def register(self, seq):
            return None

        def unregister(self):
            pass

    make_app()
    monkeypatch.setattr(hotkey, "backend_class", lambda: FakeBackend)
    w = MainWindow()
    yield w
    w.hotkey.clear()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def no_key_glyphs(text):
    assert not any(ch in text for ch in "⌃⌥⇧⌘↩⌫⎋⇥←→↑↓⌦⌤␣⇞⇟↖↘")


MAC_ONLY = pytest.mark.skipif(sys.platform != "darwin", reason="macOS UI wording")


@MAC_ONLY
def test_front_page_line(window):
    assert window.welcome.key_row.text() == "Setting up the capture key…"
    assert window.capture_key_text() == ""
    window.apply_hotkey()
    text = window.welcome.key_row.text()
    assert "Capture from anywhere with Option+Shift+Space" in text
    no_key_glyphs(text)
    assert window.capture_key_text() == "Option+Shift+Space"


@MAC_ONLY
def test_capture_status(window):
    text = window.capture_status()
    assert text == "Command+N to take a screenshot"
    no_key_glyphs(text)


@MAC_ONLY
def test_empty_picture_hint(window):
    text = window.view.empty_hint[1]
    assert "Capture (Command+N)" in text
    no_key_glyphs(text)


@MAC_ONLY
def test_tooltip(window):
    text = window.a_copy.toolTip()
    assert text.endswith("(Command+C)")
    no_key_glyphs(text)
    assert window.a_copy.shortcut() == QKeySequence("Ctrl+C")


@MAC_ONLY
def test_help_shortcuts(window):
    window.apply_hotkey()
    text = shortcuts_markdown(window.shortcut_rows())
    assert "| Command+C | Copy image |" in text
    assert "| Option+Shift+Space | Capture from anywhere |" in text
    assert "Forward Delete" in text and "Escape" in text
    no_key_glyphs(text)


@MAC_ONLY
def test_assembled_help_includes_manual_in_words(window):
    from annotshot.help import HelpWindow, help_markdown
    manual = (Path(__file__).resolve().parents[1] / "docs" / "USER-MANUAL.md").read_text()
    text = help_markdown(window.shortcut_rows(), manual)
    assert not any(ch in text for ch in "⌃⌥⇧⌘↩⌫⎋⇥")
    assert "press Command+Space" in text
    assert "(Command+N on a Mac)" in text
    assert "Default on Mac: Option+Shift+Space. Default on Windows: Alt+Shift+Space." in text
    assert "(on a Mac: Control, Option, Shift or Command)" in text
    punctuation = dict(PUNCTUATION)
    for source in (manual, text):
        shortcuts = list(re.finditer(r"Ctrl\+([,\]\[=\-])", source))
        assert len(shortcuts) == 9
        for shortcut in shortcuts:
            word = punctuation[shortcut.group(1)]
            assert source[shortcut.end():].startswith(f" ({word})")
    help_window = HelpWindow(window.shortcut_rows(), window)
    try:
        assert not any(ch in help_window.browser.toPlainText() for ch in "⌃⌥⇧⌘↩⌫⎋⇥")
        assert "Command+Comma" in help_window.browser.toPlainText()
    finally:
        help_window.deleteLater()


@MAC_ONLY
def test_settings_tooltip_names_comma(window):
    assert window.a_settings.toolTip().endswith("(Command+Comma)")


def test_bare_letter_advice():
    expected = ("Use Control, Option, Shift or Command with the key (or an F key alone)"
                if sys.platform == "darwin" else
                "Use Ctrl, Alt or Shift with the key (or an F key alone)")
    assert hotkey.NEED_MODIFIER == expected
    assert hotkey.check(QKeySequence("A")) == expected


@MAC_ONLY
def test_action_clash_sentence(window):
    text = window.set_shortcut("open", QKeySequence("Ctrl+C"))
    assert text == "Command+C is already used by Copy image."
    no_key_glyphs(text)


@MAC_ONLY
@pytest.mark.parametrize("backend_type", [hotkey.MacBackend, hotkey.WinBackend])
def test_system_clash_sentence_without_native_registration(backend_type):
    # Bypass native initialization entirely; exercise each real refusal path.
    backend = backend_type.__new__(backend_type)
    if backend_type is hotkey.MacBackend:
        backend.register_code = lambda *args: -1
    else:
        backend._installed = True
        backend._user32 = SimpleNamespace(RegisterHotKey=lambda *args: 0)
    text = backend.register(QKeySequence("Alt+Shift+Space"))
    assert text == hotkey.TAKEN.format(key="Option+Shift+Space")
    no_key_glyphs(text)


@MAC_ONLY
def test_quick_copy_paste_hint(window, monkeypatch, white):
    from annotshot.capture import CaptureResult
    monkeypatch.setattr(window, "keep_recent", lambda: False)
    monkeypatch.setattr(window, "_show_again", lambda: None)
    window._capture_done(CaptureResult(white))
    text = window.statusBar().currentMessage()
    assert text.endswith("Command+V to paste")
    no_key_glyphs(text)


def test_saved_keys_remain_portable(window):
    seq = QKeySequence("Ctrl+Alt+9")
    assert window.set_shortcut("copy", seq) is None
    assert window.settings.value("shortcuts/copy") == "Ctrl+Alt+9"
    assert window.a_copy.shortcut() == seq
    assert window.set_hotkey(seq, False) is not None  # action owns it
    other = QKeySequence("Ctrl+Alt+8")
    assert window.set_hotkey(other, False) is None
    assert window.settings.value("hotkey/sequence") == "Ctrl+Alt+8"


@MAC_ONLY
@pytest.mark.parametrize("row,recorded", [("copy", "Ctrl+K"), ("hotkey", "Ctrl+L")])
def test_settings_words_preserve_recording_set_reset_and_clear(window, row, recorded):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QToolButton
    from annotshot.settings_dialog import SettingsDialog

    page = SettingsDialog(window)
    try:
        edit = page.hotkey_edit if row == "hotkey" else page.edits[row]
        line = field_parts(edit)[0]
        default = QKeySequence(hotkey.DEFAULT if row == "hotkey" else "Ctrl+C")
        assert line.text() == key_words(default)
        seq = QKeySequence("Ctrl+Alt+9")
        edit.setKeySequence(seq)
        assert line.text() == "Option+Command+9"
        assert edit.keySequence() == seq
        commit = page.commit_hotkey if row == "hotkey" else lambda: page.commit(row)
        reset = page.reset_hotkey if row == "hotkey" else lambda: page.reset(row)
        assert commit() is None
        setting = "hotkey/sequence" if row == "hotkey" else "shortcuts/copy"
        assert window.settings.value(setting) == "Ctrl+Alt+9"
        assert reset() is None
        assert edit.keySequence() == default
        assert line.text() == key_words(default)
        edit.clear()
        assert edit.keySequence().isEmpty() and line.text() == ""
        # A held key already has words; recording and commit still use Qt data.
        key = Qt.Key_L if row == "hotkey" else Qt.Key_K
        QTest.keyPress(edit, Qt.Key_Control)
        QTest.keyPress(edit, key, Qt.ControlModifier)
        assert edit.keySequence() == QKeySequence(recorded)
        assert line.text() == key_words(QKeySequence(recorded))
        no_key_glyphs(line.text())
        QTest.keyRelease(edit, key, Qt.ControlModifier)
        QTest.keyRelease(edit, Qt.Key_Control)
        assert edit.keySequence() == QKeySequence(recorded)
        assert line.text() == key_words(QKeySequence(recorded))
        assert window.settings.value(setting) == recorded
        # Exercise the real inner clear button, then record another new key.
        clear_button = field_parts(edit)[1]
        assert clear_button is not None
        clear_button.click()
        assert line.text() == "" and edit.keySequence().isEmpty()
        QTest.keyPress(edit, Qt.Key_J, Qt.AltModifier)
        assert line.text() == "Option+J"
        QTest.keyRelease(edit, Qt.Key_J, Qt.AltModifier)
        assert edit.keySequence() == QKeySequence("Alt+J")
        assert line.text() == "Option+J"
        assert window.settings.value(setting) == "Alt+J"
        page._reset_all()
        assert line.text() == key_words(default)
        assert edit.keySequence() == default
    finally:
        page.deleteLater()
