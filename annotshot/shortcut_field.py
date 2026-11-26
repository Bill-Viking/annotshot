"""One physical chord per base-down, with the s38 B keycap presentation.

The owner alone changes a binding. Input retirement and the painter's down
mask are separate: releasing a saved cap can never submit another chord.
"""
from __future__ import annotations

import math
import sys
import weakref
from dataclasses import dataclass

from shiboken6 import isValid
from PySide6.QtCore import QCoreApplication, QEvent, QKeyCombination, QObject, QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QContextMenuEvent, QFontMetricsF, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLineEdit, QSizePolicy, QStyle, QStyleOptionFrame, QToolButton, QWidget

from . import theme
from .keywords import key_words

_CTRL, _ALT, _SHIFT, _META, _PAD = (Qt.ControlModifier, Qt.AltModifier,
                                    Qt.ShiftModifier, Qt.MetaModifier, Qt.KeypadModifier)
_MODIFIERS = {Qt.Key_Control: _CTRL, Qt.Key_Alt: _ALT,
              Qt.Key_Shift: _SHIFT, Qt.Key_Meta: _META, Qt.Key_AltGr: Qt.GroupSwitchModifier,
              Qt.Key_Super_L: _META, Qt.Key_Super_R: _META,
              Qt.Key_Hyper_L: _META, Qt.Key_Hyper_R: _META}
_IDENTITIES = {_CTRL: Qt.Key_Control, _ALT: Qt.Key_Alt,
               _SHIFT: Qt.Key_Shift, _META: Qt.Key_Meta}
_PORTABLE = QKeySequence.PortableText


def _classify(event, composition, altgr):
    """Pure ownership decision, shared by override and actual key delivery."""
    key, flags = event.key(), event.modifiers()
    if key in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape) or event.matches(QKeySequence.Cancel):
        return 'qt', None
    if key in _MODIFIERS:
        return 'modifier', None
    if (key == Qt.Key_Menu or key == Qt.Key_F10 and flags == _SHIFT
            or key in (Qt.Key_CapsLock, Qt.Key_NumLock, Qt.Key_ScrollLock)):
        return 'retire', None
    if key == Qt.Key_Multi_key:
        return 'compose', None
    if 0x01001250 <= key <= 0x010012ff:
        return composition if composition in ('preedit', 'compose') else 'dead', None
    if (0x01001120 <= key <= 0x0100117f or key in (0, Qt.Key_unknown)):
        return ('composing' if composition in ('preedit', 'compose') else 'retire'), None
    function = Qt.Key_F1 <= key <= Qt.Key_F35
    if (flags & Qt.GroupSwitchModifier or altgr) and not function:
        return 'composing', None
    independent = bool(flags & (_CTRL | _ALT | _META)) or function
    if composition in ('preedit', 'compose') and not independent:
        return 'composing', None
    if (composition == 'dead' and not independent and 0 < key <= 0x10ffff
            and chr(key).isprintable()):
        return 'continuation', None
    seq = QKeySequence(QKeyCombination(flags, Qt.Key(key)))
    if seq.isEmpty() or QKeySequence.fromString(seq.toString(_PORTABLE), _PORTABLE) != seq:
        return 'retire', None
    return 'base', seq


def _ordered_modifiers():
    mac_words = key_words(QKeyCombination(_CTRL, Qt.Key_K)) == 'Command+K'
    return (_META, _ALT, _SHIFT, _CTRL) if mac_words else (_META, _CTRL, _ALT, _SHIFT)


def _parts(sequence):
    """Structured parts. A literal plus and a keypad qualifier stay intact."""
    result = []
    for chord in range(sequence.count()):
        combo = sequence[chord]
        flags = combo.keyboardModifiers()
        parts = []
        for flag in _ordered_modifiers():
            if flags & flag:
                word = key_words(QKeyCombination(flag, Qt.Key_K)).removesuffix('+K')
                parts.append((chord, _IDENTITIES[flag], word))
        base = key_words(QKeyCombination(flags & _PAD, combo.key()))
        parts.append((chord, combo.key(), base))
        full = key_words(QKeySequence(combo))
        # Loading is total, including a chord whose portable spelling is empty.
        # The formatter owns the words; an unreadable chord is one raised cap.
        if not base or any(not part[2] for part in parts) or '+'.join(part[2] for part in parts) != full:
            parts = [(chord, combo.key(), full)]
        result.extend(parts)
    return tuple(result)


def _physical(event):
    """Physical identity, never a layout-dependent interpretation of its word."""
    if event.nativeScanCode():
        return ('scan', event.nativeScanCode())
    pad = bool(event.modifiers() & _PAD)
    if event.nativeVirtualKey() and event.nativeVirtualKey() != Qt.Key_unknown:
        return ('virtual', event.nativeVirtualKey())
    return ('logical', event.key(), pad)


def _altgr_all_up():
    """Affirmative native release evidence, or None when not verified.

    No shipping backend has yet proved that its physical-modifier query
    reports held AltGr as GroupSwitch or Ctrl+Alt. Until then, only a
    uniquely matched release retires a press. Never infer release from text.
    """
    return None


class _Downs(QObject):
    """One owner-lifetime record of unresolved field-originating downs.

    Outside a field this observes only releases, within this Settings owner.
    Retirement of a presentation never supplies evidence of a physical up.
    """
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.records = {}
        self.fields = weakref.WeakSet()
        QApplication.instance().installEventFilter(self)

    @property
    def altgr(self):
        return any(record[0] == Qt.Key_AltGr for record in self.records.values())

    def matching(self, event):
        """Prefer a scan; a unique remaining native id may bridge a lost id.

        Original identifiers stay on the one down record. Two known scans
        never merge. An ambiguous edge supplies no release evidence.
        """
        scan, virtual = event.nativeScanCode(), event.nativeVirtualKey()
        if virtual == Qt.Key_unknown:
            virtual = 0
        if scan:
            exact = [token for token, record in self.records.items() if record[2] == scan]
            if exact:
                return exact
        pad = bool(event.modifiers() & _PAD)
        result = []
        for token, (key, keypad, old_scan, old_virtual) in self.records.items():
            if scan and old_scan:  # distinguishable physical siblings
                continue
            if virtual and old_virtual:
                compatible = virtual == old_virtual
            else:
                compatible = key == event.key() and keypad == pad
            if compatible:
                result.append(token)
        return result

    def press(self, event):
        physical = _physical(event)
        key, pad = event.key(), bool(event.modifiers() & _PAD)
        if self.matching(event):
            return None
        virtual = event.nativeVirtualKey()
        self.records[physical] = (key, pad, event.nativeScanCode(),
                                  0 if virtual == Qt.Key_unknown else virtual)
        return physical

    def modifier_count(self, modifier):
        return sum(_MODIFIERS.get(record[0]) == modifier for record in self.records.values())

    def reconcile(self, flags):
        for physical, (key, *_rest) in tuple(self.records.items()):
            if key in _MODIFIERS and key != Qt.Key_AltGr and not flags & _MODIFIERS[key]:
                del self.records[physical]

    def _owns(self, widget):
        # QWidget.isAncestorOf stops at a child window. Settings is a QDialog;
        # its parentWidget chain still reaches the persistent Settings owner.
        while widget is not None:
            if widget is self.owner:
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.KeyRelease and not event.isAutoRepeat()
                and isinstance(watched, QWidget) and isValid(self.owner)
                and self._owns(watched)):
            matches = self.matching(event)
            physical = matches[0] if len(matches) == 1 else _physical(event)
            matched = self.records.pop(physical, None) if len(matches) == 1 else None
            # ASSUMES: only a unique physical match identifies a sibling.
            # Opposite: shared virtual id with two scans; unavailable all-up.
            if (event.key() == Qt.Key_AltGr and len(matches) > 1
                    and self.altgr and _altgr_all_up() is True):
                for token, (key, *_rest) in tuple(self.records.items()):
                    if key == Qt.Key_AltGr:
                        del self.records[token]
            flags = event.modifiers()
            if event.key() in _MODIFIERS:
                modifier = _MODIFIERS[event.key()]
                flags = flags | modifier if self.modifier_count(modifier) else flags & ~modifier
            self.reconcile(flags)
            for field in tuple(self.fields):
                if isValid(field):
                    field._release(event, physical, matched is not None)
        return False


@dataclass(frozen=True)
class _Face:
    keys: tuple
    breaks: tuple


# These drawing helpers port look-s38/render_look.py's B branch. No docs import.
def _rounded(p, rect, fill, stroke=None, width=1, radius=3):
    p.setBrush(QColor(fill) if fill else Qt.NoBrush)
    p.setPen(QPen(QColor(stroke), width) if stroke else Qt.NoPen)
    inset = width / 2 if stroke else 0
    p.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), radius, radius)


def _ink(p, rect, word, font, color, center=True, dy=0):
    fm = QFontMetricsF(font)
    x = rect.center().x() - fm.horizontalAdvance(word) / 2 if center else rect.left()
    y = rect.center().y() + (fm.ascent() - fm.descent()) / 2 + dy
    p.setPen(QColor(color))
    p.setFont(font)
    p.drawText(QPointF(x, y), word)


def _folded_initial(p, inner, box, key, font, fg, down):
    fm = QFontMetricsF(font)
    first = key[:1] or "…"
    scale = min(1., (inner.width() - .5) / fm.horizontalAdvance(first))
    p.save()
    p.translate(inner.center().x(), 0)
    p.scale(scale, 1)
    rect = QRectF(-inner.width() / scale / 2, inner.top(),
                  inner.width() / scale, inner.height() - 3)
    _ink(p, rect, first, font, fg, dy=.5 if down else 0)
    p.restore()
    if first != key:
        for dx in (-1.6, 0, 1.6):
            p.fillRect(QRectF(inner.center().x() + dx - .5, box.bottom() - 4, 1, 1), QColor(fg))


def _fitted(word, fm, width):
    if fm.horizontalAdvance(word) <= width:
        return word
    return fm.elidedText(word, Qt.ElideMiddle, max(0, math.floor(width)))


def _layout(face, fm, space):
    normal = [fm.horizontalAdvance(word) + 8 for word in face.keys]
    joins = [0 if i == 0 else fm.horizontalAdvance(', ') if i in face.breaks else 3
             for i in range(len(normal))]
    if sum(normal) + sum(joins) <= space:
        return normal, joins, False, 4
    compact = [n - 4 for n in normal]
    gaps = [min(join, 2) if i not in face.breaks else join for i, join in enumerate(joins)]
    if sum(compact) + sum(gaps) <= space:
        return compact, gaps, False, 2
    joins = [0] + [3 if i in face.breaks else 1 for i in range(1, len(normal))]
    available = space - sum(joins)
    if len(normal) <= 6 and space < 14 * len(normal):
        initials = [fm.horizontalAdvance(word[:1] or "…") + 2 for word in face.keys]
        return [available * n / sum(initials) for n in initials], joins, True, -1
    unit = min(5, available / len(normal))
    widths = [min(unit, n) for n in normal]
    widths[-1] = min(normal[-1], max(widths[-1], min(available / 2, available - sum(widths[:-1]))))
    left = available - sum(widths)
    while left > .001:
        ids = [i for i, width in enumerate(widths) if width + .001 < normal[i]]
        if not ids:
            break
        step = left / len(ids)
        for i in ids:
            add = min(step, normal[i] - widths[i])
            widths[i] += add
            left -= add
    return widths, joins, True, 1


class ShortcutField(QLineEdit):
    chordEntered = Signal(object)
    guidanceChanged = Signal(str)

    def __init__(self, sequence=QKeySequence(), parent=None, *, owner=None):
        super().__init__(parent)
        self._sequence = QKeySequence(sequence)
        self._cleared = False
        self._local_modifiers = set()
        self._explicit_owner = owner
        self._presses = None
        self._bind_owner(owner or self.window())
        self._lit_base = None
        self._presentation_serial = 0
        self._composition = None
        self._down = set()
        self._generation = 0
        self._submission = None
        self._guide = ''
        self._preview_ticket = None
        self._preview_expiry = QTimer(self)
        self._preview_expiry.setObjectName('shortcutPreviewExpiry')
        self._preview_expiry.setSingleShot(True)
        self._preview_expiry.setInterval(1500)
        self._preview_callback = None
        self._hover = False
        self._window_active = True
        self._observed_window = None
        self._paint_parts = ()
        self._paint_slots = ()
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setAcceptDrops(False)
        self.setCursor(Qt.ArrowCursor)
        self.setPlaceholderText(QCoreApplication.translate('QKeySequenceEdit', 'Press shortcut'))
        self._clear_action = self.addAction(self.style().standardIcon(QStyle.SP_LineEditClearButton),
                                             QLineEdit.TrailingPosition)
        self._clear_button = next(b for b in self.findChildren(QToolButton)
                                  if b.defaultAction() is self._clear_action)
        self._clear_button.setFocusPolicy(Qt.NoFocus)
        self._clear_action.triggered.connect(self._clear_display)
        QApplication.instance().applicationStateChanged.connect(self._application_state)
        self._ready = True
        self._present()

    def _bind_owner(self, owner):
        record = getattr(owner, '_shortcut_field_downs', None)
        if record is None:
            record = _Downs(owner)
            owner._shortcut_field_downs = record
        if self._presses is not None:
            self._presses.fields.discard(self)
        self._presses = record
        record.fields.add(self)

    def keySequence(self):
        return QKeySequence() if self._cleared else QKeySequence(self._sequence)

    def setKeySequence(self, sequence):
        """Authoritative presentation; never an input, even for legacy keys."""
        submission = self._submission
        # ASSUMES: only the submitted chord (or the owner's existing keypad
        # normalization) can be its synchronous echo. Opposite: F8 dispatch,
        # independent F9 publication, then the original F8 receipt.
        echo = False
        if (submission is not None and submission['dispatched']
                and submission['generation'] == self._generation):
            origin = submission['origin']
            combo = origin[0]
            normalized = QKeySequence(QKeyCombination(
                combo.keyboardModifiers() & ~_PAD, combo.key()))
            echo = sequence == origin or sequence == normalized
        if not echo:
            self._generation += 1
        self._presentation_serial += 1
        self._sequence = QKeySequence(sequence)
        self._cleared = False
        self._local_modifiers.clear()
        self._down.clear()
        self._lit_base = None
        self._stop_preview()
        self._present()

    def settleChord(self, sequence: QKeySequence, taken: bool, *, origin=None) -> None:
        receipt = sequence if origin is None else origin
        submission = self._submission
        if (submission is None or submission['settled']
                or submission['origin'] is not receipt
                or submission['generation'] != self._generation):
            return
        submission['settled'] = True
        serial = self._presentation_serial + 1
        self.setKeySequence(sequence)
        # Presentation can deliver an up, retire/destroy the field, publish a
        # different value or synchronously enter an entirely newer press.
        if (isValid(self) and self._submission is submission
                and submission['generation'] == self._generation
                and self._presentation_serial == serial and not self._cleared
                and self._sequence == sequence and taken):
            self._down = set(submission['down'])
            self._lit_base = (submission['physical'], submission['base'])
            self._present()

    def clearButton(self):
        return self._clear_button

    def clear(self):
        if self._clear_action.isVisible() and self.isEnabled():
            self._clear_action.trigger()

    def _clear_display(self):
        self.endInput('clear')
        self._cleared = True
        self.setFocus(Qt.MouseFocusReason)
        self._present()

    def hasUnfinishedInput(self):
        return bool(self._cleared or self._local_modifiers or self._composition)

    def endInput(self, reason):
        self._generation += 1
        self._cleared = False
        self._local_modifiers.clear()
        self._composition = None
        self._down.clear()
        self._lit_base = None
        self._stop_preview()
        self._present()

    def _guidance(self, text):
        if text != self._guide:
            self._guide = text
            self.setAccessibleDescription(text)
            self.guidanceChanged.emit(text)

    def _stop_preview(self):
        self._preview_ticket = None
        self._preview_expiry.stop()
        self._guidance('')

    def _preview(self, flags):
        """Only distinct modifier transitions renew the visual lease."""
        # Track the families this lease actually displays, including a
        # modifier held across the end of a previous mixed preview.
        self._local_modifiers = {key for flag, key in _IDENTITIES.items() if flags & flag}
        self._preview_expiry.stop()
        if self._preview_callback is not None:
            self._preview_expiry.timeout.disconnect(self._preview_callback)
        ticket = object()
        self._preview_ticket = ticket
        generation = self._generation
        def expire():
            if (not isValid(self) or self._preview_ticket is not ticket
                    or self._generation != generation or not self.hasFocus()):
                return
            self._preview_ticket = None
            self._local_modifiers.clear()
            self._down.clear()
            self._present()
            if (isValid(self) and self._preview_ticket is None
                    and self._generation == generation and not self._local_modifiers):
                self._guidance('Hold a modifier and press another key.')
        self._preview_callback = expire
        self._preview_expiry.timeout.connect(expire)
        self._preview_expiry.start()
        words = [key_words(QKeyCombination(flag, Qt.Key_K)).removesuffix('+K')
                 for flag in _ordered_modifiers() if flags & flag]
        if flags == _SHIFT and self._presses.modifier_count(_SHIFT) > 1:
            guide = 'Both Shift keys are down. Add another key.'
        else:
            guide = f"Hold {' + '.join(words)} and press another key, such as A."
        self._guidance(guide)
        if (isValid(self) and self._preview_ticket is ticket
                and self._generation == generation and self._local_modifiers):
            self._present(flags)

    def _present(self, preview=None):
        # Qt can destroy the trailing action before a final hide/focus event.
        # There is no remaining presentation to update during that teardown.
        if not isValid(self) or not isValid(self._clear_action):
            return
        if preview is not None:
            parts = tuple((0, _IDENTITIES[flag],
                           key_words(QKeyCombination(flag, Qt.Key_K)).removesuffix('+K'))
                          for flag in _ordered_modifiers() if preview & flag)
            mode = 'preview'
        else:
            parts = () if self._cleared else _parts(self._sequence)
            mode = 'saved'
        self._paint_parts = tuple((chord, identity, word, mode,
                                   self.isEnabled() and (mode == 'preview' or identity in self._down))
                                  for chord, identity, word in parts)
        text = ''.join((', ' if i and chord != parts[i-1][0] else '+' if i else '') + word
                       for i, (chord, _, word) in enumerate(parts))
        QLineEdit.setText(self, text)
        self._clear_action.setVisible(not self._cleared and not self._sequence.isEmpty())
        self.update()

    def _reconcile(self, flags, released=None):
        """Reliable flags may extinguish lights; they cannot create one."""
        missing = {identity for flag, identity in _IDENTITIES.items() if not flags & flag}
        if released is not None:
            missing.add(released)
        self._presses.reconcile(flags)
        self._down.difference_update(missing)
        if self._submission is not None:
            self._submission['down'].difference_update(missing)
        self._local_modifiers = {key for key in self._local_modifiers
                                 if flags & _MODIFIERS[key] and key != released}

    def _release(self, event, physical, matched):
        if not self._down and not self._local_modifiers and self._submission is None:
            return
        key, flags = event.key(), event.modifiers()
        modifier = _MODIFIERS.get(key)
        if modifier is not None:
            surviving = self._presses.modifier_count(modifier)
            flags = flags | modifier if surviving else flags & ~modifier
        else:
            surviving = False
        previous = set(self._local_modifiers)
        self._reconcile(flags, _IDENTITIES.get(modifier) if not surviving else None)
        before_families = {_MODIFIERS[k] for k in previous}
        after_families = {_MODIFIERS[k] for k in self._local_modifiers}
        if len(before_families) > 1 and before_families - after_families:
            # Retire only this visual lease. Surviving physical presses stay
            # in the owner's record and may finish a chord on a fresh base.
            self._local_modifiers.clear()
            self._down.clear()
            self._stop_preview()
            self._present()
            self._guidance('Hold a modifier and press another key.')
            return
        if modifier is None:
            # An up for a known sibling cannot raise the active base. An
            # unpairable up raises uncertain paint but leaves suppression.
            if self._lit_base is not None and (physical == self._lit_base[0] or not matched):
                self._down.discard(self._lit_base[1])
            submission = self._submission
            if submission is not None and (physical == submission['physical'] or not matched):
                submission['down'].discard(submission['base'])
        if self._local_modifiers:
            if modifier is not None and (matched or previous != self._local_modifiers):
                self._preview(flags)
            else:
                self._present(flags)
        else:
            if previous:
                words = [key_words(QKeyCombination(flag, Qt.Key_K)).removesuffix('+K')
                         for flag in _ordered_modifiers() if flag in before_families]
                self._stop_preview()
                name = ' + '.join(words)
                self._guidance(f'{name} needs another key. Try {name} + A.')
            self._present()

    def _submit(self, sequence, key, flags, physical):
        self._generation += 1
        self._cleared = False
        self._local_modifiers.clear()
        self._down.clear()
        self._lit_base = None
        entered = QKeySequence(sequence)
        submission = dict(generation=self._generation, settled=False, dispatched=False, origin=entered,
                          physical=physical, base=key,
                          down={key} | {identity for flag, identity in _IDENTITIES.items() if flags & flag})
        self._submission = submission
        try:
            self._stop_preview()
            if (not isValid(self) or self._submission is not submission
                    or self._generation != submission['generation']):
                return
            self._present()
            if (not isValid(self) or self._submission is not submission
                    or self._generation != submission['generation']):
                return
            submission['dispatched'] = True
            self.chordEntered.emit(entered)
        finally:
            if isValid(self) and self._submission is submission:
                if not submission['settled']:
                    self._down.clear()
                    self._present()
                self._submission = None

    def event(self, event):
        if not getattr(self, '_ready', False):
            return super().event(event)
        kind = event.type()
        if kind in (QEvent.ShortcutOverride, QEvent.KeyPress):
            if not self.isEnabled():
                event.ignore()
                return True
            decision, sequence = _classify(event, self._composition, self._presses.altgr)
            if kind == QEvent.ShortcutOverride:
                if decision == 'qt':
                    event.ignore()
                else:
                    event.accept()
                return True
            if decision == 'qt':
                self._presses.reconcile(event.modifiers())
                self.endInput('navigation')
                # ASSUMES: Qt offers this ignored original press to the parent.
                # Opposite cases: modified Tab which stays, and Escape after X.
                event.ignore()
                return True
            event.accept()
            if event.isAutoRepeat():
                return True
            key, flags = event.key(), event.modifiers()
            if decision in ('modifier', 'base'):
                if decision == 'modifier':
                    flags |= _MODIFIERS[key]
                self._reconcile(flags)
                physical = self._presses.press(event)
                if physical is None:
                    self._present(flags if self._local_modifiers else None)
                    return True
                if decision == 'modifier':
                    if key == Qt.Key_AltGr:
                        # AltGr is not a composition terminal or a new value.
                        # Its unspellable preview also keeps an independent ×.
                        self._generation += 1
                        self._local_modifiers.clear()
                        self._down.clear()
                        self._lit_base = None
                        self._stop_preview()
                        self._present()
                        return True
                    self._local_modifiers.add(key)
                    self._down.clear()
                    self._preview(flags)
                else:
                    self._submit(sequence, key, flags, physical)
            elif decision == 'composing':
                self._presses.reconcile(flags)
                # Preserve the source guard through candidate controls/text.
                self._generation += 1
                self._local_modifiers.clear()
                self._down.clear()
                self._lit_base = None
                self._stop_preview()
                self._present()
            else:
                self._presses.reconcile(flags)
                self.endInput('composition')
                if decision in ('dead', 'compose', 'preedit'):
                    self._composition = decision
            return True
        if kind == QEvent.KeyRelease:
            # The shared owner's passive release observer has already retired
            # this edge, including ups delivered to a sibling or later dialog.
            event.accept()
            return True
        if kind == QEvent.InputMethod:
            self.endInput('composition')
            if event.preeditString():
                self._composition = 'preedit'
            event.accept()
            return True
        if kind in (QEvent.WindowDeactivate, QEvent.ApplicationDeactivate):
            self._window_active = False
            self.endInput('deactivation')
        elif kind == QEvent.WindowActivate:
            self._window_active = True
            self.update()
        elif kind == QEvent.Enter:
            self._hover = True
            self.update()
        elif kind == QEvent.Leave:
            self._hover = False
            self.update()
        elif kind == QEvent.EnabledChange and not self.isEnabled():
            self.endInput('disabled')
        elif kind == QEvent.ContextMenu:
            if event.reason() == QContextMenuEvent.Keyboard:
                self.endInput('context')
            event.accept()
            return True
        elif kind in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            event.ignore()
            return True
        return super().event(event)

    def _application_state(self, state):
        if state != Qt.ApplicationActive:
            self._window_active = False
            self.endInput('deactivation')
        else:
            self._window_active = True
            self.update()

    def eventFilter(self, watched, event):
        # Window lifetime only. Every key is classified in event(), nowhere else.
        if event.type() in (QEvent.WindowDeactivate, QEvent.Hide, QEvent.Close):
            if event.type() == QEvent.WindowDeactivate:
                self._window_active = False
            self.endInput('window')
        elif event.type() == QEvent.WindowActivate:
            self._window_active = True
            self.update()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        window = self.window()
        if self._explicit_owner is None and self._presses.owner is not window:
            self._bind_owner(window)
        if window is not self and window is not self._observed_window:
            if self._observed_window is not None and isValid(self._observed_window):
                self._observed_window.removeEventFilter(self)
            window.installEventFilter(self)
            self._observed_window = window
        super().showEvent(event)

    def focusOutEvent(self, event):
        self.endInput('blur')
        super().focusOutEvent(event)

    def hideEvent(self, event):
        self.endInput('hide')
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if not self._local_modifiers:
            self._guidance('')
        self.setFocus(Qt.MouseFocusReason)
        event.accept()

    mouseDoubleClickEvent = mousePressEvent

    def mouseMoveEvent(self, event):
        event.accept()

    # Programmatic text editing has no path into the presentation or binding.
    def setText(self, text):
        pass

    def insert(self, text):
        pass

    def paste(self):
        pass

    def cut(self):
        pass

    def undo(self):
        pass

    def redo(self):
        pass

    def selectAll(self):
        pass

    def setSelection(self, start, length):
        pass

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t, font = theme.tokens(theme.current()), theme.font(theme.current())
        fm = QFontMetricsF(font)
        w, h = self.width(), self.height()
        frame = QRectF(0, 0, w, h)
        opt = QStyleOptionFrame()
        self.initStyleOption(opt)
        opt.state &= ~(QStyle.State_HasFocus | QStyle.State_MouseOver | QStyle.State_ReadOnly)
        self.style().drawPrimitive(QStyle.PE_PanelLineEdit, opt, p, self)
        enabled = self.isEnabled()
        focus = enabled and self.hasFocus() and self._window_active and self.isActiveWindow()
        hover = enabled and self._hover
        if focus or hover:
            _rounded(p, frame, None, t['link' if focus else 'field-hover'], 2 if focus else 1, 2)
        clear = self._clear_action.isVisible()
        right = self._clear_button.x() - 2 if clear else w - 4
        content = QRectF(4, 2, right - 4, h - 4)
        parts = self._paint_parts
        keys = tuple(part[2] for part in parts)
        breaks = tuple(i for i in range(1, len(parts)) if parts[i][0] != parts[i-1][0])
        face = _Face(keys, breaks)
        if keys:
            widths, joins, short, inset = _layout(face, fm, content.width())
        else:
            widths, joins, short, inset = [], [], False, 0
            entry = content.adjusted(4 if focus else 0, 0, 0, 0)
            _ink(p, entry, _fitted(self.placeholderText(), fm, entry.width()), font, t['text-dim'], False)
        x, slots = content.x(), []
        for i, (part, span, join) in enumerate(zip(parts, widths, joins)):
            _, _, key, mode, lit = part
            down = lit and enabled
            if join and not short and i in breaks:
                _ink(p, QRectF(x, 2, join, h-4), ', ', font, t['text-dim'])
            if short and i in breaks:
                p.fillRect(QRectF(x+1, h/2-2, 1, 4), QColor(t['text-dim']))
            x += join
            box = QRectF(x, 3, span, h-6)
            slots.append((box.x(), box.y(), box.width(), box.height()))
            preview = mode == 'preview' and enabled
            fg = t['text-disabled'] if not enabled else t['text']
            pad = min(.75 if inset == -1 else inset, span * .24) if short else inset
            if preview:
                fg = t['link']
                pen = QPen(QColor(fg), 1)
                pen.setDashPattern([2, 2])
                p.setBrush(QColor(t['accent-soft']))
                p.setPen(pen)
                p.drawRoundedRect(box.adjusted(.5, 1.5, -.5, -.5), 3, 3)
            else:
                border = t['border'] if not enabled else t['text-dim']
                _rounded(p, box.adjusted(0, 1 if down else 0, 0, 0),
                         t['link' if down else 'surface-2'], t['link'] if down else border, 1, 3)
                if down:
                    fg = t['surface']
                else:
                    p.fillRect(QRectF(x+2, box.bottom()-2, max(0, span-4), 1), QColor(border))
            inner = box.adjusted(pad, 0, -pad, 0)
            if inset == -1:
                _folded_initial(p, inner, box, key, font, fg, down)
                x += span
                continue
            display = _fitted(key, fm, inner.width())
            micro = short and display != key and (i != len(widths)-1 or display in ('', '…'))
            if micro:
                display = ''
                for end in range(1, len(key)+1):
                    if fm.horizontalAdvance(key[:end])+5 > inner.width():
                        break
                    display = key[:end]
                if display:
                    _ink(p, inner.adjusted(0, 0, -5, 0), display, font, fg, False)
                    dots_x = inner.left()+fm.horizontalAdvance(display)+1
                    for j in range(3):
                        p.fillRect(QRectF(dots_x+j*1.5, inner.center().y()+3, 1, 1), QColor(fg))
            if display.strip() and not micro:
                _ink(p, inner, display, font, fg, dy=1 if down else 0)
            elif micro and not display and inner.width() >= 6.5:
                _folded_initial(p, inner, box, key, font, fg, down)
                x += span
                continue
            elif not display.strip():
                dots = min(5, inner.width())
                for j in range(3):
                    p.fillRect(QRectF(inner.center().x()-dots/2+j*dots/3,
                                      inner.center().y(), dots/5, 1), QColor(fg))
            x += span
        self._paint_slots = tuple(slots)
        if focus and not any(part[4] for part in parts):
            caret = min(x+2, self._clear_button.x()-1.5 if clear else w-4-1.5) if keys else content.left()
            p.fillRect(QRectF(caret, h/2-7, 1.5, 14), QColor(t['link']))
        p.end()
