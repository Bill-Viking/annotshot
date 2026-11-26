"""The words used to show a keyboard shortcut to a person.

Shortcut storage and QAction shortcuts still use Qt's own sequences.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeySequence


_MAC_KEYS = {
    Qt.Key_Space: "Space",
    Qt.Key_Return: "Return",
    Qt.Key_Backspace: "Delete",
    Qt.Key_Delete: "Forward Delete",
    Qt.Key_Escape: "Escape",
    Qt.Key_Tab: "Tab",
    Qt.Key_Left: "Left Arrow",
    Qt.Key_Right: "Right Arrow",
    Qt.Key_Up: "Up Arrow",
    Qt.Key_Down: "Down Arrow",
    Qt.Key_PageUp: "Page Up",
    Qt.Key_PageDown: "Page Down",
    Qt.Key_Home: "Home",
    Qt.Key_End: "End",
    Qt.Key_Exclam: "Exclamation Mark",
    Qt.Key_QuoteDbl: "Double Quote",
    Qt.Key_NumberSign: "Number Sign",
    Qt.Key_Dollar: "Dollar",
    Qt.Key_Percent: "Percent",
    Qt.Key_Ampersand: "Ampersand",
    Qt.Key_ParenLeft: "Left Parenthesis",
    Qt.Key_ParenRight: "Right Parenthesis",
    Qt.Key_Asterisk: "Asterisk",
    Qt.Key_Comma: "Comma",
    Qt.Key_Period: "Period",
    Qt.Key_Plus: "Plus",
    Qt.Key_Minus: "Minus",
    Qt.Key_Equal: "Equals",
    Qt.Key_Slash: "Slash",
    Qt.Key_Backslash: "Backslash",
    Qt.Key_Semicolon: "Semicolon",
    Qt.Key_Colon: "Colon",
    Qt.Key_Less: "Less Than",
    Qt.Key_Greater: "Greater Than",
    Qt.Key_Question: "Question Mark",
    Qt.Key_At: "At Sign",
    Qt.Key_Apostrophe: "Quote",
    Qt.Key_BracketLeft: "Left Bracket",
    Qt.Key_BracketRight: "Right Bracket",
    Qt.Key_QuoteLeft: "Grave Accent",
    Qt.Key_AsciiCircum: "Caret",
    Qt.Key_Underscore: "Underscore",
    Qt.Key_BraceLeft: "Left Brace",
    Qt.Key_Bar: "Vertical Bar",
    Qt.Key_BraceRight: "Right Brace",
    Qt.Key_AsciiTilde: "Tilde",
}
_MAC_MODIFIERS = (
    (Qt.MetaModifier, "Control"),
    (Qt.AltModifier, "Option"),
    (Qt.ShiftModifier, "Shift"),
    (Qt.ControlModifier, "Command"),
)


def key_words(seq: QKeySequence | QKeyCombination,
              platform: str = sys.platform) -> str:
    """Display a sequence, spelling out macOS key glyphs and Qt's Ctrl swap."""
    if isinstance(seq, QKeyCombination) and seq == QKeyCombination():
        return ""
    seq = QKeySequence(seq)
    if seq.isEmpty():
        return ""
    if platform != "darwin":
        return seq.toString(QKeySequence.PortableText)
    chords = []
    for i in range(seq.count()):
        combo = seq[i]
        words = [name for modifier, name in _MAC_MODIFIERS
                 if combo.keyboardModifiers() & modifier]
        key = _MAC_KEYS.get(combo.key())
        if key is None:
            key = QKeySequence(combo.key()).toString(QKeySequence.PortableText)
            key = " ".join("".join(
                ch if ch.isascii() and ch.isalnum() else " "
                for ch in key).split()) or "this key"
        if key:
            if combo.keyboardModifiers() & Qt.KeypadModifier:
                key = f"Keypad {key}"
            words.append(key)
        chords.append("+".join(words))
    return ", ".join(chords)
