from key_field_support import field_parts, FocusOutWitness
"""s35/s36: real focus traversal, on s33's isolated native/storage rig."""
import json
import os
import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit, QToolButton

import test_s33_settings_key_field as s33
from test_s33_settings_key_field import rig
from annotshot import hotkey

# Known on Windows only (os.name is not patched by the platform rig). strict: a pass is flagged.
WINDOWS_KNOWN = pytest.mark.xfail(os.name == 'nt', strict=True, reason='0.4.4 public check 2: fails on a Windows host with the offscreen display; not yet traced on Windows')


@pytest.fixture(params=['darwin', 'win32'], ids=['Mac', 'Windows'])
def case(request):
    return s33.Case(7, request.param, 'D', 'i_focus')


def key(rig, kind, code, mods=Qt.NoModifier):
    target = QApplication.focusWidget()
    assert target is not None
    getattr(QTest, kind)(target, code, mods)
    rig.qapp.processEvents()


def place(rig, widget):
    widget.setFocus()
    rig.qapp.processEvents()
    assert QApplication.focusWidget() is widget


def order(rig, page):
    """The dialog's own forward order is the backward-traversal oracle."""
    place(rig, page.tabs.tabBar())
    result = [QApplication.focusWidget()]
    for _ in range(160):
        key(rig, 'keyClick', Qt.Key_Tab)
        target = QApplication.focusWidget()
        if target is result[0]:
            break
        assert target not in result
        result.append(target)
    else:
        pytest.fail('forward order did not close')
    assert (page.hotkey_edit in result)==page.hotkey_edit.isEnabled()
    if not page.hotkey_edit.isEnabled():
        assert page.hotkey_off not in result and page.hotkey_reset not in result
    assert all(edit in result for edit in page.edits.values())
    return result


def snapshot(rig, w, page, call_start):
    return (w.key_state().copy(), s33.bytes_(w),
            list(rig.backend.calls[call_start:]), page.message.text(),
            page._message_owner, w.statusBar().currentMessage())


def words(rig, page, edit):
    assert field_parts(edit)[0].text() == rig.words(edit.keySequence())


def in_view(page, control=None):
    control = control or QApplication.focusWidget()
    assert control is not None
    scroll = page.tabs.widget(0)
    if scroll.widget().isAncestorOf(control):
        viewport = scroll.viewport()
        rect = QRect(control.mapTo(viewport, QPoint()), control.size())
        return viewport.rect().contains(rect)
    return True


def assert_in_view(page):
    target = QApplication.focusWidget()
    assert in_view(page, target), f'focused control clipped: {target}'


SPELLINGS = ['shift_backtab', 'shift_tab', 'shift_on_entry']


def start(rig, page, edit, spelling, state='clean'):
    if spelling == 'shift_on_entry':
        place(rig, page.hotkey_reset)
        key(rig, 'keyPress', Qt.Key_Shift)
    place(rig, edit)
    if state == 'clear':
        s33.click(rig, field_parts(edit)[1])
    elif state in ('released', 'held'):
        if state != 'held' or spelling != 'shift_on_entry':
            key(rig, 'keyPress', Qt.Key_Shift)
        if state == 'released':
            key(rig, 'keyRelease', Qt.Key_Shift)


def backward(rig, spelling):
    if spelling != 'shift_on_entry':
        key(rig, 'keyPress', Qt.Key_Shift)
    code = Qt.Key_Tab if spelling == 'shift_tab' else Qt.Key_Backtab
    key(rig, 'keyPress', code, Qt.ShiftModifier)
    key(rig, 'keyRelease', code, Qt.ShiftModifier)
    key(rig, 'keyRelease', Qt.Key_Shift)


def typed(rig, code, mods=Qt.NoModifier):
    pairs = [(Qt.ControlModifier, Qt.Key_Control), (Qt.AltModifier, Qt.Key_Alt),
             (Qt.ShiftModifier, Qt.Key_Shift), (Qt.MetaModifier, Qt.Key_Meta)]
    for flag, modifier in pairs:
        if mods & flag:
            key(rig, 'keyPress', modifier)
    key(rig, 'keyClick', code, mods)
    for flag, modifier in reversed(pairs):
        if mods & flag:
            key(rig, 'keyRelease', modifier)


@pytest.mark.parametrize('spelling', SPELLINGS)
@pytest.mark.parametrize('state', ['clean', 'clear', 'released', 'held'])
def test_capture_shift_tab_matches_forward_twin(rig, case, spelling, state):
    def run(back):
        w = s33.setup(rig, case)
        call_start = len(rig.backend.calls)
        def action(page):
            controls = order(rig, page)
            start(rig, page, page.hotkey_edit, spelling if back else 'forward',
                  state if state != 'held' or back else 'clean')
            if back:
                backward(rig, spelling)
            else:
                key(rig, 'keyClick', Qt.Key_Tab)
            expected = controls[(controls.index(page.hotkey_edit) + (-1 if back else 1)) % len(controls)]
            assert QApplication.focusWidget() is expected
            result = snapshot(rig, w, page, call_start)
            assert page.hotkey_edit.keySequence() == w.hotkey_sequence()
            words(rig, page, page.hotkey_edit)
            key(rig, 'keyRelease', Qt.Key_Shift)
            words(rig, page, page.hotkey_edit)
            place(rig, page.hotkey_edit)
            typed(rig, Qt.Key_F8)
            assert w.hotkey_sequence() == QKeySequence('F8')
            before = snapshot(rig, w, page, call_start)
            key(rig, 'keyClick', Qt.Key_Tab)
            assert snapshot(rig, w, page, call_start) == before
            return result
        return s33.visit(rig, w, action)
    twin = run(False)
    assert twin[3] == ''
    assert run(True) == twin


@pytest.mark.parametrize('row', ['capture', 'copy', 'help'])
@pytest.mark.parametrize('gesture', ['plain', *SPELLINGS, 'shift_then_tab', 'ctrl_then_click'])
def test_ordinary_traversal_and_modifiers_do_not_edit(rig, case, row, gesture):
    w = s33.setup(rig, case)
    calls = []
    original = w.set_shortcut
    rig.monkeypatch.setattr(w, 'set_shortcut', lambda *args: (calls.append(args), original(*args))[1])
    def action(page):
        controls = order(rig, page)
        edit = page.edits[row]
        page.say('existing message', 'local')
        before = (w.shortcut_actions[row].shortcut(), s33.bytes_(w), page.message.text(), page._message_owner)
        start(rig, page, edit, gesture)
        if gesture in SPELLINGS:
            backward(rig, gesture)
        elif gesture == 'ctrl_then_click':
            typed(rig, Qt.Key_Control)
            s33.click(rig, page.findChild(QDialogButtonBox).button(QDialogButtonBox.Close))
            assert QApplication.focusWidget() is not edit
        else:
            if gesture == 'shift_then_tab':
                typed(rig, Qt.Key_Shift)
            key(rig, 'keyClick', Qt.Key_Tab)
        if gesture != 'ctrl_then_click':
            direction = -1 if gesture in SPELLINGS else 1
            assert QApplication.focusWidget() is controls[(controls.index(edit) + direction) % len(controls)]
        assert not calls
        assert (w.shortcut_actions[row].shortcut(), s33.bytes_(w), page.message.text(), page._message_owner) == before
        assert edit.keySequence() == before[0]
        words(rig, page, edit)
    s33.visit(rig, w, action)


@WINDOWS_KNOWN
def test_full_shortcuts_walk(rig, case):
    w = s33.setup(rig, case)
    call_start = len(rig.backend.calls)
    def action(page):
        controls = order(rig, page)
        # Capture from anywhere is first; the disclosure retains all local rows.
        first = min(controls.index(page.edits['capture']), controls.index(page.hotkey_edit))
        last = max(controls.index(reset) for reset in (*page.resets.values(), page.hotkey_reset))
        path = controls[first:last + 1]
        place(rig, path[-1])
        before = snapshot(rig, w, page, call_start), {k: a.shortcut() for k, a in w.shortcut_actions.items()}
        key(rig, 'keyPress', Qt.Key_Shift)
        visited = {QApplication.focusWidget()}
        for expected in reversed(path[:-1]):
            previous = QApplication.focusWidget()
            key(rig, 'keyClick', Qt.Key_Tab, Qt.ShiftModifier)
            assert_in_view(page)
            assert QApplication.focusWidget() is expected and expected is not previous
            visited.add(expected)
        key(rig, 'keyRelease', Qt.Key_Shift)
        for expected in path[1:]:
            previous = QApplication.focusWidget()
            key(rig, 'keyClick', Qt.Key_Tab)
            assert_in_view(page)
            assert QApplication.focusWidget() is expected and expected is not previous
        assert set(page.edits.values()) | {page.hotkey_edit} <= visited
        assert (snapshot(rig, w, page, call_start), {k: a.shortcut() for k, a in w.shortcut_actions.items()}) == before
    s33.visit(rig, w, action)


@pytest.mark.parametrize('field', ['hotkey', 'copy'])
@pytest.mark.parametrize('code', [Qt.Key_Tab, Qt.Key_Backtab], ids=['Tab', 'Backtab'])
def test_auto_repeat_traverses(rig, case, field, code):
    w = s33.setup(rig, case)
    call_start = len(rig.backend.calls)
    def action(page):
        controls = order(rig, page)
        edit = page.hotkey_edit if field == 'hotkey' else page.edits[field]
        place(rig, edit)
        before = snapshot(rig, w, page, call_start), edit.keySequence()
        mods = Qt.ShiftModifier if code == Qt.Key_Backtab else Qt.NoModifier
        event = QKeyEvent(QEvent.KeyPress, code, mods, '', True, 1)
        QApplication.sendEvent(QApplication.focusWidget(), event)
        rig.qapp.processEvents()
        direction = -1 if code == Qt.Key_Backtab else 1
        assert QApplication.focusWidget() is controls[(controls.index(edit) + direction) % len(controls)]
        assert (snapshot(rig, w, page, call_start), edit.keySequence()) == before
    s33.visit(rig, w, action)


def test_ordinary_typed_chord_and_clear(rig, case):
    w = s33.setup(rig, case)
    def action(page):
        edit = page.edits['copy']
        place(rig, edit)
        typed(rig, Qt.Key_J, Qt.AltModifier)
        assert w.a_copy.shortcut() == QKeySequence('Alt+J')
        s33.click(rig, field_parts(edit)[1])
        key(rig, 'keyClick', Qt.Key_Tab)
        assert w.a_copy.shortcut().isEmpty()
        assert w.settings.value('shortcuts/copy') == ''
    s33.visit(rig, w, action)


def test_capture_F8_AltY_and_escape_mid_draft(rig, case):
    w = s33.setup(rig, case)
    def action(page):
        place(rig, page.hotkey_edit)
        typed(rig, Qt.Key_F8)
        assert w.hotkey_sequence() == QKeySequence('F8')
        typed(rig, Qt.Key_Y, Qt.AltModifier)
        assert w.hotkey_sequence() == QKeySequence('Alt+Y')
        before = snapshot(rig, w, page, 0)
        key(rig, 'keyPress', Qt.Key_Shift)
        key(rig, 'keyClick', Qt.Key_Escape)
        QApplication.sendEvent(page.hotkey_edit, QKeyEvent(QEvent.KeyRelease, Qt.Key_Shift, Qt.NoModifier))
        rig.qapp.processEvents()
        assert not page.isVisible()
        assert snapshot(rig, w, page, 0) == before
        words(rig, page, page.hotkey_edit)
    s33.visit(rig, w, action)


@WINDOWS_KNOWN
def test_T1_walk_in_view(rig, case, record_property):
    w = s33.setup(rig, case)
    def action(page):
        assert page.size().width() == 520 and page.size().height() == 640
        place(rig, page.tabs.tabBar())
        controls = [QApplication.focusWidget()]
        for _ in range(160):
            key(rig, 'keyClick', Qt.Key_Tab)
            assert_in_view(page)
            target = QApplication.focusWidget()
            if target is controls[0]:
                break
            assert target not in controls
            controls.append(target)
        else:
            pytest.fail('forward walk did not close')
        assert page.hotkey_edit in controls
        assert set(page.edits.values()) <= set(controls)
        record_property('forward_presses', len(controls))
        for expected in list(reversed(controls[1:])) + [controls[0]]:
            key(rig, 'keyClick', Qt.Key_Tab, Qt.ShiftModifier)
            assert QApplication.focusWidget() is expected
            assert_in_view(page)
        record_property('backward_presses', len(controls))
    s33.visit(rig, w, action)


@pytest.mark.parametrize('back', [False, True], ids=['forward', 'backward'])
@pytest.mark.parametrize('field', ['copy', 'copy_reset', 'hotkey'])
def test_T2_scrolled_start(rig, case, field, back):
    w = s33.setup(rig, case)
    def action(page):
        controls = order(rig, page)
        target = (page.hotkey_edit if field == 'hotkey' else
                  page.resets['copy'] if field == 'copy_reset' else page.edits['copy'])
        place(rig, target)
        bar = page.tabs.widget(0).verticalScrollBar()
        bar.setValue(bar.minimum())
        rig.qapp.processEvents()
        if in_view(page, target):
            bar.setValue(bar.maximum())
            rig.qapp.processEvents()
        assert not in_view(page, target)
        expected = controls[(controls.index(target) + (-1 if back else 1)) % len(controls)]
        key(rig, 'keyClick', Qt.Key_Tab,
            Qt.ShiftModifier if back else Qt.NoModifier)
        assert QApplication.focusWidget() is expected
        assert_in_view(page)
    s33.visit(rig, w, action)


def spies(rig, w):
    calls = {'set_shortcut': [], 'set_hotkey': []}
    for name in calls:
        original = getattr(w, name)
        def counted(*args, _name=name, _original=original, **kwargs):
            calls[_name].append((args, kwargs))
            return _original(*args, **kwargs)
        rig.monkeypatch.setattr(w, name, counted)
    return calls


def held_on_entry(rig):
    """Only the Tab arrives here: Control was down before focus arrived."""
    for kind in (QEvent.KeyPress, QEvent.KeyRelease):
        event = QKeyEvent(kind, Qt.Key_Tab, Qt.ControlModifier)
        QApplication.sendEvent(QApplication.focusWidget(), event)
        rig.qapp.processEvents()


def ctrl_cycle(rig, page, mode):
    indices = []
    for _ in range(8):
        if mode == 'held_on_entry':
            held_on_entry(rig)
        else:
            key(rig, 'keyClick', Qt.Key_Tab, Qt.ControlModifier)
        indices.append(page.tabs.currentIndex())
    return indices


@pytest.mark.parametrize('mode', ['held_on_entry', 'QTest'])
@pytest.mark.parametrize('row', ['capture', 'copy', 'help'], ids=['first', 'copy', 'last'])
def test_T3_ctrl_cycle_rows(rig, case, row, mode, record_property):
    w = s33.setup(rig, case)
    calls = spies(rig, w)
    call_start = len(rig.backend.calls)
    def action(page):
        edit = page.edits[row]
        place(rig, edit)
        page.tabs.setCurrentIndex(1)
        rig.qapp.processEvents()
        before = (snapshot(rig, w, page, call_start),
                  {k: a.shortcut() for k, a in w.shortcut_actions.items()},
                  field_parts(edit)[0].text())
        indices = ctrl_cycle(rig, page, mode)
        record_property('s36', json.dumps({'tabs': indices,
                        'calls': {k: len(v) for k, v in calls.items()}}))
        assert indices == [2, 3, 0, 1, 2, 3, 0, 1]
        assert calls == {'set_shortcut': [], 'set_hotkey': []}
        assert (snapshot(rig, w, page, call_start),
                {k: a.shortcut() for k, a in w.shortcut_actions.items()},
                field_parts(edit)[0].text()) == before
        page.tabs.setCurrentIndex(0); place(rig,edit)
        witness=FocusOutWitness(edit); mutations=[]
        put,remove=w.settings.setValue,w.settings.remove
        rig.monkeypatch.setattr(w.settings,'setValue',lambda *a:(mutations.append(a),put(*a))[1])
        rig.monkeypatch.setattr(w.settings,'remove',lambda *a:(mutations.append(a),remove(*a))[1])
        key(rig,'keyClick',Qt.Key_Tab)
        assert witness.events and QApplication.focusWidget() is page.resets[row]
        assert not mutations
        assert calls == {'set_shortcut': [], 'set_hotkey': []}
        assert (snapshot(rig,w,page,call_start),
                {k:a.shortcut() for k,a in w.shortcut_actions.items()},
                field_parts(edit)[0].text())==before
        words(rig, page, edit)
    s33.visit(rig, w, action)


@pytest.mark.parametrize('mode', ['held_on_entry', 'QTest'])
def test_T4_ctrl_cycle_capture(rig, case, mode, record_property):
    w = s33.setup(rig, case)
    calls = spies(rig, w)
    call_start = len(rig.backend.calls)
    def action(page):
        place(rig, page.hotkey_edit)
        page.tabs.setCurrentIndex(1)
        rig.qapp.processEvents()
        before = snapshot(rig, w, page, call_start)
        indices = ctrl_cycle(rig, page, mode)
        record_property('s36', json.dumps({'tabs': indices,
                        'calls': {k: len(v) for k, v in calls.items()}}))
        assert indices == [2, 3, 0, 1, 2, 3, 0, 1]
        assert calls == {'set_shortcut': [], 'set_hotkey': []}
        assert snapshot(rig, w, page, call_start) == before
        assert page.hotkey_edit.keySequence() == w.hotkey_sequence()
        words(rig, page, page.hotkey_edit)
        page.tabs.setCurrentIndex(0)
        rig.qapp.processEvents()
        place(rig, page.hotkey_edit)
        typed(rig, Qt.Key_F8)
        assert w.hotkey_sequence() == QKeySequence('F8')
    s33.visit(rig, w, action)


TWIN_PRESSES = [
    pytest.param(Qt.Key_Tab, Qt.ControlModifier, id='Ctrl_Tab'),
    pytest.param(Qt.Key_Tab, Qt.ControlModifier | Qt.ShiftModifier, id='Ctrl_Shift_Tab'),
    pytest.param(Qt.Key_Backtab, Qt.ControlModifier, id='Ctrl_Backtab'),
    pytest.param(Qt.Key_Tab, Qt.AltModifier, id='Alt_Tab'),
    pytest.param(Qt.Key_Tab, Qt.MetaModifier, id='Meta_Tab'),
]


def movement(page, controls, target):
    focus = QApplication.focusWidget()
    if focus is target:
        return 'stayed'
    if page.tabs.currentIndex() != 0:
        assert not page.tabs.widget(0).isAncestorOf(focus)
        return 'left page'
    index = controls.index(target)
    if focus is controls[(index + 1) % len(controls)]:
        return 'forward'
    if focus is controls[(index - 1) % len(controls)]:
        return 'backward'
    pytest.fail(f'focus did not stay or move one control: {focus}')


@pytest.mark.parametrize('code,mods', TWIN_PRESSES)
@pytest.mark.parametrize('field', ['capture', 'copy', 'help', 'hotkey'],
                         ids=['first', 'copy', 'last', 'capture'])
def test_T5_reset_twins(rig, case, field, code, mods, record_property):
    def run(twin):
        w = s33.setup(rig, case)
        calls = spies(rig, w)
        call_start = len(rig.backend.calls)
        def action(page):
            controls = order(rig, page)
            capture = field == 'hotkey'
            edit = page.hotkey_edit if capture else page.edits[field]
            reset = page.hotkey_reset if capture else page.resets[field]
            target = reset if twin else edit
            place(rig, target)
            before = (w.hotkey_sequence(), s33.bytes_(w),
                      list(rig.backend.calls[call_start:]))
            saved = edit.keySequence()
            typed(rig, code, mods)
            result = (page.tabs.currentIndex(), movement(page, controls, target))
            if QApplication.focusWidget() is edit:
                key(rig, 'keyClick', Qt.Key_Tab)
            if capture:
                assert not calls['set_hotkey']
                assert (w.hotkey_sequence(), s33.bytes_(w),
                        list(rig.backend.calls[call_start:])) == before
            assert calls == {'set_shortcut': [], 'set_hotkey': []}
            assert edit.keySequence() == saved
            words(rig, page, edit)
            counts = {k: len(v) for k, v in calls.items()}
            if capture:
                page.tabs.setCurrentIndex(0)
                rig.qapp.processEvents()
                place(rig, edit)
                typed(rig, Qt.Key_F8)
                assert w.hotkey_sequence() == QKeySequence('F8')
            return {'tab': result[0], 'movement': result[1], 'calls': counts}
        return s33.visit(rig, w, action)
    twin = run(True)
    field_result = run(False)
    record_property('s36', json.dumps({'field': field_result, 'twin': twin}))
    assert (field_result['tab'], field_result['movement']) == (twin['tab'], twin['movement'])
