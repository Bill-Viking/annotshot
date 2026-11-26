"""s37/s39: real Settings fields, independent owner/storage and painter witnesses.

No stock finish cycle. Hand-made edges keep held-at-entry distinct from down here.
"""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QKeyCombination, QPoint, Qt
from PySide6.QtGui import QAccessible, QInputMethodEvent, QKeyEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QKeySequenceEdit, QToolButton, QSizePolicy

import test_s33_settings_key_field as s33
import test_s35_settings_tab_keys as s35
from test_s33_settings_key_field import rig
from key_field_support import field_parts, FocusOutWitness
from annotshot import hotkey, theme

C, A, S, M, N = Qt.ControlModifier, Qt.AltModifier, Qt.ShiftModifier, Qt.MetaModifier, Qt.NoModifier
PAIRS = ((C, Qt.Key_Control), (A, Qt.Key_Alt), (S, Qt.Key_Shift), (M, Qt.Key_Meta))


@pytest.fixture(params=['darwin', 'win32'], ids=['Mac', 'Windows'])
def case(request):
    return s33.Case(7, request.param, 'D', 'i_focus')


def edge(field, key, mods=N, kind=QEvent.KeyPress, repeat=False, text='', scan=0, virtual=0):
    event = QKeyEvent(kind, key, mods, scan, virtual, 0, text, repeat, 1)
    QApplication.sendEvent(field, event)
    return event


def up(field, key, mods=N, repeat=False):
    return edge(field, key, mods, QEvent.KeyRelease, repeat)


def value(field):
    interface = QAccessible.queryAccessibleInterface(field)
    return interface.text(QAccessible.Value)


def shown(field, expected, tuples=None):
    assert field.text() == expected
    assert value(field) == expected
    if tuples is not None:
        assert field._paint_parts == tuples


def raised(field, sequence, rig):
    """Independent navigation oracle: saved words and every cap raised."""
    shown(field, rig.words(sequence))
    expected = []
    order = ((M, Qt.Key_Meta), (A, Qt.Key_Alt), (S, Qt.Key_Shift), (C, Qt.Key_Control)) if rig.platform == 'darwin' else ((M, Qt.Key_Meta), (C, Qt.Key_Control), (A, Qt.Key_Alt), (S, Qt.Key_Shift))
    for chord in range(sequence.count()):
        combo = sequence[chord]
        for flag, identity in order:
            if combo.keyboardModifiers() & flag:
                word = rig.words(QKeySequence(QKeyCombination(flag, Qt.Key_K))).removesuffix('+K')
                expected.append((chord, identity, word, 'saved', False))
        expected.append((chord, combo.key(), rig.words(QKeySequence(QKeyCombination(combo.keyboardModifiers() & Qt.KeypadModifier, combo.key()))), 'saved', False))
    assert field._paint_parts == tuple(expected)


def field_for(page, row):
    return page.hotkey_edit if row == 'hotkey' else page.edits[row]


def observe(rig, w, page):
    writes, calls, chords = [], s35.spies(rig, w), []
    put, remove = w.settings.setValue, w.settings.remove
    rig.monkeypatch.setattr(w.settings, 'setValue', lambda *a: (writes.append(('set', *a)), put(*a))[1])
    rig.monkeypatch.setattr(w.settings, 'remove', lambda *a: (writes.append(('remove', *a)), remove(*a))[1])
    for f in [*page.edits.values(), page.hotkey_edit]:
        f.chordEntered.connect(lambda seq: chords.append(QKeySequence(seq)))
    return writes, calls, chords


def invariant(rig, w, page):
    return (s33.bytes_(w), tuple(rig.backend.calls), dict(rig.backend.held),
            {k: tuple(a.shortcuts()) for k, a in w.shortcut_actions.items()},
            w.key_state().copy(), page.message.text(), page._message_owner,
            w.statusBar().currentMessage())


def focus_chain(page):
    start=page.tabs.tabBar(); current=start; controls=[]
    for _ in range(1000):
        if current is not page.tabs and current.isVisible() and current.isEnabled() and current.focusPolicy() & Qt.TabFocus:
            controls.append(current)
        current=current.nextInFocusChain()
        if current is start: return controls
    pytest.fail('Qt focus chain did not close')


HISTORIES = ('rest', 'clear', 'tap', 'refused', 'base_down', 'base_up')
TAB_FLAGS = {
    1: ((Qt.Key_Tab, N),),
    2: ((Qt.Key_Tab, S), (Qt.Key_Backtab, S), (Qt.Key_Backtab, N)),
    3: ((Qt.Key_Tab, C),),
    4: ((Qt.Key_Tab, C | S), (Qt.Key_Backtab, C)),
    5: ((Qt.Key_Tab, A),),
    6: ((Qt.Key_Tab, M),),
    7: ((Qt.Key_Tab, C | A | S | M), (Qt.Key_Backtab, Qt.GroupSwitchModifier | Qt.KeypadModifier)),
}


def tab_case(rig, case, family, row, history, arrival, repeat, small, scrolled=False):
    def run(w, twin, code, mods):
        def action(page):
            if small:
                page.resize(420, 360)
                rig.qapp.processEvents()
            controls = focus_chain(page)
            if scrolled:
                bar=page.tabs.widget(0).verticalScrollBar()
                bar.setValue(bar.maximum() if row=='copy' else bar.minimum())
            field = field_for(page, row)
            reset = page.hotkey_reset if row == 'hotkey' else page.resets[row]
            q = QKeySequence(w.hotkey_sequence() if row == 'hotkey' else w.shortcut_actions[row].shortcut())
            assert q == QKeySequence(hotkey.DEFAULT if row == 'hotkey' else 'Ctrl+C')
            shown(field,rig.words(q))
            incoming = mods & (C | A | S | M)
            # Seed the very same physical modifier before the tap/chord. On
            # arrival its down goes only to the Reset twin, never the field.
            s35.place(rig, reset if arrival else field)
            flags = N
            for flag, key in PAIRS:
                if incoming & flag:
                    flags |= flag
                    edge(QApplication.focusWidget(), key, flags)
            s35.place(rig, field)
            if history == 'clear':
                s33.click(rig, field_parts(field)[1])
            elif history == 'tap':
                tap_flag,tap_key = next(((flag,key) for flag,key in PAIRS if not incoming & flag),
                                        (Qt.GroupSwitchModifier,Qt.Key_AltGr))
                edge(field, tap_key, incoming|tap_flag)
                up(field, tap_key, incoming)
            elif history == 'refused':
                candidate = QKeySequence(QKeyCombination(incoming|C,Qt.Key_Z))
                w.set_shortcut('undo',candidate)  # reserve, or retain its existing owner
                old = QKeySequence(q)
                edge(field, Qt.Key_Z, incoming|C)
                assert field.keySequence()==old and 'already used by' in page.message.text()
                up(field, Qt.Key_Z, incoming)
            elif history.startswith('base_'):
                edge(field, Qt.Key_F8, incoming)
                q=QKeySequence(QKeyCombination(incoming,Qt.Key_F8))
                assert field.keySequence()==q
                shown(field,rig.words(q))
                if history == 'base_up':
                    up(field, Qt.Key_F8, incoming)
                    shown(field,rig.words(q))
                    for flag,key in PAIRS:
                        if incoming & flag:
                            up(field,key); shown(field,rig.words(q))
            target = reset if twin else field
            s35.place(rig, target)
            if history=='clear' and row=='copy': q=QKeySequence()
            if history=='base_up':
                fresh=N
                for flag,key in PAIRS:
                    if incoming & flag:
                        fresh |= flag; edge(target,key,fresh)
            before = invariant(rig, w, page)
            writes, calls, chords = observe(rig, w, page)
            edge(target, code, mods, repeat=repeat)
            result = (page.tabs.currentIndex(), s35.movement(page, controls, target),
                      page.isVisible(), s35.in_view(page) if page.tabs.currentIndex()==0 else True)
            assert invariant(rig, w, page) == before
            assert calls == {'set_shortcut': [], 'set_hotkey': []} and not writes and not chords
            raised(field, q, rig)
            up(QApplication.focusWidget(), code, mods)
            raised(field, q, rig)
            remaining=mods
            for flag, key in PAIRS:
                if mods & flag:
                    remaining &= ~flag
                    up(QApplication.focusWidget(), key,remaining)
                    raised(field, q, rig)
            if history == 'base_down':
                destination = QApplication.focusWidget()
                assert destination is not None and destination.isVisible()
                after = invariant(rig, w, page)
                up(destination, Qt.Key_F8, remaining)
                raised(field, q, rig)
                assert QApplication.focusWidget() is destination and invariant(rig, w, page) == after
            assert invariant(rig, w, page) == before
            if small and page.tabs.currentIndex() == 0 and QApplication.focusWidget() is not target:
                assert s35.in_view(page)
            edge(QApplication.focusWidget(), Qt.Key_Escape)
            assert not page.isVisible()
            raised(field, q, rig)
            return result
        return s33.visit(rig, w, action)
    for code, mods in TAB_FLAGS[family]:
        # Each trial opens the real modal dialog. Reuse only the expensive
        # main window, with real release/reset roads between matched trials.
        # The full s33 oracle separately keeps its hidden Help observer.
        w = s33.setup(rig, case, help_window=False)
        result = run(w, False, code, mods)
        before = (s33.bytes_(w), tuple(rig.backend.calls), w.key_state().copy())
        up(w, Qt.Key_F8)  # the base_down history deliberately left it held
        assert (s33.bytes_(w), tuple(rig.backend.calls), w.key_state().copy()) == before
        assert w.reset_all_shortcuts() is None
        assert all(a.shortcuts() == list(w.default_shortcuts[k]) for k,a in w.shortcut_actions.items())
        assert w.hotkey_sequence() == QKeySequence(hotkey.DEFAULT)
        assert result == run(w, True, code, mods)


# Every ID is independently collected. s35 retains the full two-lap/walk tests.
@pytest.mark.parametrize('row', ['copy', 'hotkey'])
@pytest.mark.parametrize('history', HISTORIES)
@pytest.mark.parametrize('arrival', [False, True], ids=['inside', 'arrival'])
@pytest.mark.parametrize('repeat', [False,True])
@pytest.mark.parametrize('small', [False,True])
@pytest.mark.parametrize('family', range(1, 8))
def test_tab_matrix(rig, case, family, row, history, arrival, repeat, small):
    tab_case(rig, case, family, row, history, arrival, repeat, small)


def test_F01(rig, case): tab_case(rig, case, 1, 'copy', 'rest', True, False, False)
def test_F02(rig, case): tab_case(rig, case, 2, 'hotkey', 'clear', True, False, False)
def test_F03(rig, case): tab_case(rig, case, 3, 'copy', 'clear', True, False, False)
def test_F04(rig, case): tab_case(rig, case, 4, 'hotkey', 'tap', True, False, False)
def test_F05(rig, case): tab_case(rig, case, 5, 'hotkey', 'tap', False, False, False)
def test_F06(rig, case): tab_case(rig, case, 6, 'copy', 'rest', True, False, False)
def test_F07(rig, case): tab_case(rig, case, 7, 'hotkey', 'rest', True, True, False)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
def test_F08(rig, case, row):
    w=s33.setup(rig,case)
    for flag,key in PAIRS: edge(w,key,C|A|S|M)
    def action(page):
        for box,q in ((page.hotkey_edit,QKeySequence(hotkey.DEFAULT)),(page.edits['copy'],QKeySequence('Ctrl+C'))):
            shown(box,rig.words(q)); assert all(not p[4] for p in box._paint_parts)
        f=field_for(page,row); before=invariant(rig,w,page)
        QTest.mouseClick(f,Qt.LeftButton); rig.qapp.processEvents()
        assert QApplication.focusWidget() is f
        shown(f,rig.words(QKeySequence(hotkey.DEFAULT if row=='hotkey' else 'Ctrl+C')))
        for key in (Qt.Key_Control,Qt.Key_Alt,Qt.Key_Shift,Qt.Key_Meta):
            up(f,key)
            for box,q in ((page.hotkey_edit,QKeySequence(hotkey.DEFAULT)),(page.edits['copy'],QKeySequence('Ctrl+C'))):
                shown(box,rig.words(q)); assert all(not p[4] for p in box._paint_parts)
        page.tabs.setCurrentIndex(1); page.tabs.setCurrentIndex(0); rig.qapp.processEvents()
        assert invariant(rig,w,page)==before
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
def test_F09(rig, case, row):
    w=s33.setup(rig,case)
    for flag,key in PAIRS: edge(w,key,C|A|S|M)
    def action(page):
        for box,q in ((page.hotkey_edit,QKeySequence(hotkey.DEFAULT)),(page.edits['copy'],QKeySequence('Ctrl+C'))):
            shown(box,rig.words(q)); assert all(not p[4] for p in box._paint_parts)
        f=field_for(page,row); s35.place(rig,f); before=invariant(rig,w,page)
        for key in (Qt.Key_Control,Qt.Key_Alt,Qt.Key_Shift,Qt.Key_Meta):
            up(f,key); shown(f,rig.words(QKeySequence(hotkey.DEFAULT if row=='hotkey' else 'Ctrl+C')))
            assert invariant(rig,w,page)==before
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
def test_F10(rig, case, row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); q=f.keySequence(); before=invariant(rig,w,page)
        edge(f,Qt.Key_Control,C); shown(f,rig.words(QKeySequence('Ctrl+K')).removesuffix('+K'))
        edge(f,Qt.Key_Shift,C|S); shown(f,rig.words(QKeySequence('Ctrl+Shift+K')).removesuffix('+K'))
        up(f,Qt.Key_Shift,C)
        # s43e: losing a family retires the whole incomplete mixed preview.
        raised(f,q,rig)
        assert QAccessible.queryAccessibleInterface(f).text(QAccessible.Description) == 'Hold a modifier and press another key.'
        assert f.keySequence()==q and invariant(rig,w,page)==before
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
def test_F11(rig, case, row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); before=invariant(rig,w,page)
        edge(f,Qt.Key_Shift,S); up(f,Qt.Key_Shift)
        shown(f,rig.words(f.keySequence()))
        page.resets['copy'].setFocus(); rig.qapp.processEvents()
        assert invariant(rig,w,page)==before
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
@pytest.mark.parametrize('history', ['tap','clear','hold'])
def test_F13(rig, case, row, history):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f)
        if history=='clear': s33.click(rig,field_parts(f)[1])
        else:
            edge(f,Qt.Key_Shift,S)
            if history=='tap': up(f,Qt.Key_Shift)
        q=w.hotkey_sequence() if row=='hotkey' else w.a_copy.shortcut()
        witness=FocusOutWitness(f)
        before=invariant(rig,w,page); writes,calls,chords=observe(rig,w,page)
        page.tabs.widget(0).ensureWidgetVisible(page.resets['help'])
        QTest.mousePress(page.resets['help'],Qt.LeftButton); rig.qapp.processEvents()
        QTest.mouseRelease(page.resets['help'],Qt.LeftButton,pos=QPoint(-10,-10)); rig.qapp.processEvents()
        assert invariant(rig,w,page)==before and not writes and not chords
        assert calls=={'set_shortcut':[],'set_hotkey':[]}
        assert witness.events and QApplication.focusWidget() is page.resets['help']
        shown(f,rig.words(q)); up(f,Qt.Key_Shift); shown(f,rig.words(q))
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
@pytest.mark.parametrize('history', ['rest','clear','hold','tap','refused'])
def test_F14(rig, case, row, history):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f)
        if history=='clear': s33.click(rig,field_parts(f)[1])
        if history in ('hold','tap'):
            edge(f,Qt.Key_Shift,S)
            if history=='tap': up(f,Qt.Key_Shift)
        if history=='refused': edge(f,Qt.Key_C,C) if row=='hotkey' else edge(f,Qt.Key_Z,C)
        before=invariant(rig,w,page)
        edge(f,Qt.Key_Escape)  # actual flags, irrespective of old Shift down
        assert not page.isVisible() and invariant(rig,w,page)==before
        shown(f,rig.words(f.keySequence()))
    s33.visit(rig,w,action)


@pytest.mark.parametrize('seq', ['F8','Alt+Y','Alt+Shift+Space','Ctrl+Return','Ctrl+Space','Ctrl+Backspace','Alt+Num+1','A','Alt+Volume Up','Ctrl+C'])
def test_F15(rig, case, seq):
    w=s33.setup(rig,case)
    def action(page):
        f=page.hotkey_edit; s35.place(rig,f); old=QKeySequence(hotkey.DEFAULT)
        before=invariant(rig,w,page); writes,calls,chords=observe(rig,w,page)
        replies=[]; settle=f.settleChord
        rig.monkeypatch.setattr(f,'settleChord',lambda saved,taken,**kw:(replies.append((QKeySequence(saved),taken)),settle(saved,taken,**kw))[1])
        combo=QKeySequence(seq)[0]; edge(f,combo.key(),combo.keyboardModifiers())
        assert QApplication.focusWidget() is f
        accepted=seq in ('F8','Alt+Y','Alt+Shift+Space','Ctrl+Space')
        q=QKeySequence(seq) if accepted else old
        assert calls['set_hotkey']==[((QKeySequence(seq),False,True),{})]
        assert chords==[QKeySequence(seq)] and replies==[(q,accepted)]
        shown(f,rig.words(q)); assert f.keySequence()==w.hotkey_sequence()==q
        assert all(p[4]==accepted for p in f._paint_parts)
        if accepted:
            assert page.message.text()=='' and not w.hotkey_off() and w.hotkey.sequence==q
        else:
            reason=(hotkey.MAC_KEYPAD if case.platform=='darwin' else hotkey.WIN_KEYPAD) if seq=='Alt+Num+1' else hotkey.NEED_MODIFIER if seq=='A' else rig.words(QKeySequence('Ctrl+C'))+' is already used by Copy image.' if seq=='Ctrl+C' else hotkey.UNKNOWN_KEY
            assert page.message.text()==reason and not writes
            assert s33.bytes_(w)==before[0] and tuple(rig.backend.calls)==before[1]
        after=invariant(rig,w,page); counts=len(writes)
        up(f,combo.key(),combo.keyboardModifiers())
        assert QApplication.focusWidget() is f
        shown(f,rig.words(q)); assert not f._paint_parts[-1][4]
        assert all(p[4]==accepted for p in f._paint_parts[:-1])
        flags=combo.keyboardModifiers()
        for flag,key in PAIRS:
            if flags & flag:
                flags &= ~flag; up(f,key,flags)
                shown(f,rig.words(q))
                assert all(p[4]==(accepted and bool(flags & dict((key,flag) for flag,key in PAIRS).get(p[1],N))) for p in f._paint_parts)
                assert QApplication.focusWidget() is f
                assert invariant(rig,w,page)==after
        assert len(calls['set_hotkey'])==1 and len(writes)==counts
    s33.visit(rig,w,action)


@pytest.mark.parametrize('seq', ['Alt+J','Ctrl+C','Ctrl+Z','Return','Enter','Space','Backspace','Delete','Ctrl+Backspace','Left','Home','End','PgUp','PgDown','Ins','Print','F8','Ctrl+V','Ctrl+A','Ctrl+Z','Shift+!','Ctrl++','Alt+Num+1','Volume Up'])
def test_F16(rig, case, seq):
    w=s33.setup(rig,case)
    def action(page):
        f=page.edits['copy']; s35.place(rig,f); before=invariant(rig,w,page)
        writes,calls,chords=observe(rig,w,page); replies=[]; settle=f.settleChord
        rig.monkeypatch.setattr(f,'settleChord',lambda saved,taken,**kw:(replies.append((QKeySequence(saved),taken)),settle(saved,taken,**kw))[1])
        combo=QKeySequence(seq)[0]; edge(f,combo.key(),combo.keyboardModifiers())
        assert QApplication.focusWidget() is f
        normalized=QKeySequence(QKeyCombination(combo.keyboardModifiers() & ~Qt.KeypadModifier,combo.key()))
        accepted=seq not in ('Ctrl+Z','Delete')
        q=normalized if accepted else QKeySequence('Ctrl+C')
        assert chords==[QKeySequence(seq)] and calls['set_shortcut']==[(('copy',normalized),{})]
        assert replies==[(q,accepted)] and f.keySequence()==w.a_copy.shortcut()==q
        shown(f,rig.words(q)); assert all(p[4]==accepted for p in f._paint_parts)
        if not accepted:
            owner='Undo' if seq=='Ctrl+Z' else 'Delete'
            assert page.message.text()==rig.words(normalized)+' is already used by '+owner+'.'
            assert not writes and s33.bytes_(w)==before[0] and tuple(rig.backend.calls)==before[1]
        else:
            assert page.message.text()==''
            assert w.settings.value('shortcuts/copy')==normalized.toString(QKeySequence.PortableText) if seq!='Ctrl+C' else not w.settings.contains('shortcuts/copy')
        after=invariant(rig,w,page); counts=len(writes)
        up(f,combo.key(),combo.keyboardModifiers()); shown(f,rig.words(q))
        assert QApplication.focusWidget() is f
        assert not f._paint_parts[-1][4]
        flags=combo.keyboardModifiers() & ~Qt.KeypadModifier
        for flag,key in PAIRS:
            if flags & flag:
                flags &= ~flag; up(f,key,flags); shown(f,rig.words(q))
                assert QApplication.focusWidget() is f
                assert invariant(rig,w,page)==after
        assert all(not p[4] for p in f._paint_parts)
        assert len(calls['set_shortcut'])==1 and len(writes)==counts
    s33.visit(rig,w,action)


@pytest.mark.parametrize('mods', [S,C,A,M,C|S])
def test_F17(rig, case, mods):
    def run(twin):
        w=s33.setup(rig,case)
        def action(page):
            controls=s35.order(rig,page)
            target=page.resets['copy'] if twin else page.edits['copy']
            s35.place(rig,target); before=invariant(rig,w,page)
            edge(target,Qt.Key_Escape,mods)
            result=page.isVisible(),page.tabs.currentIndex(),s35.movement(page,controls,target)
            assert invariant(rig,w,page)==before
            shown(page.edits['copy'],rig.words(QKeySequence('Ctrl+C')))
            if page.isVisible(): edge(QApplication.focusWidget(),Qt.Key_Escape)
            assert not page.isVisible()
            return result
        return s33.visit(rig,w,action)
    assert run(False)==run(True)


@pytest.mark.parametrize('code', [Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space])
def test_F18(rig, case, code):
    w=s33.setup(rig,case)
    def action(page):
        s35.place(rig,page.edits['copy']); edge(page.edits['copy'],Qt.Key_Tab)
        assert QApplication.focusWidget() is page.resets['copy']
        up(QApplication.focusWidget(),Qt.Key_Tab)
        _,calls,chords=observe(rig,w,page)
        reset=[]; original=w.reset_shortcut
        rig.monkeypatch.setattr(w,'reset_shortcut',lambda k:(reset.append(k),original(k))[1])
        QTest.keyClick(QApplication.focusWidget(),code); rig.qapp.processEvents()
        assert reset==['copy'] and not chords and calls=={'set_shortcut':[],'set_hotkey':[]}
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy','hotkey'])
def test_F19(rig, case, row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); _,calls,chords=observe(rig,w,page)
        edge(f,Qt.Key_J,A); after=invariant(rig,w,page)
        for kind in (QEvent.KeyPress,QEvent.KeyRelease,QEvent.KeyPress):
            edge(f,Qt.Key_J,A,kind,True)
            assert invariant(rig,w,page)==after
        edge(f,Qt.Key_J,A)  # duplicate down, not a second physical press
        up(f,Qt.Key_J,A); up(f,Qt.Key_J,A)
        assert len(chords)==sum(len(v) for v in calls.values())==1
        edge(f,Qt.Key_J,A); assert len(chords)==2
    s33.visit(rig,w,action)


@pytest.mark.parametrize('code', [Qt.Key_CapsLock,Qt.Key_NumLock,Qt.Key_ScrollLock,Qt.Key_Menu,Qt.Key_Dead_Acute,Qt.Key_Multi_key,Qt.Key_Mode_switch,Qt.Key_Henkan,Qt.Key_unknown,0])
@pytest.mark.parametrize('row', ['copy','hotkey'])
def test_F20(rig, case, row, code):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); before=invariant(rig,w,page)
        _,calls,chords=observe(rig,w,page)
        edge(f,Qt.Key_Shift,S); edge(f,code); up(f,code)
        shown(f,rig.words(f.keySequence()))
        assert invariant(rig,w,page)==before and not chords and calls=={'set_shortcut':[],'set_hotkey':[]}
        edge(f,Qt.Key_F8); assert len(chords)==1
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy','hotkey'])
def test_F20_composition(rig, case, row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); _,calls,chords=observe(rig,w,page)
        edge(f,Qt.Key_Dead_Acute); edge(f,Qt.Key_E,text='é'); up(f,Qt.Key_E)
        assert not chords
        QApplication.sendEvent(f,QInputMethodEvent('preedit',[]))
        edge(f,Qt.Key_E,text='e'); assert not chords
        commit=QInputMethodEvent(); commit.setCommitString('é'); QApplication.sendEvent(f,commit)
        assert not chords; shown(f,rig.words(f.keySequence()))
        edge(f,Qt.Key_F8); assert chords==[QKeySequence('F8')]
        edge(f,Qt.Key_AltGr,Qt.GroupSwitchModifier); edge(f,Qt.Key_Q,Qt.GroupSwitchModifier,text='@')
        assert len(chords)==1
    s33.visit(rig,w,action)


@pytest.mark.parametrize('focused', [False,True])
def test_F21(rig, case, focused):
    w=s33.setup(rig,case)
    def action(page):
        f=page.hotkey_edit
        s35.place(rig,f if focused else page.hotkey_reset)
        before=invariant(rig,w,page); _,calls,chords=observe(rig,w,page)
        point=f.clearButton().mapTo(f,f.clearButton().rect().center())
        s33.click(rig,field_parts(f)[1]); shown(f,'')
        assert f.keySequence().isEmpty() and not field_parts(f)[1].isVisible()
        assert QApplication.focusWidget() is f and invariant(rig,w,page)==before
        assert calls=={'set_shortcut':[],'set_hotkey':[]} and not chords
        QTest.mouseClick(f,Qt.LeftButton,pos=point); shown(f,'')
        assert QApplication.focusWidget() is f and invariant(rig,w,page)==before
        assert calls=={'set_shortcut':[],'set_hotkey':[]} and not chords
        edge(f,Qt.Key_Shift,S); up(f,Qt.Key_Shift); shown(f,'')
        page.hotkey_reset.setFocus(); rig.qapp.processEvents(); shown(f,rig.words(w.hotkey_sequence()))
    s33.visit(rig,w,action)


def test_F22(rig, case):
    w=s33.setup(rig,case)
    def action(page):
        controls=s35.order(rig,page)
        assert focus_chain(page)==controls
        assert len(page.edits)==27
        for f in [*page.edits.values(),page.hotkey_edit]:
            assert isinstance(f,QLineEdit) and field_parts(f)[1].focusPolicy()==Qt.NoFocus
            assert field_parts(f)[1] not in controls and f in controls
    s33.visit(rig,w,action)


@pytest.mark.parametrize('control', ['off','reset','all'])
def test_F23(rig, case, control):
    w=s33.setup(rig,case)
    def action(page):
        f=page.hotkey_edit; s35.place(rig,f); s33.click(rig,field_parts(f)[1]); edge(f,Qt.Key_Shift,S)
        _,calls,chords=observe(rig,w,page); owner_calls=[]
        name={'reset':'_apply_key','all':'reset_all_shortcuts'}.get(control)
        if name:
            original=getattr(w,name)
            rig.monkeypatch.setattr(w,name,lambda *a,**kw:(owner_calls.append((a,kw)),original(*a,**kw))[1])
        button={'off':page.hotkey_off,'reset':page.hotkey_reset,'all':page.reset_all}[control]
        s33.click(rig,button)
        d=QKeySequence(hotkey.DEFAULT)
        assert not chords and f.keySequence()==w.hotkey_sequence()==d
        if control=='off':
            assert calls['set_hotkey']==[((d,True,True),{})]
            assert page.hotkey_off.isChecked() and w.hotkey_off() and not w.hotkey.registered and not rig.backend.held
        elif control=='reset':
            assert owner_calls==[((d,False),{'reset':True})] and not calls['set_hotkey']
            assert w.hotkey.registered and not w.hotkey_off()
        else:
            assert owner_calls==[((),{})] and not calls['set_hotkey']
            assert all(tuple(a.shortcuts())==tuple(w.default_shortcuts[k]) for k,a in w.shortcut_actions.items())
        shown(f,rig.words(d)); assert all(not p[4] for p in f._paint_parts)
        assert page.message.text()==''
        up(f,Qt.Key_Shift); shown(f,rig.words(d)); assert all(not p[4] for p in f._paint_parts)
    s33.visit(rig,w,action)


def test_F24(rig, case):
    w=s33.setup(rig,case)
    def action(page):
        f=page.edits['copy']; s35.place(rig,f); edge(f,Qt.Key_J,A); up(f,Qt.Key_J,A)
        count=[]; reset=w.reset_shortcut
        rig.monkeypatch.setattr(w,'reset_shortcut',lambda k:(count.append(k),reset(k))[1])
        edge(f,Qt.Key_Shift,S); s33.click(rig,page.resets['copy']); up(f,Qt.Key_Shift)
        assert count==['copy']; shown(f,rig.words(QKeySequence('Ctrl+C')))
        assert w.a_copy.shortcuts()==[QKeySequence('Ctrl+C')] and not w.settings.contains('shortcuts/copy')
        assert all(not p[4] for p in f._paint_parts) and page.message.text()==''
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy','hotkey'])
def test_F25(rig, case, row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); edge(f,Qt.Key_Control,C)
        before=invariant(rig,w,page); QApplication.sendEvent(page,QEvent(QEvent.WindowDeactivate))
        shown(f,rig.words(f.keySequence()))
        QApplication.sendEvent(page,QEvent(QEvent.WindowActivate)); up(f,Qt.Key_Control)
        assert invariant(rig,w,page)==before
        edge(f,Qt.Key_F8); assert (w.hotkey_sequence() if row=='hotkey' else w.a_copy.shortcut())==QKeySequence('F8'); up(f,Qt.Key_F8)
        edge(f,Qt.Key_J,A); assert (w.hotkey_sequence() if row=='hotkey' else w.a_copy.shortcut())==QKeySequence('Alt+J')
    s33.visit(rig,w,action)


@pytest.mark.parametrize('button', [Qt.LeftButton,Qt.RightButton,Qt.MiddleButton])
@pytest.mark.parametrize('row', ['copy','hotkey'])
def test_F26(rig, case, row, button):
    from PySide6.QtCore import QObject, QMimeData, QPointF
    from PySide6.QtGui import QContextMenuEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent, QTouchEvent, QEventPoint, QPointingDevice, QInputDevice
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); q=QKeySequence(hotkey.DEFAULT if row=='hotkey' else 'Ctrl+C')
        before=invariant(rig,w,page); writes,calls,chords=observe(rig,w,page); seen=[]
        class Delivery(QObject):
            def eventFilter(self,watched,event): seen.append(event.type()); return False
        witness=Delivery(f); f.installEventFilter(witness)
        QTest.mousePress(f,button,pos=QPoint(5,5)); QTest.mouseMove(f,QPoint(30,10)); QTest.mouseRelease(f,button,pos=QPoint(30,10))
        QTest.mouseDClick(f,button)
        context=QContextMenuEvent(QContextMenuEvent.Mouse,QPoint(5,5)); QApplication.sendEvent(f,context)
        mime=QMimeData(); mime.setText('evil')
        events=[QDragEnterEvent(QPoint(5,5),Qt.CopyAction,mime,Qt.LeftButton,N),
                QDragMoveEvent(QPoint(8,5),Qt.CopyAction,mime,Qt.LeftButton,N),
                QDropEvent(QPointF(8,5),Qt.CopyAction,mime,Qt.LeftButton,N)]
        # Qt refuses external drag delivery before the event path when drops are
        # disabled. Deliver the real event objects to that path as well.
        for event in events:
            QApplication.sendEvent(f,event)
            f.event(event)
            assert not event.isAccepted()
        device=QPointingDevice('s41 touch',41,QInputDevice.DeviceType.TouchScreen,QPointingDevice.PointerType.Finger,QInputDevice.Capability.Position,1,0)
        for kind,state in ((QEvent.TouchBegin,QEventPoint.State.Pressed),(QEvent.TouchEnd,QEventPoint.State.Released)):
            event=QTouchEvent(kind,device,N,[QEventPoint(1,state,QPointF(5,5),QPointF(f.mapToGlobal(QPoint(5,5))))])
            QApplication.sendEvent(f,event); f.event(event)
        f.setText('evil'); f.insert('evil'); f.paste(); f.cut(); f.undo(); f.redo()
        assert QEvent.MouseButtonPress in seen and QEvent.MouseMove in seen and QEvent.MouseButtonRelease in seen and QEvent.ContextMenu in seen
        assert invariant(rig,w,page)==before and not writes and not chords
        assert calls=={'set_shortcut':[],'set_hotkey':[]} and not f.hasSelectedText()
        assert not f.findChildren(__import__('PySide6.QtWidgets',fromlist=['QMenu']).QMenu)
        shown(f,rig.words(q))
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy','hotkey'])
def test_F27(rig, case, row):
    w=s33.setup(rig,case)
    def action(page):
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtCore import QPointF
        page.resize(420,360); rig.qapp.processEvents()
        f=field_for(page,row); s35.place(rig,f); before=invariant(rig,w,page)
        bar=page.tabs.widget(0).verticalScrollBar(); assert bar.maximum()>0
        toward_bottom=False  # both common rows are now at the top
        for at_limit in (False,True):
            boundary=bar.maximum() if toward_bottom else bar.minimum()
            bar.setValue(boundary if at_limit else boundary+(-1 if toward_bottom else 1))
            previous=bar.value(); assert s35.in_view(page,f)
            QTest.wheelEvent(page.windowHandle(),f.mapTo(page,f.rect().center()),QPoint(0,-120 if toward_bottom else 120))
            rig.qapp.processEvents()
            assert (bar.value()==previous) if at_limit else (bar.value()!=previous)
            assert invariant(rig,w,page)==before and QApplication.focusWidget() is f and page.tabs.currentIndex()==0
            shown(f,rig.words(QKeySequence(hotkey.DEFAULT if row=='hotkey' else 'Ctrl+C')))
    s33.visit(rig,w,action)


def test_F28(rig, case):
    w=s33.setup(rig,case); rig.monkeypatch.setattr(rig.backend, "available", False)
    def action(page):
        assert not page.hotkey_edit.isEnabled() and not page.hotkey_off.isEnabled() and not page.hotkey_reset.isEnabled()
        controls=s35.order(rig,page)
        assert page.hotkey_edit not in controls and page.hotkey_off not in controls and page.hotkey_reset not in controls
        assert all(f in controls and page.resets[k] in controls for k,f in page.edits.items())
        s35.place(rig,controls[0])
        for key,flags,path in ((Qt.Key_Tab,N,controls[1:]+controls[:1]),(Qt.Key_Backtab,S,list(reversed(controls[1:]))+controls[:1])):
            for expected in path:
                edge(QApplication.focusWidget(),key,flags); up(QApplication.focusWidget(),key,flags)
                assert QApplication.focusWidget() is expected
                shown(page.hotkey_edit,rig.words(QKeySequence(hotkey.DEFAULT)))
                assert all(not p[4] for p in page.hotkey_edit._paint_parts)
        before=invariant(rig,w,page); edge(page.hotkey_edit,Qt.Key_F8)
        assert invariant(rig,w,page)==before
        s35.place(rig,page.edits['copy']); edge(page.edits['copy'],Qt.Key_F8)
        assert w.a_copy.shortcut()==QKeySequence('F8')
    s33.visit(rig,w,action)


@pytest.mark.parametrize('first', ['modifier','base','tab','escape','mouse','return'])
@pytest.mark.parametrize('phase', ['beat','minimizing','armed'])
def test_F29(rig, case, first, phase):
    w,native,captured=s33.raw_setup(rig,s33.Case(11,case.platform,'D','open'))
    def action(page):
        f=page.hotkey_edit; s35.place(rig,page.hotkey_reset if first=='mouse' else f)
        if phase=='minimizing': rig.monkeypatch.setattr(w,'showMinimized',lambda:None)
        s33.menu_try(w)
        if phase!='beat': w.key_clock.advance(1000)
        assert w._key_try['phase']==phase
        # Passive construction/publication has no input and leaves the try alive.
        observer=s33.settings_dialog.SettingsDialog(w); w._publish_key()
        assert w._key_try['phase']==phase; observer.deleteLater()
        stale=[cb for _,cb in w.key_clock.queue]; raw=native.raw(); backend=w.hotkey._backend
        _,calls,chords=observe(rig,w,page); endings=[]; end=w.end_key_try
        def ending(reason="",restore=False):
            if w._key_try is not None: endings.append(reason)
            return end(reason,restore)
        rig.monkeypatch.setattr(w,'end_key_try',ending)
        effects=[]
        for method in ('_present','endInput','setFocus'):
            original=getattr(f,method)
            def witnessed(*args,_original=original,_method=method,**kwargs):
                assert w._key_try is None and endings==['Try cancelled']
                effects.append(_method)
                return _original(*args,**kwargs)
            rig.monkeypatch.setattr(f,method,witnessed)
        if first=='mouse': QTest.mouseClick(f,Qt.LeftButton)
        else: edge(f,{'modifier':Qt.Key_Shift,'base':Qt.Key_F8,'tab':Qt.Key_Tab,'escape':Qt.Key_Escape,'return':Qt.Key_Return}[first],S if first=='modifier' else N)
        assert w._key_try is None and endings==['Try cancelled']
        assert effects, 'no visible recipient effect was witnessed'
        if first=='modifier': shown(f,'Shift',((0,Qt.Key_Shift,'Shift','preview',True),))
        elif first=='base':
            assert chords==[QKeySequence('F8')] and w.hotkey_sequence()==QKeySequence('F8') and all(p[4] for p in f._paint_parts)
        elif first=='tab': assert QApplication.focusWidget() is page.hotkey_off
        elif first=='escape': assert not page.isVisible()
        elif first=='mouse': assert QApplication.focusWidget() is f
        else:
            assert chords==[QKeySequence('Return')] and page.message.text()==hotkey.NEED_MODIFIER
            assert w.hotkey_sequence()==QKeySequence(hotkey.DEFAULT) and all(not p[4] for p in f._paint_parts)
        assert sum(len(v) for v in calls.values())==int(first in ('base','return'))
        after=invariant(rig,w,page); parts=f._paint_parts; n=len(chords)
        for cb in stale: cb()
        s33.dispatch_to(rig,backend,raw); w.key_clock.advance(20000)
        assert not captured and w._key_try is None and endings==['Try cancelled']
        assert invariant(rig,w,page)==after and f._paint_parts==parts and len(chords)==n
    s33.visit(rig,w,action)


def test_F30(rig, case):
    # Existing adapter/clock seam with real owner; K12/K13/K14 remain independent.
    raw_case=s33.Case(12,case.platform,'TD','raw','before_choice')
    s33.test_K12(rig,raw_case)


def test_F31(rig, case):
    w=s33.setup(rig,case)
    def action(page):
        f=page.hotkey_edit; s35.place(rig,f); edge(f,Qt.Key_Shift,S)
        before=invariant(rig,w,page); text=f.text(); w.hotkey._backend.press()
        assert not w._s33_captures and invariant(rig,w,page)==before and f.text()==text
    s33.visit(rig,w,action)


def test_F32(rig, case):
    w,native,captured=s33.raw_setup(rig,s33.Case(10,case.platform,'D','adapter_focus','ordinary'))
    def action(page):
        f=page.edits['copy']; s35.place(rig,f); submissions=[]
        f.chordEntered.connect(submissions.append)
        before=f.text(),f.keySequence(),s33.bytes_(w)
        native.dispatch(native.raw())
        assert captured==[1] and not submissions
        assert (f.text(),f.keySequence(),s33.bytes_(w))==before
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy','hotkey'])
def test_F33(rig, case, row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); edge(f,Qt.Key_Shift,S)
        before=invariant(rig,w,page); text=f.text(); w._publish_key()
        assert f.text()==text and invariant(rig,w,page)==before
        f.setKeySequence(QKeySequence('Ctrl+K, Ctrl+C')); shown(f,rig.words(QKeySequence('Ctrl+K, Ctrl+C')))
        assert f.keySequence()==QKeySequence('Ctrl+K, Ctrl+C') and not f.hasUnfinishedInput()
        up(f,Qt.Key_Shift); shown(f,rig.words(f.keySequence()))
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy','hotkey'])
def test_F34(rig, case, row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); edge(f,Qt.Key_Control,C)
        before=invariant(rig,w,page); text=f.text(); tuples=f._paint_parts
        event=edge(f,Qt.Key_K,C, QEvent.ShortcutOverride)
        assert event.isAccepted() and f.text()==text and f._paint_parts==tuples
        assert invariant(rig,w,page)==before
        edge(f,Qt.Key_K,C); assert (w.hotkey_sequence() if row=='hotkey' else w.a_copy.shortcut())==QKeySequence('Ctrl+K')
    s33.visit(rig,w,action)


@pytest.mark.parametrize('focused', [False,True])
@pytest.mark.parametrize('held', [False,True])
def test_F35(rig, case, focused, held):
    w=s33.setup(rig,case)
    def action(page):
        f=page.edits['copy']; s35.place(rig,f if focused else page.resets['copy'])
        if held: edge(f,Qt.Key_Shift,S)
        _,calls,chords=observe(rig,w,page)
        point=f.clearButton().mapTo(f,f.clearButton().rect().center())
        s33.click(rig,field_parts(f)[1])
        assert calls['set_shortcut']==[(('copy',QKeySequence()),{})]
        assert not chords and w.a_copy.shortcut().isEmpty() and w.settings.value('shortcuts/copy')==''
        shown(f,''); assert not field_parts(f)[1].isVisible() and QApplication.focusWidget() is f
        QTest.mouseClick(f,Qt.LeftButton,pos=point); shown(f,'')
        assert QApplication.focusWidget() is f and calls['set_shortcut']==[(('copy',QKeySequence()),{})]
        up(f,Qt.Key_Shift); shown(f,'')
        edge(f,Qt.Key_Tab); assert len(calls['set_shortcut'])==1
        s33.click(rig,page.resets['copy']); assert w.a_copy.shortcut()==QKeySequence('Ctrl+C')
        s35.place(rig,f); s33.click(rig,field_parts(f)[1]); edge(f,Qt.Key_Escape)
        assert not page.isVisible() and w.a_copy.shortcut().isEmpty()
    s33.visit(rig,w,action)


@pytest.fixture
def own(qapp, monkeypatch, case):
    from annotshot import shortcut_field
    monkeypatch.setattr(shortcut_field.sys, 'platform', case.platform)
    monkeypatch.setattr(shortcut_field, 'key_words', lambda seq: s33.s30.key_words(seq, case.platform))
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
    host=QWidget(); box=QVBoxLayout(host)
    field=shortcut_field.ShortcutField(QKeySequence('Ctrl+C'))
    other=QPushButton('Reset'); box.addWidget(field); box.addWidget(other)
    host.show(); host.activateWindow(); field.setFocus(); qapp.processEvents()
    yield field, other, host
    host.close(); host.deleteLater()
    # A pytest function has no outer Qt loop to deliver DeferredDelete. Retire
    # its owner and passive observer before constructing the next fixture.
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    qapp.processEvents()


def saved_parts(case, base=Qt.Key_C, shift=False, down=()):
    labels = ((Qt.Key_Shift, 'Shift'), (Qt.Key_Control, 'Command')) if case.platform=='darwin' and shift else ((Qt.Key_Control,'Ctrl'),(Qt.Key_Shift,'Shift')) if shift else ((Qt.Key_Control,'Command' if case.platform=='darwin' else 'Ctrl'),)
    return tuple((0,key,word,'saved',key in down) for key,word in (*labels,(base,chr(base))))


@s35.WINDOWS_KNOWN
def test_painter_every_edge(own, case, qapp):
    f,other,host=own
    ctrl='Command' if case.platform=='darwin' else 'Ctrl'
    shown(f,ctrl+'+C',saved_parts(case))
    edge(f,Qt.Key_Control,C); shown(f,ctrl,((0,Qt.Key_Control,ctrl,'preview',True),))  # S06
    preview = ((0,Qt.Key_Shift,'Shift','preview',True),(0,Qt.Key_Control,ctrl,'preview',True)) if case.platform=='darwin' else ((0,Qt.Key_Control,ctrl,'preview',True),(0,Qt.Key_Shift,'Shift','preview',True))
    edge(f,Qt.Key_Shift,C|S); shown(f,'+'.join(p[2] for p in preview),preview)  # S07
    edge(f,Qt.Key_K,C|S,QEvent.ShortcutOverride); shown(f,'+'.join(p[2] for p in preview),preview)  # S17
    calls=[]
    def accept(seq):
        calls.append(QKeySequence(seq))
        f.setKeySequence(seq)  # synchronous presenter may run first
        assert all(not p[4] for p in f._paint_parts)
        f.settleChord(seq,True)
    f.chordEntered.connect(accept)
    edge(f,Qt.Key_K,C|S)
    full='Shift+Command+K' if case.platform=='darwin' else 'Ctrl+Shift+K'
    shown(f,full,saved_parts(case,Qt.Key_K,True,(Qt.Key_Control,Qt.Key_Shift,Qt.Key_K)))  # S08
    snap=f._paint_parts
    edge(f,Qt.Key_K,C|S,repeat=True); shown(f,full,snap)
    up(f,Qt.Key_K,C|S,True); shown(f,full,snap)
    edge(f,Qt.Key_K,C|S); shown(f,full,snap); assert len(calls)==1
    up(f,Qt.Key_K,C|S); shown(f,full,saved_parts(case,Qt.Key_K,True,(Qt.Key_Control,Qt.Key_Shift)))
    up(f,Qt.Key_Shift,C); shown(f,full,saved_parts(case,Qt.Key_K,True,(Qt.Key_Control,)))  # S16
    up(f,Qt.Key_Control); shown(f,full,saved_parts(case,Qt.Key_K,True))  # S09
    # Exact deliberate re-entry still lights and submits once.
    edge(f,Qt.Key_K,C|S); shown(f,full,saved_parts(case,Qt.Key_K,True,(Qt.Key_Control,Qt.Key_Shift,Qt.Key_K)))
    assert len(calls)==2
    # A reliable up with missing modifier flags clears their lost releases.
    up(f,Qt.Key_K); shown(f,full,saved_parts(case,Qt.Key_K,True))
    # Entry-held flags light the accepted parts without inventing preview.
    other.setFocus(); qapp.processEvents(); f.setFocus(); qapp.processEvents()
    edge(f,Qt.Key_K,C|S); shown(f,full,saved_parts(case,Qt.Key_K,True,(Qt.Key_Control,Qt.Key_Shift,Qt.Key_K)))
    other.setFocus(); qapp.processEvents(); shown(f,full,saved_parts(case,Qt.Key_K,True))
    up(f,Qt.Key_Control); shown(f,full,saved_parts(case,Qt.Key_K,True))
    up(f,Qt.Key_K); shown(f,full,saved_parts(case,Qt.Key_K,True))
    f.chordEntered.disconnect(accept)
    f.setKeySequence(QKeySequence('Ctrl+C')); f.setFocus(); qapp.processEvents()
    def refuse(seq): f.settleChord(QKeySequence('Ctrl+C'),False)
    f.chordEntered.connect(refuse)
    edge(f,Qt.Key_Control,C); shown(f,ctrl,((0,Qt.Key_Control,ctrl,'preview',True),))
    edge(f,Qt.Key_Z,C); shown(f,ctrl+'+C',saved_parts(case))  # S10 shared modifier, quiet
    up(f,Qt.Key_Z,C); shown(f,ctrl+'+C',saved_parts(case))
    up(f,Qt.Key_Control); shown(f,ctrl+'+C',saved_parts(case))


def test_settlement_generation_and_silent_fallback(own, case, qapp):
    f,other,_=own; old=f.keySequence(); text=f.text()
    f.chordEntered.connect(lambda seq: f.setKeySequence(old))
    edge(f,Qt.Key_K,C); shown(f,text,saved_parts(case))  # no settle -> saved, unlit
    up(f,Qt.Key_K,C); f.chordEntered.disconnect()
    def invalidated(seq):
        f.setKeySequence(seq)  # owner accepted, then focus/control retired its paint
        f.endInput('navigation')
        f.settleChord(seq,True)
    f.chordEntered.connect(invalidated)
    edge(f,Qt.Key_K,C); shown(f,('Command' if case.platform=='darwin' else 'Ctrl')+'+K',saved_parts(case,Qt.Key_K))
    up(f,Qt.Key_K,C); f.chordEntered.disconnect()
    # A reply outside its receipt has no authority to publish another Q.
    f.settleChord(QKeySequence('Ctrl+C'),True)
    shown(f,('Command' if case.platform=='darwin' else 'Ctrl')+'+K',saved_parts(case,Qt.Key_K))
    def release_in_slot(seq):
        up(f,Qt.Key_K,C)
        f.settleChord(seq,True)
    f.chordEntered.connect(release_in_slot)
    edge(f,Qt.Key_K,C)
    assert f._paint_parts[-1][4] is False
    f.setKeySequence(f.keySequence()); assert all(not p[4] for p in f._paint_parts)


@pytest.mark.parametrize('seq', ['Ctrl++','Alt+Shift+Space','Ctrl+K, Ctrl+C','Meta+Alt+Shift+Ctrl+Num+Keyboard Brightness Down'])
@pytest.mark.parametrize('name', ['light','dark','retro'])
@pytest.mark.parametrize('width', [80,164,220,227,277])
@pytest.mark.parametrize('dpr', [1,2])
def test_painter_structured_words_and_fit(own, case, qapp, seq, name, width, dpr):
    from PySide6.QtGui import QImage, QPainter
    f,other,_=own; theme.apply(qapp,name); f.setKeySequence(QKeySequence(seq)); f.resize(width,f.sizeHint().height())
    other.setFocus(); qapp.processEvents()
    image=QImage(width*dpr,f.height()*dpr,QImage.Format_ARGB32_Premultiplied); image.setDevicePixelRatio(dpr)
    f.render(image)
    parts=f._paint_parts
    joined=''
    previous=0
    for i,(chord,identity,word,kind,down) in enumerate(parts):
        joined+=(', ' if chord!=previous else '+' if i else '')+word; previous=chord
        assert kind=='saved' and not down
    expected=s33.s30.key_words(QKeySequence(seq),case.platform)
    shown(f,expected); assert joined==expected
    assert len(f._paint_slots)==len(parts)
    right=f.clearButton().x()-2
    for x,y,w,h in f._paint_slots:
        assert x>=4-.001 and y>=2 and x+w<=right+.001 and y+h<=f.height()-2
    if seq=='Ctrl++':
        shown(f,expected,((0,Qt.Key_Control,'Command' if case.platform=='darwin' else 'Ctrl','saved',False),
                          (0,Qt.Key_Plus,'Plus' if case.platform=='darwin' else '+','saved',False)))
    if ',' in seq:
        ctrl='Command' if case.platform=='darwin' else 'Ctrl'
        shown(f,expected,((0,Qt.Key_Control,ctrl,'saved',False),(0,Qt.Key_K,'K','saved',False),
                          (1,Qt.Key_Control,ctrl,'saved',False),(1,Qt.Key_C,'C','saved',False)))


@pytest.mark.parametrize('name', ['light','dark','retro'])
def test_stock_geometry_disabled_and_clear(own, case, qapp, name):
    f,other,_=own; theme.apply(qapp,name)
    stock=QKeySequenceEdit(QKeySequence('Ctrl+C')); stock.setClearButtonEnabled(True); stock.setMinimumWidth(80)
    stock.resize(220,stock.sizeHint().height()); stock.grab()
    f.resize(220,f.sizeHint().height()); f.grab()
    line=stock.findChild(QLineEdit); clear=line.findChild(QToolButton)
    assert f.sizeHint()==stock.sizeHint() and f.height()==stock.height()
    assert f.minimumWidth()==80 and f.sizePolicy().horizontalPolicy()==QSizePolicy.Ignored
    assert f.sizePolicy().verticalPolicy()==QSizePolicy.Fixed
    assert f.clearButton().geometry()==clear.geometry()
    assert f.clearButton().icon().pixmap(16,16).toImage()==clear.icon().pixmap(16,16).toImage()
    f.setDisabled(True); stock.setDisabled(True); f.grab(); stock.grab()
    assert all(not p[4] for p in f._paint_parts)
    assert f.clearButton().isHidden()==clear.isHidden()
    assert not f.clearButton().isEnabled() and not clear.isEnabled()
    shown(f,s33.s30.key_words(QKeySequence('Ctrl+C'),case.platform))
    stock.deleteLater()


@pytest.mark.parametrize('outcome', ['accept','same','release_fault','refused_swap','K04','off_accept','off_refuse','reserved','retained_stop','legacy_same_reserved'])
def test_owner_settlement_bits(rig, case, outcome):
    state='Y' if outcome=='legacy_same_reserved' else 'U' if outcome=='K04' else 'O' if outcome.startswith('off_') else 'R' if outcome=='retained_stop' else 'D'
    w=s33.setup(rig,s33.Case(7,case.platform,state,'e_legacy' if outcome=='legacy_same_reserved' else 'i_focus'))
    def action(page):
        f=page.hotkey_edit; s35.place(rig,f)
        target=QKeySequence(hotkey.DEFAULT if outcome=='same' else 'Ctrl+C' if outcome in ('reserved','legacy_same_reserved') else 'Alt+X')
        if outcome in ('refused_swap','K04','off_refuse'): rig.backend.refused.add(target.toString(QKeySequence.PortableText))
        if outcome=='release_fault': rig.backend.fail_release.add(w.hotkey._backend.identity)
        if outcome=='retained_stop': rig.backend.fail_release.add(w.hotkey._retained[0][0].identity)
        answers=[]; settle=f.settleChord
        rig.monkeypatch.setattr(f,'settleChord',lambda seq,taken,**kw:(answers.append((QKeySequence(seq),taken)),settle(seq,taken,**kw))[1])
        combo=target[0]; edge(f,combo.key(),combo.keyboardModifiers())
        taken=outcome in ('accept','same','release_fault','off_accept')
        assert answers==[(w.hotkey_sequence(),taken)]
        shown(f,rig.words(w.hotkey_sequence()))
        assert any(p[4] for p in f._paint_parts)==taken
        if outcome=='K04':
            expected=((0,Qt.Key_Alt,'Option' if case.platform=='darwin' else 'Alt','saved',False),(0,Qt.Key_X,'X','saved',False))
            shown(f,rig.words(QKeySequence('Alt+X')),expected)
            assert not w.hotkey.registered and w.hotkey_sequence()==QKeySequence('Alt+X')
        up(f,combo.key()); assert all(not p[4] for p in f._paint_parts)
        if outcome=='K04': shown(f,rig.words(QKeySequence('Alt+X')),expected)
    s33.visit(rig,w,action)


@pytest.mark.parametrize('capture', [False,True])
def test_painter_clear_tap_hold(own, case, qapp, capture):
    f,other,_=own
    if not capture:
        f.clearButton().defaultAction().triggered.connect(lambda: f.setKeySequence(QKeySequence()))
    f.clear(); shown(f,'',())
    word='Command' if case.platform=='darwin' else 'Ctrl'
    preview=((0,Qt.Key_Control,word,'preview',True),)
    edge(f,Qt.Key_Control,C); shown(f,word,preview)  # S23
    edge(f,Qt.Key_K,C,QEvent.ShortcutOverride); shown(f,word,preview)
    up(f,Qt.Key_Control); shown(f,'',())  # S22
    before=f.grab().toImage(); QTest.qWait(600)
    assert f.grab().toImage()==before  # G1's steady caret, no native blink wash
    edge(f,Qt.Key_Control,C); shown(f,word,preview)
    other.setFocus(); qapp.processEvents()
    up(f,Qt.Key_Control)
    shown(f,s33.s30.key_words(QKeySequence('Ctrl+C'),case.platform) if capture else '', saved_parts(case) if capture else ())


def test_F16_freeing_capture_owner(rig, case):
    w=rig.create(saved='Alt+Y',local='Alt+Y'); w.apply_hotkey()
    assert not w.hotkey.registered
    w._s30_page.deleteLater(); rig.qapp.processEvents(); w.show()
    def action(page):
        f=page.edits['copy']; s35.place(rig,f)
        before=list(rig.backend.calls); _,calls,chords=observe(rig,w,page)
        edge(f,Qt.Key_J,A)
        assert w.a_copy.shortcut()==QKeySequence('Alt+J')
        assert w.hotkey.registered and w.hotkey.sequence==QKeySequence('Alt+Y')
        assert rig.backend.calls==before+[('register','Alt+Y')]
        assert len(calls['set_shortcut'])==1 and not calls['set_hotkey']
        shown(f,rig.words(QKeySequence('Alt+J')))
        assert all(p[4] for p in f._paint_parts)
        up(f,Qt.Key_J); assert all(not p[4] for p in f._paint_parts)
    s33.visit(rig,w,action)


def test_F33_alternate_actions_survive(rig, case):
    w=s33.setup(rig,case)
    def action(page):
        f=page.edits['save']; s35.place(rig,f)
        shortcuts=tuple(w.a_save.shortcuts()); assert len(shortcuts)==2
        before=invariant(rig,w,page); writes,calls,chords=observe(rig,w,page)
        edge(f,Qt.Key_Shift,S); up(f,Qt.Key_Shift)
        edge(f,Qt.Key_CapsLock); up(f,Qt.Key_CapsLock)
        edge(f,Qt.Key_Dead_Acute); edge(f,Qt.Key_E,text='é'); up(f,Qt.Key_E)
        f.setKeySequence(f.keySequence()); w._publish_key()
        edge(f,Qt.Key_Tab); page.tabs.setCurrentIndex(1); page.tabs.setCurrentIndex(0)
        rig.qapp.processEvents()
        assert invariant(rig,w,page)==before
        assert tuple(w.a_save.shortcuts())==shortcuts and not writes and not chords
        assert calls=={'set_shortcut':[],'set_hotkey':[]}
    s33.visit(rig,w,action)


@pytest.mark.parametrize('retire', ['setter','control','navigation'])
def test_F19_retired_base_down(own, case, qapp, retire):
    f,other,host=own; submissions=[]
    def accept(seq):
        submissions.append(QKeySequence(seq)); f.settleChord(seq,True)
    f.chordEntered.connect(accept)
    edge(f,Qt.Key_J,A); assert len(submissions)==1
    if retire=='setter': f.setKeySequence(QKeySequence('Ctrl+C'))
    else: f.endInput(retire)
    before=f.text(),f.keySequence(),f._paint_parts
    edge(f,Qt.Key_J,A)  # same physical down, no intervening genuine up
    assert len(submissions)==1 and (f.text(),f.keySequence(),f._paint_parts)==before
    up(f,Qt.Key_J,A); edge(f,Qt.Key_J,A); assert len(submissions)==2
    # Identical nonrepeat downs across activation/entry prove no release.
    QApplication.sendEvent(host,QEvent(QEvent.WindowDeactivate))
    QApplication.sendEvent(host,QEvent(QEvent.WindowActivate))
    edge(f,Qt.Key_J,A); assert len(submissions)==2
    other.setFocus(); qapp.processEvents(); f.setFocus(); qapp.processEvents()
    edge(f,Qt.Key_J,A); assert len(submissions)==2
    up(f,Qt.Key_J,A); edge(f,Qt.Key_J,A); assert len(submissions)==3


def test_F25_destruction(qapp, case):
    from annotshot.app import make_app
    from annotshot.mainwindow import MainWindow
    from annotshot.settings_dialog import SettingsDialog
    from PySide6.QtCore import QCoreApplication
    from shiboken6 import isValid
    make_app()
    window=MainWindow(); page=SettingsDialog(window)
    window.show(); page.show(); page.activateWindow(); page.edits['copy'].setFocus()
    qapp.processEvents()
    window.deleteLater()  # no explicit dialog reject/hide before parent teardown
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    qapp.processEvents()
    assert not isValid(page) and not isValid(window)

# s41: independent histories from the fix contract; baseline on fbd69bc.
@pytest.mark.parametrize('row', ['copy', 'hotkey'])
@pytest.mark.parametrize('source', ['compose','dead','ime-commit','ime-cancel','altgr'])
def test_s41_text_sources(rig, case, row, source):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f)
        q=QKeySequence('Ctrl+C' if row=='copy' else hotkey.DEFAULT)
        before=invariant(rig,w,page); deadline=tuple(w.key_clock.queue); writes,calls,chords=observe(rig,w,page)
        def quiet():
            assert QApplication.focusWidget() is f and page.tabs.currentIndex()==0
            assert tuple(w.key_clock.queue)==deadline
            shown(f,rig.words(q)); assert f.keySequence()==q
            assert all(p[3:] == ('saved',False) for p in f._paint_parts)
            assert invariant(rig,w,page)==before and not writes and not chords
            assert calls=={'set_shortcut':[],'set_hotkey':[]}
        if source in ('compose','dead'):
            edge(f,Qt.Key_Multi_key if source=='compose' else Qt.Key_Dead_Acute); quiet()
            up(f,Qt.Key_Multi_key if source=='compose' else Qt.Key_Dead_Acute); quiet()
            edge(f,Qt.Key_Apostrophe,text="'"); quiet(); up(f,Qt.Key_Apostrophe); quiet()
            if source=='compose':
                edge(f,Qt.Key_E,text='e'); quiet(); up(f,Qt.Key_E); quiet()
            else:
                # Another accent extends the one-printable dead-key guard.
                edge(f,Qt.Key_Dead_Grave); quiet()
                edge(f,Qt.Key_E,S,text='E'); quiet(); up(f,Qt.Key_E); quiet()
        elif source.startswith('ime'):
            QApplication.sendEvent(f,QInputMethodEvent('preedit',[])); quiet()
            edge(f,Qt.Key_Henkan); quiet(); up(f,Qt.Key_Henkan); quiet()
            edge(f,Qt.Key_E,text='e'); quiet(); up(f,Qt.Key_E); quiet()
            end=QInputMethodEvent()
            if source=='ime-commit': end.setCommitString('é')
            QApplication.sendEvent(f,end); quiet()
        else:
            edge(f,Qt.Key_AltGr,Qt.GroupSwitchModifier); quiet()
            edge(f,Qt.Key_Q,Qt.GroupSwitchModifier,text='@'); quiet()
            edge(f,Qt.Key_E,C|A,text='€'); quiet()
            up(f,Qt.Key_Q,C|A); quiet(); up(f,Qt.Key_E,C|A); quiet()
            up(f,Qt.Key_AltGr); quiet()
        edge(f,Qt.Key_F8); assert chords==[QKeySequence('F8')]
    s33.visit(rig,w,action)


@pytest.mark.parametrize('raw', ['Ctrl+Bogus','Ctrl+K, Ctrl+Bogus','Ctrl+Bogus, Ctrl+C'])
def test_s41_total_saved_parts(own, case, raw):
    f,_,_=own; emitted=[]; f.chordEntered.connect(emitted.append)
    seq=QKeySequence(raw); f.setKeySequence(seq)
    shown(f,s33.s30.key_words(seq,case.platform))
    assert f.keySequence()==seq and not emitted
    assert all(p[3:]==('saved',False) for p in f._paint_parts)
    assert {p[0] for p in f._paint_parts}==set(range(seq.count()))
    f.setFixedWidth(80); f.grab()  # even an empty portable spelling cannot index word[0]


@pytest.mark.parametrize('row', ['copy','hotkey'])
@pytest.mark.parametrize('road', ['blur','window','application','disable','clear','reset','all','off'])
def test_s41_unresolved_down(rig, case, row, road):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); writes,calls,chords=observe(rig,w,page)
        edge(f,Qt.Key_Alt,A); edge(f,Qt.Key_J,A)
        assert len(chords)==1 and all(p[4] for p in f._paint_parts)
        if road=='blur': s35.place(rig,page.resets['copy']); s35.place(rig,f)
        elif road=='window':
            QApplication.sendEvent(page,QEvent(QEvent.WindowDeactivate))
            QApplication.sendEvent(page,QEvent(QEvent.WindowActivate))
        elif road=='application':
            f._application_state(Qt.ApplicationInactive); f._application_state(Qt.ApplicationActive)
        elif road=='disable': f.setDisabled(True); f.setEnabled(True)
        elif road=='clear': s33.click(rig,f.clearButton()); s35.place(rig,page.resets['help']); s35.place(rig,f)
        else:
            s33.click(rig,{'reset':page.hotkey_reset if row=='hotkey' else page.resets[row],
                           'all':page.reset_all,'off':page.hotkey_off}[road]); s35.place(rig,f)
        before=invariant(rig,w,page); logs=(len(writes),{k:len(v) for k,v in calls.items()})
        q=w.hotkey_sequence() if row=='hotkey' else w.a_copy.shortcut()
        for key,mods,repeat in ((Qt.Key_J,A,False),(Qt.Key_J,A,True),(Qt.Key_Alt,A,False)):
            edge(f,key,mods,repeat=repeat)
            shown(f,rig.words(q)); assert all(not p[4] for p in f._paint_parts)
            assert len(chords)==1 and invariant(rig,w,page)==before
            assert logs==(len(writes),{k:len(v) for k,v in calls.items()})
        # A different base is immediately eligible while J remains unresolved.
        edge(f,Qt.Key_F8); assert len(chords)==2; up(f,Qt.Key_F8)
        up(f,Qt.Key_J,A); up(f,Qt.Key_Alt)
        edge(f,Qt.Key_J,A); assert len(chords)==3
    s33.visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy','hotkey'])
@pytest.mark.parametrize('native', ['scan','virtual','fallback'])
@pytest.mark.parametrize('first_up', ['top','pad'])
def test_s41_two_physical_ones(rig, case, row, native, first_up):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); _,calls,chords=observe(rig,w,page)
        def send(which,kind=QEvent.KeyPress):
            ident={'scan':{'scan':10 if which=='top' else 11},
                   'virtual':{'virtual':49 if which=='top' else 97},'fallback':{}}[native]
            edge(f,Qt.Key_1,A | (Qt.KeypadModifier if which=='pad' and (kind==QEvent.KeyPress or native=='fallback') else N),kind,**ident)
        edge(f,Qt.Key_Alt,A); send('top'); assert chords==[QKeySequence('Alt+1')]
        send('pad'); assert chords==[QKeySequence('Alt+1'),QKeySequence('Alt+Num+1')]
        assert len(calls['set_hotkey' if row=='hotkey' else 'set_shortcut'])==2
        q=QKeySequence('Alt+1'); shown(f,rig.words(q)); assert f.keySequence()==q
        assert [p[4] for p in f._paint_parts]==([False,False] if row=='hotkey' else [True,True])
        send(first_up,QEvent.KeyRelease)
        assert [p[4] for p in f._paint_parts]==([False,False] if row=='hotkey' else [True,first_up=='top'])
        send('pad' if first_up=='top' else 'top',QEvent.KeyRelease)
        assert [p[4] for p in f._paint_parts]==([False,False] if row=='hotkey' else [True,False])
        up(f,Qt.Key_Alt); assert all(not p[4] for p in f._paint_parts)
    s33.visit(rig,w,action)


@pytest.mark.parametrize('native', ['scan','virtual'])
def test_s41_renamed_key(own, case, native):
    f,_,_=own; calls=[]
    def accept(seq): calls.append(seq); f.settleChord(seq,True)
    f.chordEntered.connect(accept)
    ident={native:20}
    for _ in range(2):
        edge(f,Qt.Key_Shift,S); edge(f,Qt.Key_Exclam,S,**ident)
        assert all(p[4] for p in f._paint_parts)
        edge(f,Qt.Key_Exclam,S,**ident); assert len(calls)==_+1
        up(f,Qt.Key_Shift); assert [p[4] for p in f._paint_parts]==[False,True]
        edge(f,Qt.Key_1,N,QEvent.KeyRelease,**ident)
        assert f.keySequence()==QKeySequence('Shift+!') and all(not p[4] for p in f._paint_parts)


@pytest.mark.parametrize('row', ['save','redo'])
def test_s41_primary_reentry(rig, case, row):
    w=s33.setup(rig,case)
    def action(page):
        f=page.edits[row]; s35.place(rig,f); action=w.shortcut_actions[row]
        keys=tuple(action.shortcuts()); assert len(keys)==2
        before=s33.bytes_(w); writes,calls,chords=observe(rig,w,page)
        combo=keys[0][0]; edge(f,combo.key(),combo.keyboardModifiers())
        assert calls['set_shortcut']==[((row,keys[0]),{})] and chords==[keys[0]]
        assert tuple(action.shortcuts())==keys and s33.bytes_(w)==before and not writes
        assert not w.settings.contains('shortcuts/'+row) and all(p[4] for p in f._paint_parts)
        up(f,combo.key(),combo.keyboardModifiers()); assert not f._paint_parts[-1][4]
        for flag,key in PAIRS:
            if combo.keyboardModifiers() & flag: up(f,key)
        assert all(not p[4] for p in f._paint_parts)
    s33.visit(rig,w,action)


@pytest.mark.parametrize('equal', [False,True])
def test_s41_receipt_nested(own, case, equal):
    f,_,_=own; receipts=[]; snapshots=[]
    def snapshot(): return QKeySequence(f.keySequence()),tuple(f._paint_parts)
    def reply(seq):
        receipts.append(seq)
        if len(receipts)==1: return
        f.settleChord(receipts[0],True); snapshots.append(snapshot())
        f.settleChord(seq,True); snapshots.append(snapshot())
        f.settleChord(receipts[0],False); snapshots.append(snapshot())
    f.chordEntered.connect(reply)
    edge(f,Qt.Key_J,A); up(f,Qt.Key_J)
    edge(f,Qt.Key_J if equal else Qt.Key_K,A)
    q=QKeySequence('Alt+J' if equal else 'Alt+K')
    base=Qt.Key_J if equal else Qt.Key_K
    parts=((0,Qt.Key_Alt,'Option' if case.platform=='darwin' else 'Alt','saved',True),
           (0,base,'J' if equal else 'K','saved',True))
    assert len(receipts)==2 and receipts[0] is not receipts[1]
    assert snapshots==[(QKeySequence('Ctrl+C'),saved_parts(case)),(q,parts),(q,parts)]
    assert f.keySequence()==q and f._paint_parts==parts


@pytest.mark.parametrize('reenter', ['blur','control','up','nested','destroy'])
def test_s41_receipt_presentation(own, case, qapp, monkeypatch, reenter):
    from shiboken6 import isValid
    from PySide6.QtCore import QCoreApplication
    f,other,_=own; present=f.setKeySequence; entered=[]
    def presentation(seq):
        present(seq)
        monkeypatch.setattr(f,'setKeySequence',present)
        if reenter=='blur': other.setFocus(); qapp.processEvents()
        elif reenter=='control': f.endInput('control')
        elif reenter=='up': up(f,Qt.Key_J,A)
        elif reenter=='nested': edge(f,Qt.Key_K,C)
        else:
            f.deleteLater(); QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    monkeypatch.setattr(f,'setKeySequence',presentation)
    def reply(seq):
        entered.append(seq); f.settleChord(seq,True)
    f.chordEntered.connect(reply)
    edge(f,Qt.Key_J,A)
    if reenter=='destroy': assert not isValid(f); return
    if reenter=='nested':
        assert f.keySequence()==QKeySequence('Ctrl+K')
        assert all(p[4] for p in f._paint_parts)
    else:
        assert f.keySequence()==QKeySequence('Alt+J')
        assert [p[4] for p in f._paint_parts]==([True,False] if reenter=='up' else [False,False])


@pytest.mark.parametrize('name', ['light','dark','retro'])
@pytest.mark.parametrize('width', [80,164,220])
@pytest.mark.parametrize('dpr', [1,2])
def test_s41_caret_bounds(own, case, qapp, monkeypatch, name, width, dpr):
    from annotshot import shortcut_field
    from PySide6.QtGui import QImage, QPainter
    f,other,_=own; theme.apply(qapp,name)
    f.setKeySequence(QKeySequence('Meta+Alt+Shift+Ctrl+Num+Keyboard Brightness Down'))
    f.setFixedWidth(width); f.setFocus(); qapp.processEvents()
    rects=[]
    class Painter(QPainter):
        def fillRect(self,*args):
            if len(args)==2 and hasattr(args[0],'width') and args[0].width()==1.5 and args[0].height()==14:
                rects.append(args[0])
            return super().fillRect(*args)
    monkeypatch.setattr(shortcut_field,'QPainter',Painter)
    image=QImage(width*dpr,f.height()*dpr,QImage.Format_ARGB32_Premultiplied); image.setDevicePixelRatio(dpr)
    f.render(image); assert len(rects)==1
    assert rects[0].left()>=0 and rects[0].right()<=f.clearButton().x()
    assert rects[0].top()>=0 and rects[0].bottom()<=f.height()
    edge(f,Qt.Key_Control,C); rects.clear(); f.render(image); assert not rects
    up(f,Qt.Key_Control); rects.clear(); f.render(image); assert len(rects)==1
    other.setFocus(); qapp.processEvents(); rects.clear(); f.render(image); assert not rects
    f.setDisabled(True); f.render(image); assert not rects

@pytest.mark.parametrize('row', ['copy','hotkey'])
@pytest.mark.parametrize('observed', [False,True])
def test_s41_reopen_unresolved(rig, case, row, observed):
    w=s33.setup(rig,case)
    def first(page):
        f=field_for(page,row); s35.place(rig,f); edge(f,Qt.Key_Alt,A); edge(f,Qt.Key_J,A)
        assert all(p[4] for p in f._paint_parts)
    s33.visit(rig,w,first)
    if observed: up(w,Qt.Key_J,A)
    def second(page):
        f=field_for(page,row); s35.place(rig,f); before=invariant(rig,w,page)
        writes,calls,chords=observe(rig,w,page)
        q=QKeySequence('Alt+J'); shown(f,rig.words(q)); assert all(not p[4] for p in f._paint_parts)
        edge(f,Qt.Key_J,A)
        assert len(chords)==int(observed)
        if not observed:
            assert not writes and invariant(rig,w,page)==before
            assert calls=={'set_shortcut':[],'set_hotkey':[]}
            shown(f,rig.words(q)); assert all(not p[4] for p in f._paint_parts)
        up(page.resets['copy'],Qt.Key_J,A)  # up observed by a real sibling in this owner
        up(page.resets['copy'],Qt.Key_Alt)
        edge(f,Qt.Key_Alt,A); edge(f,Qt.Key_J,A)
        assert len(chords)==int(observed)+1 and all(p[4] for p in f._paint_parts)
    s33.visit(rig,w,second)


@pytest.mark.parametrize('row', ['copy','hotkey'])
def test_s41_clean_ctrl_alt(rig, case, row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); _,calls,chords=observe(rig,w,page)
        edge(f,Qt.Key_Y,C|A,text='y')
        q=QKeySequence('Ctrl+Alt+Y'); assert chords==[q]
        assert f.keySequence()==q and all(p[4] for p in f._paint_parts)
        assert len(calls['set_hotkey' if row=='hotkey' else 'set_shortcut'])==1
    s33.visit(rig,w,action)


def test_s41_unpairable_up(own, case):
    f,_,_=own; calls=[]
    def accept(seq): calls.append(seq); f.settleChord(seq,True)
    f.chordEntered.connect(accept)
    edge(f,Qt.Key_K,C,scan=40); assert all(p[4] for p in f._paint_parts)
    edge(f,Qt.Key_X,C,QEvent.KeyRelease,scan=41)
    assert not f._paint_parts[-1][4] and f._paint_parts[0][4]
    edge(f,Qt.Key_K,C,scan=40); assert len(calls)==1 and not f._paint_parts[-1][4]
    edge(f,Qt.Key_K,C,QEvent.KeyRelease,scan=40)
    edge(f,Qt.Key_K,C,scan=40); assert len(calls)==2 and all(p[4] for p in f._paint_parts)


@pytest.mark.parametrize('row', ['copy','hotkey'])
def test_s41_raw_load_storage(rig, case, row):
    from annotshot.settings_dialog import SettingsDialog
    # The raw requested bytes are not sent through any registration/validation path.
    w=s33.setup(rig,case); key='hotkey/sequence' if row=='hotkey' else 'shortcuts/copy'
    w.settings.setValue(key,'Ctrl+Bogus'); w.settings.sync()
    if row=='copy': w._apply_saved_shortcuts()
    else: w._publish_key()
    before=s33.bytes_(w),tuple(rig.backend.calls),dict(rig.backend.held)
    for _ in range(2):
        page=SettingsDialog(w)
        try:
            f=field_for(page,row); seq=QKeySequence('Ctrl+Bogus')
            assert f.keySequence()==seq
            shown(f,'this key' if case.platform=='darwin' else '')
            assert len(f._paint_parts)==1 and not f._paint_parts[0][4]
            if row=='hotkey':
                f.clear(); shown(f,''); f.endInput('leave')
                shown(f,'this key' if case.platform=='darwin' else '')
            assert w.settings.value(key)=='Ctrl+Bogus'
            assert (s33.bytes_(w),tuple(rig.backend.calls),dict(rig.backend.held))==before
        finally: page.deleteLater(); rig.qapp.processEvents()


def test_s41_save_lifecycle(rig, case):
    w=s33.setup(rig,case)
    def action(page):
        f=page.edits['save']; s35.place(rig,f)
        defaults=[QKeySequence('Ctrl+S'),QKeySequence('Ctrl+Shift+S')]
        assert w.a_save.shortcuts()==defaults
        writes,calls,chords=observe(rig,w,page)
        initial=s33.bytes_(w)
        edge(f,Qt.Key_S,C)
        assert w.a_save.shortcuts()==defaults and not writes and s33.bytes_(w)==initial
        assert calls['set_shortcut']==[(('save',defaults[0]),{})]
        assert all(p[4] for p in f._paint_parts)
        up(f,Qt.Key_S,C); assert [p[4] for p in f._paint_parts]==[True,False]
        up(f,Qt.Key_Control); assert all(not p[4] for p in f._paint_parts)
        edge(f,Qt.Key_J,A); up(f,Qt.Key_J); q=QKeySequence('Alt+J')
        assert w.a_save.shortcuts()==[q] and w.settings.value('shortcuts/save')=='Alt+J'
        previous=s33.bytes_(w); n=len(writes)
        edge(f,Qt.Key_Z,C); shown(f,rig.words(q))
        assert page.message.text()==rig.words(QKeySequence('Ctrl+Z'))+' is already used by Undo.'
        assert w.a_save.shortcuts()==[q] and s33.bytes_(w)==previous and len(writes)==n
        assert all(not p[4] for p in f._paint_parts); up(f,Qt.Key_Z)
        w.set_shortcut('help',defaults[1]); previous=s33.bytes_(w); n=len(writes)
        s33.click(rig,page.resets['save'])
        assert w.a_save.shortcuts()==[q] and s33.bytes_(w)==previous and len(writes)==n
        assert page.message.text()==rig.words(defaults[1])+' is already used by Help.'
        w.reset_shortcut('help'); s35.place(rig,f)
        s33.click(rig,f.clearButton()); shown(f,'')
        assert w.a_save.shortcuts()==[] and w.settings.contains('shortcuts/save') and w.settings.value('shortcuts/save')==''
        assert calls['set_shortcut'][-1]==(('save',QKeySequence()),{})
        # Empty override survives a new window reading exactly this ini file.
        w.settings.sync()
        reload=type(w)()
        try: assert reload.a_save.shortcuts()==[] and reload.settings.value('shortcuts/save')==''
        finally: reload.hide(); reload.deleteLater(); rig.qapp.processEvents()
        s33.click(rig,page.resets['save'])
        assert w.a_save.shortcuts()==defaults and not w.settings.contains('shortcuts/save')
        shown(f,rig.words(defaults[0])); assert all(not p[4] for p in f._paint_parts)
        w.settings.sync()
        reload=type(w)()
        try: assert reload.a_save.shortcuts()==defaults and not reload.settings.contains('shortcuts/save')
        finally: reload.hide(); reload.deleteLater(); rig.qapp.processEvents()
    s33.visit(rig,w,action)

@pytest.mark.parametrize('family',range(1,8))
@pytest.mark.parametrize('row',['copy','hotkey'])
@pytest.mark.parametrize('small',[False,True])
def test_s41_tab_scrolled(rig,case,family,row,small):
    tab_case(rig,case,family,row,'clear',True,False,small,scrolled=True)


def test_s41_missing_modifier_bits(own,case):
    f,_,_=own; calls=[]
    def accept(seq): calls.append(seq); f.settleChord(seq,True)
    f.chordEntered.connect(accept)
    edge(f,Qt.Key_Control,C); edge(f,Qt.Key_K,C)
    assert all(p[4] for p in f._paint_parts)
    edge(f,Qt.Key_K)  # reliable missing Control bit, still the unresolved K
    assert len(calls)==1 and [p[4] for p in f._paint_parts]==[False,True]
    f.endInput('control')
    edge(f,Qt.Key_Control,C)
    word='Command' if case.platform=='darwin' else 'Ctrl'
    shown(f,word,((0,Qt.Key_Control,word,'preview',True),))
    edge(f,Qt.Key_K,C); assert len(calls)==1  # Control evidence never rearms K
    up(f,Qt.Key_K,C); edge(f,Qt.Key_K,C); assert len(calls)==2

@pytest.mark.parametrize('source',['compose','preedit'])
def test_s41_altgr_preserves_composition(own,case,source):
    f,_,_=own; chords=[]; f.chordEntered.connect(chords.append)
    if source=='compose': edge(f,Qt.Key_Multi_key)
    else: QApplication.sendEvent(f,QInputMethodEvent('preedit',[]))
    edge(f,Qt.Key_AltGr,Qt.GroupSwitchModifier); up(f,Qt.Key_AltGr)
    edge(f,Qt.Key_E,text='e'); up(f,Qt.Key_E)
    shown(f,('Command' if case.platform=='darwin' else 'Ctrl')+'+C',saved_parts(case))
    assert not chords
    edge(f,Qt.Key_F8); assert chords==[QKeySequence('F8')]


@pytest.mark.parametrize('row',['copy','hotkey'])
def test_s41_altgr_after_clear(rig,case,row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); s33.click(rig,f.clearButton())
        before=invariant(rig,w,page); writes,calls,chords=observe(rig,w,page)
        for kind in (QEvent.KeyPress,QEvent.KeyRelease):
            edge(f,Qt.Key_AltGr,Qt.GroupSwitchModifier if kind==QEvent.KeyPress else N,kind)
            shown(f,'',()); assert f.keySequence().isEmpty()
            assert invariant(rig,w,page)==before and not writes and not chords
            assert calls=={'set_shortcut':[],'set_hotkey':[]}
        s35.place(rig,page.resets['help'])
        shown(f,rig.words(QKeySequence(hotkey.DEFAULT)) if row=='hotkey' else '')
    s33.visit(rig,w,action)

@pytest.mark.parametrize('row',['copy','hotkey'])
@pytest.mark.parametrize('clash',[False,True])
def test_s41_raw_load_reset(rig,case,row,clash):
    from annotshot.settings_dialog import SettingsDialog
    w=s33.setup(rig,case); key='hotkey/sequence' if row=='hotkey' else 'shortcuts/copy'
    w.settings.setValue(key,'Ctrl+Bogus'); w.settings.sync()
    if row=='copy': w._apply_saved_shortcuts()
    else: w._publish_key()
    default=QKeySequence(hotkey.DEFAULT if row=='hotkey' else 'Ctrl+C')
    if clash: assert w.set_shortcut('help',default) is None
    page=SettingsDialog(w)
    try:
        f=field_for(page,row); shown(f,'this key' if case.platform=='darwin' else '')
        before=s33.bytes_(w),tuple(rig.backend.calls),dict(rig.backend.held)
        owner_calls=[]; name='_apply_key' if row=='hotkey' else 'reset_shortcut'; original=getattr(w,name)
        rig.monkeypatch.setattr(w,name,lambda *a,**kw:(owner_calls.append((a,kw)),original(*a,**kw))[1])
        (page.hotkey_reset if row=='hotkey' else page.resets['copy']).click()
        assert len(owner_calls)==1
        if row=='hotkey': assert owner_calls==[((default,False),{'reset':True})]
        else: assert owner_calls==[(('copy',),{})]
        if clash:
            assert f.keySequence()==QKeySequence('Ctrl+Bogus')
            assert page.message.text()==rig.words(default)+' is already used by Help.'
            assert (s33.bytes_(w),tuple(rig.backend.calls),dict(rig.backend.held))==before
            shown(f,'this key' if case.platform=='darwin' else '')
        else:
            assert f.keySequence()==default and not w.settings.contains(key)
            shown(f,rig.words(default)); assert page.message.text()==''
        assert all(p[3:] == ('saved',False) for p in f._paint_parts)
    finally:
        page.deleteLater(); QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete); rig.qapp.processEvents()


def test_s41_save_multi_clash(rig,case):
    w=s33.setup(rig,case)
    def action(page):
        f=page.edits['save']; s35.place(rig,f)
        keys=[QKeySequence('Ctrl+S'),QKeySequence('Ctrl+Shift+S')]
        before=s33.bytes_(w),tuple(rig.backend.calls); writes,calls,chords=observe(rig,w,page)
        edge(f,Qt.Key_Z,C)
        assert w.a_save.shortcuts()==keys and (s33.bytes_(w),tuple(rig.backend.calls))==before and not writes
        assert calls['set_shortcut']==[(('save',QKeySequence('Ctrl+Z')),{})] and chords==[QKeySequence('Ctrl+Z')]
        shown(f,rig.words(keys[0])); assert all(not p[4] for p in f._paint_parts)
        assert page.message.text()==rig.words(QKeySequence('Ctrl+Z'))+' is already used by Undo.'
        up(f,Qt.Key_Z,C); up(f,Qt.Key_Control)
        assert w.a_save.shortcuts()==keys and not w.settings.contains('shortcuts/save')
    s33.visit(rig,w,action)


def test_s41_matching_receipt_once(own,case):
    f,_,_=own; snapshots=[]
    def reply(seq):
        f.settleChord(seq,True); snapshots.append((f.keySequence(),f._paint_parts))
        f.settleChord(seq,False); snapshots.append((f.keySequence(),f._paint_parts))
        f.settleChord(QKeySequence(seq),True); snapshots.append((f.keySequence(),f._paint_parts))
    f.chordEntered.connect(reply); edge(f,Qt.Key_J,A)
    parts=((0,Qt.Key_Alt,'Option' if case.platform=='darwin' else 'Alt','saved',True),(0,Qt.Key_J,'J','saved',True))
    assert snapshots==[(QKeySequence('Alt+J'),parts)]*3


@pytest.mark.parametrize('same',[False,True])
def test_s41_authoritative_reentry(own,case,monkeypatch,same):
    f,_,_=own; original=f.setKeySequence
    def publish(seq):
        original(seq)
        original(seq if same else QKeySequence('Ctrl+C'))
    monkeypatch.setattr(f,'setKeySequence',publish)
    f.chordEntered.connect(lambda seq:f.settleChord(seq,True))
    edge(f,Qt.Key_J,A)
    if same:
        shown(f,('Option' if case.platform=='darwin' else 'Alt')+'+J',
              ((0,Qt.Key_Alt,'Option' if case.platform=='darwin' else 'Alt','saved',False),(0,Qt.Key_J,'J','saved',False)))
    else: shown(f,('Command' if case.platform=='darwin' else 'Ctrl')+'+C',saved_parts(case))


@pytest.mark.parametrize('width',[227,277])
@pytest.mark.parametrize('dpr',[1,2])
def test_s41_caret_retro_defaults(own,case,qapp,monkeypatch,width,dpr):
    test_s41_caret_bounds(own,case,qapp,monkeypatch,'retro',width,dpr)
