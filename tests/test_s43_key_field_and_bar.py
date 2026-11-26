"""s43 user histories. Real offscreen widgets; native services are fakes.

Expected words, owner bytes, native handle and effects are separate witnesses.
The caller owns native keyboard/IME, browser, display and speech proofs.
"""
import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QAccessible, QColor, QImage, QInputMethodEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

import test_s33_settings_key_field as s33
import test_s35_settings_tab_keys as s35
import test_s37_own_key_field as s37
import test_s10_capture as s10
from test_s33_settings_key_field import rig
from test_s37_own_key_field import case, own, edge, shown, field_for
from test_s10_capture import rig as capture_rig
from annotshot import hotkey, theme
from PySide6.QtCore import QRectF

N, S, A, C, M = Qt.NoModifier, Qt.ShiftModifier, Qt.AltModifier, Qt.ControlModifier, Qt.MetaModifier


def visit(rig, w, action):
    return s33.visit(rig, w, action, full=False)


def release(target, key, mods=N, scan=0, virtual=0):
    return edge(target, key, mods, QEvent.KeyRelease, scan=scan, virtual=virtual)


def quiet(field, words):
    shown(field, words)
    assert all(p[3:] == ('saved', False) for p in field._paint_parts)


def description(field):
    return QAccessible.queryAccessibleInterface(field).text(QAccessible.Description)


def expand(page):
    button = next(b for b in page.findChildren(s33.settings_dialog.QPushButton)
                  if b.text() == 'More shortcuts (24)')
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    return button


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
@pytest.mark.parametrize('scan', [50, 51])
def test_A1_shift_tap_guidance(rig, case, row, scan):
    w = s33.setup(rig, case)
    old = hotkey.DEFAULT if row == 'hotkey' else 'Meta+C' if case.platform=='darwin' else 'Ctrl+C'
    if row == 'copy': assert w.set_shortcut('copy',s33.QKeySequence(old)) is None
    def action(page):
        f = field_for(page, row); s35.place(rig, f)
        words = rig.words(s33.QKeySequence(old))
        before = s37.invariant(rig, w, page)
        writes, calls, chords = s37.observe(rig, w, page)
        edge(f, Qt.Key_Shift, S, scan=scan)
        shown(f, 'Shift', ((0, Qt.Key_Shift, 'Shift', 'preview', True),))
        assert description(f) == 'Hold Shift and press another key, such as A.'
        guide = next(g for g in page.findChildren(QLabel) if g.text() == description(f))
        assert guide.isVisible() and guide.mapToGlobal(QPoint()).y() >= f.mapToGlobal(QPoint(0, f.height())).y()
        assert not calls['set_shortcut'] and not calls['set_hotkey'] and not writes and not chords
        release(f, Qt.Key_Shift, scan=scan)
        quiet(f, words)
        assert description(f) == 'Shift needs another key. Try Shift + A.'
        assert QApplication.focusWidget() is f
        assert s37.invariant(rig, w, page) == before
        edge(f, Qt.Key_Shift, S, scan=scan)
        edge(f, Qt.Key_A, S)
        shown(f, 'Shift+A', ((0, Qt.Key_Shift, 'Shift', 'saved', True), (0, Qt.Key_A, 'A', 'saved', True)))
        assert description(f) in ('', 'Press shortcut')
        release(f, Qt.Key_A, S)
        assert f._paint_parts[-1][4] is False and f._paint_parts[0][4] is True
        release(f, Qt.Key_Shift, scan=scan)
        quiet(f, 'Shift+A')
        assert len(chords) == 1 and sum(map(len, calls.values())) == 1
    visit(rig, w, action)
    visit(rig, w, lambda page: quiet(field_for(page, row), 'Shift+A'))


@pytest.mark.parametrize('source,target',[('hotkey','copy'),('copy','save')])
def test_A1_blur_keeps_mouse_target_until_release(rig, case, source, target):
    w=s33.setup(rig,case)
    assert w.set_shortcut(target,s33.QKeySequence('Alt+J')) is None
    def action(page):
        f=field_for(page,source); s35.place(rig,f)
        edge(f,Qt.Key_Shift,S,scan=50); rig.qapp.processEvents()
        button=page.resets[target]; point=button.mapTo(page,button.rect().center())
        assert page.childAt(point) is button
        calls=[]; original=page.reset
        def reset(key): calls.append(key); return original(key)
        rig.monkeypatch.setattr(page,'reset',reset)
        QTest.mousePress(page.windowHandle(),Qt.LeftButton,pos=point); rig.qapp.processEvents()
        assert page.childAt(point) is button and button.isDown()
        assert 'Hold Shift' not in description(f)
        QTest.mouseRelease(page.windowHandle(),Qt.LeftButton,pos=point); rig.qapp.processEvents()
        assert calls==[target]
        assert w.shortcut_actions[target].shortcut()==s33.QKeySequence('Ctrl+C' if target=='copy' else 'Ctrl+S')
        release(QApplication.focusWidget(),Qt.Key_Shift,scan=50)
    visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
@pytest.mark.parametrize('draft', [False, True])
def test_A2_preview_expiry_is_visual_only(rig, case, row, draft):
    w = s33.setup(rig, case)
    def action(page):
        f = field_for(page, row); s35.place(rig, f)
        if draft: s33.click(rig, f.clearButton())
        words = '' if draft else rig.words(s33.QKeySequence(hotkey.DEFAULT if row == 'hotkey' else 'Ctrl+C'))
        before = s37.invariant(rig, w, page); writes, calls, chords = s37.observe(rig, w, page)
        edge(f, Qt.Key_Shift, S, scan=50)
        edge(f, Qt.Key_Control, S | C, scan=55)
        assert len(f._paint_parts) == 2 and all(p[3:] == ('preview', True) for p in f._paint_parts)
        timer = f.findChild(QTimer, 'shortcutPreviewExpiry')
        assert timer is not None and timer.isSingleShot() and timer.interval() == 1500 and timer.isActive()
        timer.stop(); timer.timeout.emit()
        quiet(f, words)
        assert QApplication.focusWidget() is f and not f.clearButton().isVisible() == draft
        assert s37.invariant(rig, w, page) == before
        assert not writes and not chords and not any(calls.values())
        # Duplicate down after expiry is no release evidence and cannot relight.
        edge(f, Qt.Key_Shift, S | C, scan=50); quiet(f, words)
        edge(f, Qt.Key_J, S | C)
        assert f.keySequence() == s33.QKeySequence('Ctrl+Shift+J') and len(chords) == 1
        painted = f._paint_parts
        timer.timeout.emit()  # stale timeout cannot overwrite an accepted result
        assert f._paint_parts == painted
        release(f, Qt.Key_J, S | C)
        release(f, Qt.Key_Shift, C, scan=50); release(f, Qt.Key_Control, scan=55)
    visit(rig, w, action)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
@pytest.mark.parametrize('terminal', ['commit', 'cancel', 'commit-new-preedit'])
def test_B1_preedit_dead_accent_keeps_guard(rig, case, row, terminal):
    w = s33.setup(rig, case)
    def action(page):
        f = field_for(page, row); s35.place(rig, f)
        words = rig.words(s33.QKeySequence(hotkey.DEFAULT if row == 'hotkey' else 'Ctrl+C'))
        before = s37.invariant(rig, w, page); writes, calls, chords = s37.observe(rig, w, page)
        QApplication.sendEvent(f, QInputMethodEvent('candidate', []))
        for code in (Qt.Key_Dead_Acute, Qt.Key_E, Qt.Key_T):
            edge(f, code, text='é' if code == Qt.Key_E else '')
            quiet(f, words); assert s37.invariant(rig, w, page) == before
            release(f, code); quiet(f, words)
            assert not writes and not chords and not any(calls.values())
        event = QInputMethodEvent('next' if terminal == 'commit-new-preedit' else '', [])
        if terminal != 'cancel': event.setCommitString('ét')
        QApplication.sendEvent(f, event)
        if terminal == 'commit-new-preedit':
            edge(f, Qt.Key_T, text='t'); release(f, Qt.Key_T); quiet(f, words)
            assert not chords
        edge(f, Qt.Key_F8)
        assert chords == [s33.QKeySequence('F8')]
        release(f, Qt.Key_F8); quiet(f, 'F8')
    visit(rig, w, action)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
@pytest.mark.parametrize('lost', ['duplicate', 'up-away', 'scan-arrives'])
@pytest.mark.parametrize('refused', [False, True])
def test_B3_native_identity_survives_focus(rig, case, row, lost, refused):
    w = s33.setup(rig, case)
    if refused: w.set_shortcut('undo', s33.QKeySequence('Alt+J'))
    def action(page):
        f = field_for(page, row); reset = page.hotkey_reset if row == 'hotkey' else page.resets[row]
        s35.place(rig, f); _, calls, chords = s37.observe(rig, w, page)
        edge(f, Qt.Key_J, A, scan=0 if lost == 'scan-arrives' else 20, virtual=74)
        words = rig.words(s33.QKeySequence(hotkey.DEFAULT if row == 'hotkey' else 'Ctrl+C')) if refused else rig.words(s33.QKeySequence('Alt+J'))
        # A real aborted reset-body click changes focus without resetting.
        QTest.mousePress(reset, Qt.LeftButton)
        QTest.mouseRelease(reset, Qt.LeftButton, pos=QPoint(-10, -10))
        assert QApplication.focusWidget() is reset
        if lost == 'up-away': release(reset, Qt.Key_J, A, virtual=74)
        QTest.mouseClick(f, Qt.LeftButton); quiet(f, words)
        if lost != 'up-away':
            edge(f, Qt.Key_J, A, scan=20 if lost == 'scan-arrives' else 0, virtual=74)
            quiet(f, words); assert len(chords) == 1
            release(f, Qt.Key_J, A, virtual=74)
        edge(f, Qt.Key_J, A, scan=20, virtual=74)
        assert len(chords) == 2 and sum(map(len, calls.values())) == 2
        release(f, Qt.Key_J, A, virtual=74)
        assert not f._paint_parts[-1][4]
        if not refused: assert f._paint_parts[0][4]  # Alt is genuinely still held
        release(f, Qt.Key_Alt); quiet(f, words)
    visit(rig, w, action)


@pytest.mark.parametrize('first', [20,21])
def test_B3_same_virtual_different_scans_stay_distinct(own, case, first):
    f,_,_=own; chords=[]
    def accept(seq): chords.append(seq); f.settleChord(seq,True)
    f.chordEntered.connect(accept)
    edge(f,Qt.Key_J,A,scan=20,virtual=74)
    edge(f,Qt.Key_J,A,scan=21,virtual=74)
    assert len(chords)==2 and f._paint_parts[-1][4]
    release(f,Qt.Key_J,A,virtual=74)  # cannot identify either physical sibling
    assert not f._paint_parts[-1][4]
    edge(f,Qt.Key_J,A,virtual=74)
    for scan in (20,21): edge(f,Qt.Key_J,A,scan=scan,virtual=74)
    assert len(chords)==2 and not f._paint_parts[-1][4]
    release(f,Qt.Key_J,A,scan=first,virtual=74)
    edge(f,Qt.Key_J,A,scan=41-first,virtual=74)
    assert len(chords)==2
    release(f,Qt.Key_J,A,virtual=74)  # now the remaining virtual id is unique
    edge(f,Qt.Key_J,A,scan=41-first,virtual=74)
    assert len(chords)==3 and f._paint_parts[-1][4]
    release(f,Qt.Key_J); quiet(f,'Option+J' if case.platform=='darwin' else 'Alt+J')


@pytest.mark.parametrize('virtual',[0,Qt.Key_unknown])
def test_B3_unknown_native_id_keeps_independent_keys(own, case, virtual):
    f,_,_=own; chords=[]
    def accept(seq): chords.append(seq); f.settleChord(seq,True)
    f.chordEntered.connect(accept)
    edge(f,Qt.Key_F8,virtual=virtual); edge(f,Qt.Key_F9,virtual=virtual)
    assert chords==[s33.QKeySequence('F8'),s33.QKeySequence('F9')]
    release(f,Qt.Key_F8,virtual=virtual)
    assert f._paint_parts==((0,Qt.Key_F9,'F9','saved',True),)
    release(f,Qt.Key_F9,virtual=virtual); quiet(f,'F9')


@pytest.mark.parametrize('first', [50, 51])
@pytest.mark.parametrize('finish', [False, True])
@pytest.mark.parametrize('expire', [False, True])
def test_B4_both_shifts(own, case, first, finish, expire):
    f, _, _ = own; chords = []
    def accept(seq): chords.append(seq); f.settleChord(seq, True)
    f.chordEntered.connect(accept)
    edge(f, Qt.Key_Shift, S, scan=50); edge(f, Qt.Key_Shift, S, scan=51)
    shown(f, 'Shift', ((0, Qt.Key_Shift, 'Shift', 'preview', True),))
    assert description(f) == 'Both Shift keys are down. Add another key.'
    release(f, Qt.Key_Shift, S, scan=first)
    shown(f, 'Shift', ((0, Qt.Key_Shift, 'Shift', 'preview', True),))
    assert description(f) == 'Hold Shift and press another key, such as A.'
    if expire:
        timer = f.findChild(QTimer, 'shortcutPreviewExpiry'); timer.stop(); timer.timeout.emit()
        quiet(f, 'Command+C' if case.platform == 'darwin' else 'Ctrl+C')
    if finish:
        edge(f, Qt.Key_A, S); assert chords == [s33.QKeySequence('Shift+A')]
        release(f, Qt.Key_A, S)
    release(f, Qt.Key_Shift, scan=101-first)
    quiet(f, 'Shift+A' if finish else 'Command+C' if case.platform == 'darwin' else 'Ctrl+C')


@pytest.mark.parametrize('reentry', ['up', 'blur', 'newer', 'refuse', 'destroy'])
def test_B6_release_during_first_presentation(own, case, monkeypatch, reentry):
    from shiboken6 import isValid
    f, other, _ = own; original = f._present; once = [False]; chords = []
    def present(*args):
        original(*args)
        if not once[0]:
            once[0] = True
            if reentry == 'up': release(f, Qt.Key_F8)
            elif reentry == 'blur': other.setFocus(); QApplication.processEvents()
            elif reentry == 'newer': edge(f, Qt.Key_F9)
            elif reentry == 'destroy': f.deleteLater(); s37.QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    monkeypatch.setattr(f, '_present', present)
    def answer(seq):
        chords.append(seq)
        f.settleChord(s33.QKeySequence('Ctrl+C') if reentry == 'refuse' else seq, reentry != 'refuse', origin=seq)
    f.chordEntered.connect(answer)
    edge(f, Qt.Key_F8)
    if reentry == 'destroy': assert not isValid(f); assert not chords
    elif reentry == 'newer': assert chords == [s33.QKeySequence('F9')]; shown(f, 'F9')
    elif reentry == 'blur': assert not chords; quiet(f, 'Command+C' if case.platform == 'darwin' else 'Ctrl+C')
    elif reentry == 'refuse': quiet(f, 'Command+C' if case.platform == 'darwin' else 'Ctrl+C')
    else: assert chords == [s33.QKeySequence('F8')]; quiet(f, 'F8')


@s35.WINDOWS_KNOWN
def test_B6_first_presentation_up_keeps_only_held_modifiers(own, case, monkeypatch):
    f,_,_=own; chords=[]
    edge(f,Qt.Key_Alt,A,scan=58); edge(f,Qt.Key_Shift,A|S,scan=50)
    original=f._present; once=[False]
    def present(*args):
        original(*args)
        if not once[0]:
            once[0]=True; release(f,Qt.Key_F8,A|S)
    monkeypatch.setattr(f,'_present',present)
    def accept(seq): chords.append(seq); f.settleChord(seq,True)
    f.chordEntered.connect(accept)
    edge(f,Qt.Key_F8,A|S)
    assert chords==[s33.QKeySequence('Alt+Shift+F8')]
    assert [part[4] for part in f._paint_parts]==[True,True,False]
    release(f,Qt.Key_Shift,A,scan=50)
    assert [part[4] for part in f._paint_parts]==[True,False,False]
    release(f,Qt.Key_Alt,scan=58)
    quiet(f,'Option+Shift+F8' if case.platform=='darwin' else 'Alt+Shift+F8')


@pytest.mark.parametrize('name', ['light', 'dark', 'retro'])
@pytest.mark.parametrize('dpr', [1, 2])
def test_B7_same_focused_field_resizes(own, case, qapp, monkeypatch, name, dpr):
    from annotshot import shortcut_field
    from PySide6.QtGui import QPainter
    f, _, host = own; theme.apply(qapp, name)
    host.layout().setEnabled(False)
    f.setKeySequence(s33.QKeySequence('Alt+Shift+Space'))
    default = 164 if name != 'retro' else 227
    paints = []; ink = []; old = QPainter.fillRect; original_ink = shortcut_field._ink
    def draw(p, rect, word, *args, **kwargs):
        ink.append(word)
        return original_ink(p, rect, word, *args, **kwargs)
    monkeypatch.setattr(shortcut_field, '_ink', draw)
    def fill(p, *args):
        if len(args) == 2 and hasattr(args[0], 'width') and args[0].width() == 1.5: paints.append(args[0])
        return old(p, *args)
    monkeypatch.setattr(QPainter, 'fillRect', fill)
    frames = []
    for width in (default, 80, default):
        f.resize(width, f.sizeHint().height()); qapp.processEvents(); paints.clear(); ink.clear()
        image = QImage(f.width()*dpr, f.height()*dpr, QImage.Format_ARGB32_Premultiplied); image.setDevicePixelRatio(dpr)
        f.render(image); frames.append(image)
        expected = ['Option' if case.platform == 'darwin' else 'Alt', 'Shift', 'Space']
        if width == default:
            assert ink == expected
        else:
            assert len(ink) == len(expected)
            assert all(short and short[0] == word[0] for word, short in zip(expected, ink))
            assert sum(map(len,ink)) < sum(map(len,expected))
        assert QApplication.focusWidget() is f
        shown(f, 'Option+Shift+Space' if case.platform == 'darwin' else 'Alt+Shift+Space')
        assert f.clearButton().isVisible() and f.rect().contains(f.clearButton().geometry())
        assert paints and all(r.right() <= f.clearButton().x() for r in paints)
        assert all(x+w <= f.clearButton().x()-2+.001 for x,y,w,h in f._paint_slots)
        assert any(image.pixelColor(x, y) != image.pixelColor(2*dpr, 2*dpr)
                   for x in range(8*dpr, int(f.clearButton().x()-3)*dpr) for y in range(6*dpr, (f.height()-6)*dpr))
    assert frames[0] == frames[2] and frames[0].size() != frames[1].size()
    QTest.mouseClick(f.clearButton(), Qt.LeftButton); quiet(f, '')


def test_A2_old_expiry_cannot_erase_new_preview(own, case):
    f, other, _ = own
    edge(f, Qt.Key_Shift, S, scan=50)
    stale = f._preview_callback
    release(f, Qt.Key_Shift, scan=50)
    edge(f, Qt.Key_Alt, A, scan=58)
    before = (f.text(), f._paint_parts, description(f))
    stale()
    assert (f.text(), f._paint_parts, description(f)) == before
    other.setFocus(); QApplication.processEvents()
    assert description(f) in ('', 'Press shortcut')
    f._preview_callback()
    quiet(f, 'Command+C' if case.platform == 'darwin' else 'Ctrl+C')


def test_C1_linux_disabled_first_row(rig, case):
    w = s33.setup(rig, case)
    rig.monkeypatch.setattr(type(w.hotkey), 'available', property(lambda _: False))
    def action(page):
        viewport = page.tabs.widget(0).viewport()
        assert page.hotkey_edit.mapTo(viewport, QPoint()).y() < page.edits['capture'].mapTo(viewport, QPoint()).y()
        assert all(not x.isEnabled() for x in (page.hotkey_edit, page.hotkey_off, page.hotkey_reset))
        controls = s37.focus_chain(page)
        assert page.hotkey_edit not in controls and page.hotkey_off not in controls and page.hotkey_reset not in controls
        labels = [label.text() for label in page.findChildren(QLabel)]
        assert any('Capture from anywhere' in text and hotkey.NOT_ON_LINUX in text for text in labels)
    visit(rig, w, action)


@pytest.mark.parametrize('small', [False, True])
def test_C1_C2_capture_first_and_disclosure(rig, case, small):
    w = s33.setup(rig, case); w.set_shortcut('undo', s33.QKeySequence('Alt+J'))
    def action(page):
        if small: page.resize(420, 360); rig.qapp.processEvents()
        scroll = page.tabs.widget(0); scroll.verticalScrollBar().setValue(0)
        viewport = scroll.viewport()
        assert viewport.rect().contains(QRect(page.hotkey_edit.mapTo(viewport, QPoint()), page.hotkey_edit.size()))
        assert page.hotkey_edit.mapTo(viewport, QPoint()).y() < page.edits['capture'].mapTo(viewport, QPoint()).y()
        assert {key for key, f in page.edits.items() if f.isVisible()} == {'capture', 'copy', 'save'}
        s35.place(rig, page.hotkey_edit)
        for expected in (page.hotkey_off, page.hotkey_reset, page.edits['capture']):
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_Tab); assert QApplication.focusWidget() is expected
        before = s37.invariant(rig, w, page)
        button = expand(page); assert button.isCheckable() and button.isChecked()
        assert len(page.edits) == 27 and all(f.isVisible() for f in page.edits.values())
        assert s37.invariant(rig, w, page) == before
        controls = s35.order(rig, page)
        for target in reversed(controls):
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_Backtab, S)
            assert QApplication.focusWidget() is target
        s35.place(rig, page.edits['copy']); edge(page.edits['copy'], Qt.Key_J, A)
        assert 'Undo' in page.message.text() and w.a_copy.shortcut() == s33.QKeySequence('Ctrl+C')
        release(page.edits['copy'], Qt.Key_J, A)
        s35.place(rig, page.edits['undo']); button.click(); QApplication.processEvents()
        assert QApplication.focusWidget() is button and not page.edits['undo'].isVisible()
        page.tabs.setCurrentIndex(1); page.tabs.setCurrentIndex(0)
        assert not button.isChecked()
        button.click(); page.tabs.setCurrentIndex(1); page.tabs.setCurrentIndex(0)
        assert button.isChecked() and page.edits['undo'].isVisible()
    visit(rig, w, action)


def test_C2_custom_undo_and_page_renders(rig, case, white, tmp_path):
    from annotshot.items import RectItem
    from annotshot.scene import Document
    w = s33.setup(rig,case); w._bind(Document(white))
    item=RectItem(); item.set_geom((40,40,120,80)); w.doc.add_items([item])
    assert w.set_shortcut('undo',s33.QKeySequence('Alt+J')) is None
    def folded(page):
        assert not page.edits['undo'].isVisible()
    visit(rig,w,folded)
    w.activateWindow(); w.view.setFocus(); rig.qapp.processEvents()
    QTest.keyClick(w.view.viewport(),Qt.Key_J,A); rig.qapp.processEvents()
    assert item.scene() is None and w.doc.undo_stack.index()==0
    w.doc.undo_stack.redo(); assert item.scene() is w.doc
    def action(page):
        assert not page.edits['undo'].isVisible()
        assert page.grab().save(str(tmp_path/'shortcuts-folded.png'))
        s35.place(rig,page.edits['copy']); edge(page.edits['copy'],Qt.Key_Shift,S,scan=50)
        assert page.grab().save(str(tmp_path/'field-guide.png'))
        release(page.edits['copy'],Qt.Key_Shift,scan=50)
        page.resize(420,360); rig.qapp.processEvents()
        assert page.grab().save(str(tmp_path/'shortcuts-small.png'))
        button=expand(page); s35.place(rig,page.edits['undo'])
        edge(page.edits['undo'],Qt.Key_K,A); release(page.edits['undo'],Qt.Key_K)
        assert w.a_undo.shortcut()==s33.QKeySequence('Alt+K')
        assert w.settings.value('shortcuts/undo')=='Alt+K'
        button.click(); assert not page.edits['undo'].isVisible()
        assert w.a_undo.shortcut()==s33.QKeySequence('Alt+K')
    visit(rig,w,action)
    w.activateWindow(); w.view.setFocus(); rig.qapp.processEvents()
    assert w.a_undo.isEnabled() and item.scene() is w.doc
    QTest.keyClick(w.view.viewport(),Qt.Key_K,A); rig.qapp.processEvents()
    assert item.scene() is None and w.doc.undo_stack.index()==0
    def reopen(page):
        assert not page.edits['undo'].isVisible()
        expand(page); quiet(page.edits['undo'],rig.words(s33.QKeySequence('Alt+K')))
    visit(rig,w,reopen)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
@pytest.mark.parametrize('focused', [False, True])
def test_B10a_two_clear_clicks(rig, case, row, focused):
    w = s33.setup(rig, case)
    def action(page):
        f = field_for(page, row)
        s35.place(rig, f if focused else page.hotkey_reset)
        pos = f.clearButton().geometry().center()
        writes, calls, chords = s37.observe(rig, w, page)
        QTest.mouseClick(f.clearButton(), Qt.LeftButton)
        for second in (False, True):
            if second: QTest.mouseClick(f, Qt.LeftButton, pos=pos)
            quiet(f, ''); assert QApplication.focusWidget() is f
            assert not chords and len(calls['set_shortcut']) == int(row == 'copy') and not calls['set_hotkey']
            assert len(writes) == int(row == 'copy')
        s35.place(rig, page.hotkey_reset)
        quiet(f, rig.words(s33.QKeySequence(hotkey.DEFAULT)) if row == 'hotkey' else '')
    visit(rig, w, action)


def test_B10b_wheel_midpoint_and_both_limits(rig, case):
    w = s33.setup(rig, case)
    def action(page):
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtCore import QPointF
        if hasattr(page, 'more_shortcuts'): expand(page)
        page.resize(420,360); rig.qapp.processEvents()
        scroll = page.tabs.widget(0); bar = scroll.verticalScrollBar()
        assert bar.maximum() > 200
        for offset, direction, moves in ((bar.maximum()//2, -120, True), (bar.minimum(),120,False), (bar.maximum(),-120,False)):
            bar.setValue(offset); rig.qapp.processEvents()
            f = next(f for f in page.edits.values() if s35.in_view(page,f))
            s35.place(rig,f); bar.setValue(offset); rig.qapp.processEvents()
            assert s35.in_view(page,f)
            words=f.text(); before=s37.invariant(rig,w,page); previous=bar.value()
            point=f.mapTo(page,f.rect().center())
            assert page.childAt(point) is f
            y=f.mapTo(scroll.viewport(),QPoint()).y()
            QTest.wheelEvent(page.windowHandle(), point, QPoint(0,direction)); rig.qapp.processEvents()
            assert bar.value()>previous if moves else bar.value()==previous
            assert f.mapTo(scroll.viewport(),QPoint()).y()==y-(bar.value()-previous)
            assert QApplication.focusWidget() is f and s37.invariant(rig,w,page)==before
            quiet(f,words)
    visit(rig,w,action)


@pytest.mark.parametrize('row', ['copy', 'hotkey'])
def test_B8_release_at_destination_leave_and_reopen(rig, case, row):
    w = s33.setup(rig, case)
    def action(page):
        f = field_for(page,row); s35.place(rig,f)
        writes, calls, chords = s37.observe(rig,w,page)
        edge(f,Qt.Key_F8); shown(f,'F8',((0,Qt.Key_F8,'F8','saved',True),))
        before=s37.invariant(rig,w,page); counts=(len(writes),sum(map(len,calls.values())),len(chords))
        edge(f,Qt.Key_Tab)
        destination=QApplication.focusWidget()
        assert destination is (page.hotkey_off if row=='hotkey' else page.resets[row]) and destination.isVisible()
        quiet(f,'F8')
        release(destination,Qt.Key_Tab); quiet(f,'F8')
        release(destination,Qt.Key_F8); quiet(f,'F8')
        assert QApplication.focusWidget() is destination and s37.invariant(rig,w,page)==before
        assert (len(writes),sum(map(len,calls.values())),len(chords))==counts
        page.close(); assert not page.isVisible(); quiet(f,'F8')
    visit(rig,w,action)
    visit(rig,w,lambda page: quiet(field_for(page,row),'F8'))


@pytest.mark.parametrize('seconds', [0, 3, 5, 10])
@pytest.mark.parametrize('gesture', ['area', 'window', 'whole', 'same'])
def test_D1_wait_after_pick_pixels(capture_rig, seconds, gesture):
    r = capture_rig; cap = r.cap
    # One source color before pick, another at the end of the controlled wait.
    color = [QColor('#aa2200')]
    for screen in r.screens:
        original = screen.grabWindow
        def grab(ident, original=original):
            image = original(ident).toImage(); image.fill(color[0]); return QPixmap.fromImage(image)
        r.monkeypatch.setattr(screen, 'grabWindow', grab)
    window = s10.SimpleNamespace(hwnd=99, title='Window', rect=QRectF(100,100,240,160))
    r.monkeypatch.setattr(cap.macos, 'list_windows', lambda: [window])
    session, results = r.start(last_area={'screen':'main','x':120,'y':120,'width':200,'height':100})
    bar = session.bar; bar.timer_actions[seconds].trigger()
    assert bar.timer_button.text() == ('Wait after pick · Off' if seconds == 0 else f'Wait after pick · {seconds} s')
    assert bar.help.isVisible() and 'Drag' in bar.help.text()
    session._tick(); session._tick()
    assert session.state == 'idle' and not results and not any(s.calls for s in r.screens)
    if gesture == 'area': s10.drag(session.overlays[0])
    elif gesture == 'window':
        QTest.mouseClick(bar.mode_buttons['window'], Qt.LeftButton)
        assert 'Click a window' in bar.help.text()
        QTest.mouseClick(session.overlays[0], Qt.LeftButton, pos=QPoint(150,150))
    elif gesture == 'whole': QTest.mouseClick(bar.whole_screen_button, Qt.LeftButton)
    else: QTest.mouseClick(bar.same_area_button, Qt.LeftButton)
    assert not any(s.calls for s in r.screens)
    if seconds:
        for n in range(seconds, 0, -1):
            assert session.remaining == n and bar.countdown.text() == f'{n} s' and bar.countdown.isVisible()
            assert all('count ends' in ov.hint() and 'Click' not in ov.hint() and 'Drag' not in ov.hint()
                       for ov in session.overlays)
            session._tick()
    color[0] = QColor('#00bb44')
    s10.settle(session)
    assert len(results) == 1 and results[0].image.pixelColor(0,0) == color[0]
    assert sum(len(s.calls) for s in r.screens) == 1


@pytest.mark.parametrize('gesture', ['area', 'window', 'whole', 'same'])
def test_D2_freeze_and_thaw_pixels(capture_rig, gesture):
    r = capture_rig; color = [QColor('#aa2200')]
    for screen in r.screens:
        original = screen.grabWindow
        def grab(ident, original=original):
            image = original(ident).toImage(); image.fill(color[0]); return QPixmap.fromImage(image)
        r.monkeypatch.setattr(screen, 'grabWindow', grab)
    session, results = r.start(timer=5, last_area={'screen':'main','x':120,'y':120,'width':200,'height':100})
    assert session.bar.freeze_button.text() == 'Freeze now'
    QTest.mouseClick(session.bar.freeze_button, Qt.LeftButton); s10.settle(session)
    bar = session.bar
    assert bar.freeze_button.text() == 'Go live' and bar.timer_button.text() == 'Wait after pick · 5 s'
    assert not bar.timer_button.isEnabled() and 'Screen frozen' in bar.help.text()
    assert 'already' in bar.help.text().lower()
    color[0] = QColor('#00bb44')
    if gesture == 'area':
        assert 'Drag an area' in bar.help.text(); s10.drag(session.overlays[0])
    elif gesture == 'window':
        window = s10.SimpleNamespace(hwnd=99, title='Window', rect=QRectF(100,100,240,160))
        r.monkeypatch.setattr(r.cap.macos, 'list_windows', lambda: [window])
        session.overlays[0].windows = [window]
        QTest.mouseClick(bar.mode_buttons['window'], Qt.LeftButton)
        assert 'Click a window' in bar.help.text()
        QTest.mouseClick(session.overlays[0], Qt.LeftButton, pos=QPoint(150,150))
    elif gesture == 'whole':
        QTest.mouseClick(bar.mode_buttons['screen'], Qt.LeftButton)
        assert 'Return' in bar.help.text(); QTest.keyClick(session.overlays[0], Qt.Key_Return)
    else: QTest.mouseClick(bar.same_area_button, Qt.LeftButton)
    assert len(results) == 1 and results[0].image.pixelColor(0,0) == QColor('#aa2200')
    assert sum(len(s.calls) for s in r.screens) == 2
    thaw, out = r.start(); s10.settle(thaw)
    assert thaw.freeze and thaw.timer == 5
    assert sum(len(s.calls) for s in r.screens) == 4
    QTest.mouseClick(thaw.bar.freeze_button, Qt.LeftButton)
    assert not thaw.freeze and thaw.timer == 5 and thaw.bar.timer_button.isEnabled()
    assert sum(len(s.calls) for s in r.screens) == 4
    color[0] = QColor('#2244dd')  # distinguish the new live frame from the remembered still
    s10.drag(thaw.overlays[0]); assert thaw.remaining == 5
    for _ in range(5): thaw._tick()
    s10.settle(thaw); assert out[0].image.pixelColor(0,0) == color[0]
    assert sum(len(s.calls) for s in r.screens) == 5


def test_D2_forced_freeze_and_narrow_screen(capture_rig):
    r = capture_rig
    r.screens[0]._geometry = QRect(0,0,420,360)
    r.screens[1]._geometry = QRect(-320,0,320,360)
    r.monkeypatch.setattr(r.cap.LiveOverlay, 'supports_translucency', lambda _: False)
    session, _ = r.start(timer=10); s10.settle(session)
    assert not session.settings.value('capture/freeze', False, type=bool)
    assert not session.bar.freeze_button.isEnabled()
    assert ('Live capture is unavailable on this display. Drag an area or click for the whole screen '
            'from this still, or cancel.') in session.bar.help.text()
    for ov in session.overlays:
        session.pointer_on(ov); QApplication.processEvents(); bar = session.bar
        assert ov.rect().contains(bar.geometry())
        assert bar.cancel_button.isVisible() and bar.rect().contains(bar.cancel_button.geometry())
        assert bar.help.isVisible() and bar.help.height() >= bar.help.fontMetrics().height()
        assert not bar.timer_button.isEnabled() and '10 s' in bar.timer_button.text()


def test_D1_narrow_countdown_moves_and_cancels(capture_rig, tmp_path):
    r=capture_rig
    r.screens[0]._geometry=QRect(0,0,420,360)
    r.screens[1]._geometry=QRect(-320,0,320,360)
    session,results=r.start(timer=5)
    for ov in session.overlays:
        session.pointer_on(ov); QApplication.processEvents(); bar=session.bar
        assert ov.rect().contains(bar.geometry())
        assert bar.grab().save(str(tmp_path/f'bar-live-{ov.width()}.png'))
        assert bar.help.isVisible() and 'Drag an area' in bar.help.text()
    bar=session.bar
    QTest.mouseClick(bar.whole_screen_button,Qt.LeftButton)
    assert session.remaining==5 and bar.countdown.isVisible()
    assert bar.parentWidget().rect().contains(bar.geometry())
    assert bar.rect().contains(bar.countdown.geometry()) and bar.rect().contains(bar.cancel_button.geometry())
    assert bar.grab().save(str(tmp_path/'bar-countdown.png'))
    QTest.mouseClick(bar.cancel_button,Qt.LeftButton)
    session._tick(); session._settled()
    assert results==[None] and not any(s.calls for s in r.screens)


def test_D2_bar_render_states(capture_rig, tmp_path):
    r=capture_rig; session,_=r.start(timer=5)
    assert session.bar.height()<160
    assert session.bar.grab().save(str(tmp_path/'bar-live-wide.png'))
    QTest.mouseClick(session.bar.freeze_button,Qt.LeftButton); s10.settle(session)
    assert session.bar.height()<160
    assert session.bar.grab().save(str(tmp_path/'bar-frozen-wide.png'))


@pytest.mark.parametrize('freeze', [False,True])
def test_D1_unavailable_window_guidance(capture_rig, freeze):
    session,_=capture_rig.start(mode='window',freeze=freeze)
    if freeze: s10.settle(session)
    assert 'No window is available' in session.bar.help.text()
    assert 'Click a window' not in session.overlays[0].hint()
    QTest.mouseClick(session.bar.mode_buttons['area'],Qt.LeftButton)
    assert 'Drag an area' in session.bar.help.text()

# s43e round two: independent observations before product changes.
@pytest.mark.parametrize('row', ['copy', 'hotkey'])
@pytest.mark.parametrize('publication', ['new', 'equal', 'passive', 'early-up', 'guide'])
def test_R2_owner_publication(rig, case, row, publication):
    w = s33.setup(rig, case)
    if publication == 'equal':
        if row == 'hotkey': assert w.set_hotkey(s33.QKeySequence('F8'),False,True) is None
        else: assert w.set_shortcut('copy',s33.QKeySequence('F8')) is None
    def action(page):
        f = field_for(page, row); s35.place(rig, f)
        writes, calls, chords = s37.observe(rig, w, page)
        original = f._present; fired = []; after = []
        def publish():
            if fired: return
            fired.append(True)
            if publication == 'early-up': release(f, Qt.Key_F8)
            elif publication == 'passive':
                if row == 'hotkey': page.refresh_capture_key()
                else: f.update()
            else:
                target = 'F8' if publication == 'equal' else 'F9'
                if row == 'hotkey':
                    assert w.set_hotkey(s33.QKeySequence(target), False, True) is None
                    page._restore_capture_field()  # explicit owner presentation, even equal
                else:
                    assert w.set_shortcut('copy', s33.QKeySequence(target)) is None
                    page._show_key('copy')
                quiet(f, target)
                after.append((len(chords), len(writes), sum(map(len,calls.values())), tuple(rig.backend.calls)))
        def present(*args):
            original(*args)
            if publication != 'guide': publish()
        if publication == 'guide':
            edge(f, Qt.Key_Shift, S, scan=50)
            f.guidanceChanged.connect(lambda text: publish() if text == '' else None)
        rig.monkeypatch.setattr(f, '_present', present)
        edge(f, Qt.Key_F8)
        release(f, Qt.Key_F8)
        if publication == 'guide': release(f, Qt.Key_Shift, scan=50)
        if after:
            assert (len(chords), len(writes), sum(map(len,calls.values())), tuple(rig.backend.calls)) == after[0], 'stale F8 reached the owner after its newer publication'
            quiet(f, 'F8' if publication == 'equal' else 'F9')
        else:
            assert chords == [s33.QKeySequence('F8')]
            quiet(f, 'F8')
        edge(f, Qt.Key_F8); release(f, Qt.Key_F8)
        assert chords[-1] == s33.QKeySequence('F8')
    visit(rig, w, action)


@pytest.mark.parametrize('row,draft', [('copy',False), ('hotkey',False), ('hotkey',True)])
@pytest.mark.parametrize('away', [False,True])
@pytest.mark.parametrize('first', [100,101])
def test_R2_altgr_siblings(rig, case, row, draft, away, first):
    w = s33.setup(rig, case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f)
        if draft: s33.click(rig,f.clearButton())
        words = '' if draft else rig.words(f.keySequence())
        before=s37.invariant(rig,w,page); writes,calls,chords=s37.observe(rig,w,page)
        for scan in (100,101): edge(f,Qt.Key_AltGr,Qt.GroupSwitchModifier,scan=scan,virtual=65027)
        recipient=f
        if away:
            recipient=page.resets['copy']; s35.place(rig,recipient)
        release(recipient,Qt.Key_AltGr,virtual=65027)
        if away:
            s35.place(rig,f)
            if draft: words=rig.words(f.keySequence())  # blur restores the global draft
        def text():
            edge(f,Qt.Key_Q,C|A,text='@',scan=24); release(f,Qt.Key_Q,C|A,scan=24)
            quiet(f,words)
            assert s37.invariant(rig,w,page)==before
            assert not writes and not chords and not any(calls.values())
        text()
        release(f,Qt.Key_AltGr,scan=first,virtual=65027); text()
        release(f,Qt.Key_AltGr,virtual=65027)  # only the final sibling is unique
        edge(f,Qt.Key_Control,C,scan=29); edge(f,Qt.Key_Alt,C|A,scan=56)
        edge(f,Qt.Key_Q,C|A,scan=24); release(f,Qt.Key_Q,C|A,scan=24)
        assert chords==[s33.QKeySequence('Ctrl+Alt+Q')]
        release(f,Qt.Key_Control,A,scan=29); release(f,Qt.Key_Alt,scan=56)
    visit(rig,w,action)
    visit(rig,w,lambda page:quiet(field_for(page,row),rig.words(s33.QKeySequence('Ctrl+Alt+Q'))))


@pytest.mark.parametrize('evidence', [True,False,None])
def test_R2_altgr_all_up_boundary(own,case,monkeypatch,evidence):
    from annotshot import shortcut_field
    f,other,_=own; chords=[]; reads=[]
    monkeypatch.setattr(shortcut_field,'_altgr_all_up',lambda: (reads.append(1),evidence)[1],raising=False)
    f.chordEntered.connect(lambda seq: (chords.append(seq),f.settleChord(seq,True)))
    for scan in (100,101): edge(f,Qt.Key_AltGr,Qt.GroupSwitchModifier,scan=scan,virtual=65027)
    release(f,Qt.Key_AltGr,virtual=65027)
    assert reads==[1]
    edge(f,Qt.Key_Q,C|A,text='@'); release(f,Qt.Key_Q,C|A)
    assert len(chords)==int(evidence is True)
    if evidence is not True:
        edge(f,Qt.Key_F8); release(f,Qt.Key_F8)
        assert chords==[s33.QKeySequence('F8')]
        edge(f,Qt.Key_Q,C|A,text='@'); release(f,Qt.Key_Q,C|A)
        assert chords==[s33.QKeySequence('F8')]
    release(other,Qt.Key_AltGr,scan=100,virtual=65027)
    release(other,Qt.Key_AltGr,virtual=65027)
    edge(f,Qt.Key_Control,C,scan=29); edge(f,Qt.Key_Alt,C|A,scan=56)
    edge(f,Qt.Key_Q,C|A); assert chords[-1]==s33.QKeySequence('Ctrl+Alt+Q')


@pytest.mark.parametrize('row,draft',[('copy',False),('hotkey',False),('hotkey',True)])
@pytest.mark.parametrize('lift',[pytest.param(Qt.Key_Shift,marks=s35.WINDOWS_KNOWN),Qt.Key_Control])
def test_R2_mixed_release_event_turn(rig,case,row,draft,lift,tmp_path):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f)
        if draft: s33.click(rig,f.clearButton())
        words='' if draft else rig.words(f.keySequence())
        before=s37.invariant(rig,w,page); writes,calls,chords=s37.observe(rig,w,page)
        edge(f,Qt.Key_Shift,S,scan=50); edge(f,Qt.Key_Control,S|C,scan=55)
        stale=f._preview_callback
        surviving=C if lift==Qt.Key_Shift else S
        survivor=Qt.Key_Control if lift==Qt.Key_Shift else Qt.Key_Shift
        release(f,lift,surviving,scan=50 if lift==Qt.Key_Shift else 55)
        quiet(f,words)
        assert description(f)=='Hold a modifier and press another key.'
        assert page.grab().save(str(tmp_path/'fresh-mixed-field.png'))
        assert QApplication.focusWidget() is f and s37.invariant(rig,w,page)==before
        assert not chords and not writes and not any(calls.values())
        edge(f,survivor,surviving,scan=55 if survivor==Qt.Key_Control else 50); stale(); quiet(f,words)
        edge(f,Qt.Key_J,surviving)
        assert chords==[s33.QKeySequence('Ctrl+J' if surviving==C else 'Shift+J')]
        release(f,Qt.Key_J,surviving); release(f,survivor,scan=55 if survivor==Qt.Key_Control else 50)
    visit(rig,w,action)


@pytest.mark.parametrize('row',['copy','hotkey'])
@pytest.mark.parametrize('alias',[Qt.Key_Super_L,Qt.Key_Super_R,Qt.Key_Hyper_L,Qt.Key_Hyper_R])
def test_R2_alias_words(rig,case,row,alias,tmp_path):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); old=rig.words(f.keySequence())
        writes,calls,chords=s37.observe(rig,w,page)
        word='Control' if case.platform=='darwin' else 'Meta'
        edge(f,alias,M,scan=77)
        shown(f,word,((0,Qt.Key_Meta,word,'preview',True),))
        assert description(f)==f'Hold {word} and press another key, such as A.'
        release(f,alias,scan=77); quiet(f,old)
        assert description(f)==f'{word} needs another key. Try {word} + A.'
        guide=next(g for g in page.findChildren(QLabel) if g.text()==description(f))
        assert guide.isVisible() and not chords and not writes and not any(calls.values())
        assert page.grab().save(str(tmp_path/'fresh-alias-field.png'))
        edge(f,alias,M,scan=77); edge(f,Qt.Key_A,M)
        assert chords==[s33.QKeySequence('Meta+A')]
        release(f,Qt.Key_A,M); release(f,alias,scan=77)
    visit(rig,w,action)


@pytest.mark.parametrize('spelling,code,flags,modifier',[
    ('Alt+A',Qt.Key_A,A,Qt.Key_Alt),('Alt+G',Qt.Key_G,A,Qt.Key_Alt),
    ('Meta+C',Qt.Key_C,M,Qt.Key_Meta),('Shift+A',Qt.Key_A,S,Qt.Key_Shift)])
def test_R2_copy_reopen_invocation(rig,case,white,spelling,code,flags,modifier):
    from annotshot.scene import Document
    w=s33.setup(rig,case); white.setPixelColor(0,0,QColor('#e83319')); w._bind(Document(white))
    def action(page):
        f=page.edits['copy']; s35.place(rig,f)
        edge(f,modifier,flags,scan=77); edge(f,code,flags,scan=44)
        release(f,code,flags,scan=44); release(f,modifier,scan=77)
        assert w.a_copy.shortcut()==s33.QKeySequence(spelling)
    visit(rig,w,action)
    visit(rig,w,lambda page: quiet(page.edits['copy'],rig.words(s33.QKeySequence(spelling))))
    w.activateWindow(); w.view.setFocus(); QApplication.processEvents()
    QApplication.clipboard().clear()
    QTest.keyClick(w.view.viewport(),code,flags); QApplication.processEvents()
    image=QApplication.clipboard().image()
    assert not image.isNull() and image.size()==white.size() and image.pixelColor(0,0)==QColor('#e83319')


@pytest.mark.parametrize('row',['copy','hotkey'])
@pytest.mark.parametrize('width',['normal','80','restored'])
@pytest.mark.parametrize('blocked',[False,True])
def test_R2_clear_window_dispatch(rig,case,row,width,blocked,record_property):
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QPushButton
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f); natural=f.width(); measured=[natural]
        if width!='normal':
            f.setMaximumWidth(80); page.layout().activate(); QApplication.processEvents()
            assert f.width()==80; measured.append(f.width())
            if width=='restored':
                f.setMaximumWidth(16777215); page.layout().activate(); QApplication.processEvents(); measured.append(f.width())
        record_property('layout_widths',','.join(map(str,measured)))
        assert f.width()==(80 if width=='80' else natural)
        # Observe the real button recipient through the scroll viewport.
        button=f.clearButton(); point=button.mapTo(page,button.rect().center())
        assert page.childAt(point) is button
        received=[]
        class Witness(QObject):
            def eventFilter(self,obj,event):
                if event.type() in (QEvent.MouseButtonPress,QEvent.MouseButtonRelease): received.append((obj,event.type()))
                return False
        witness=Witness(page); button.installEventFilter(witness)
        shield=None
        if blocked:
            shield=QPushButton('shield',f); shield.setGeometry(button.geometry()); shield.show(); shield.raise_(); shield.installEventFilter(witness)
            assert page.childAt(point) is shield
        words=rig.words(f.keySequence()); before=s37.invariant(rig,w,page)
        writes,calls,chords=s37.observe(rig,w,page)
        QTest.mouseClick(page.windowHandle(),Qt.LeftButton,pos=point); QApplication.processEvents()
        target=shield if blocked else button
        assert received==[(target,QEvent.MouseButtonPress),(target,QEvent.MouseButtonRelease)]
        if blocked:
            quiet(f,words); assert not writes and not chords and not any(calls.values())
        else:
            quiet(f,''); assert QApplication.focusWidget() is f
            assert len(calls['set_shortcut'])==int(row=='copy') and not calls['set_hotkey'] and len(writes)==int(row=='copy') and not chords
            QTest.mouseClick(page.windowHandle(),Qt.LeftButton,pos=point); QApplication.processEvents()
            assert len(writes)==int(row=='copy')
            if row=='hotkey':
                assert s33.bytes_(w)==before[0] and tuple(rig.backend.calls)==before[1] and dict(rig.backend.held)==before[2]
            s35.place(rig,page.hotkey_reset); quiet(f,words if row=='hotkey' else '')
    visit(rig,w,action)
    if not blocked and row=='copy': visit(rig,w,lambda page: quiet(page.edits['copy'],''))


@pytest.mark.parametrize('phase',['beat','minimizing','armed'])
def test_R2_try_focus_order(rig,case,phase):
    from PySide6.QtCore import QObject
    w,native,captured=s33.raw_setup(rig,s33.Case(11,case.platform,'D','open'))
    def action(page):
        f=page.hotkey_edit; old=page.hotkey_reset; s35.place(rig,old)
        if phase=='minimizing': rig.monkeypatch.setattr(w,'showMinimized',lambda:None)
        s33.menu_try(w)
        if phase!='beat': w.key_clock.advance(1000)
        assert w._key_try['phase']==phase and QApplication.focusWidget() is old
        stale=[cb for _,cb in w.key_clock.queue]; raw=native.raw(); backend=w.hotkey._backend
        trace=[]; end=w.end_key_try
        def ending(reason='',restore=False):
            active=w._key_try is not None
            result=end(reason,restore)
            if active: trace.append(('end',QApplication.focusWidget(),w._key_try))
            return result
        rig.monkeypatch.setattr(w,'end_key_try',ending)
        class Witness(QObject):
            def eventFilter(self,obj,event):
                if event.type() in (QEvent.FocusAboutToChange,QEvent.FocusOut,QEvent.FocusIn):
                    trace.append((event.type(),obj,w._key_try))
                    if event.type()==QEvent.FocusIn and obj is f:
                        s33.dispatch_to(rig,backend,raw)  # stale native callback at arrival entry
                        assert not captured
                return False
        witness=Witness(page); old.installEventFilter(witness); f.installEventFilter(witness)
        def changed(a,b): trace.append(('changed',(a,b),w._key_try))
        QApplication.instance().focusChanged.connect(changed)
        try:
            point=f.mapTo(page,f.rect().center()); assert page.childAt(point) is f
            QTest.mouseClick(page.windowHandle(),Qt.LeftButton,pos=point)
            QApplication.processEvents()
            ends=[r for r in trace if r[0]=='end']; assert ends==[('end',old,None)], trace
            entries=[i for i,r in enumerate(trace) if r[0]==QEvent.FocusIn and r[1] is f]
            assert entries and trace.index(ends[0])<entries[0] and trace[entries[0]][2] is None,trace
            assert ('changed',(old,f),None) in trace and QApplication.focusWidget() is f
            for cb in stale: cb()
            s33.dispatch_to(rig,backend,raw); w.key_clock.advance(20000)
            assert not captured and w._key_try is None and len([r for r in trace if r[0]=='end'])==1
        finally: QApplication.instance().focusChanged.disconnect(changed)
    visit(rig,w,action)


def r2_platform(r,platform):
    r.monkeypatch.setattr(r.cap,'IS_WINDOWS',platform=='win32')
    r.monkeypatch.setattr(r.cap.macos,'IS_MAC',platform=='darwin')
    r.monkeypatch.setattr(r.cap,'_monitors',lambda:{})
    r.monkeypatch.setattr(r.cap,'win32',s10.SimpleNamespace(
        list_windows=lambda:[],
        window_under_point=lambda x,y,exclude,windows:next((w for w in windows if w.rect.contains(x,y)),None)))


@pytest.mark.parametrize('platform',['darwin','win32'])
@pytest.mark.parametrize('remembered',[False,True])
@pytest.mark.parametrize('finish',['pick','cancel','escape'])
def test_R2_remembered_freeze(capture_rig,platform,remembered,finish):
    r=capture_rig; r2_platform(r,platform)
    r.monkeypatch.setattr(r.cap.LiveOverlay,'supports_translucency',lambda ov:ov.grab.screen is r.screens[0])
    session,results=r.start(freeze=remembered,timer=5)
    first=session.bar
    assert not first.freeze_button.isEnabled(), 'Go live became actionable before session capability was established'
    s10.settle(session)
    for ov in session.overlays:
        session.pointer_on(ov); bar=session.bar
        assert session.freeze and not bar.freeze_button.isEnabled() and not bar.timer_button.isEnabled()
        assert bar.freeze_button.toolTip()=='Live capture is unavailable on this display.'
        assert bar.timer_button.text()=='Wait after pick · 5 s'
        QTest.mouseClick(bar.freeze_button,Qt.LeftButton)
    assert session.settings.value('capture/freeze',False,type=bool)==remembered
    assert session.settings.value('capture/timer',type=int)==5
    for screen in r.screens:
        def late(ident, screen=screen):
            screen.calls.append(ident)
            image=QImage(1800,1200,QImage.Format_RGB32); image.fill(QColor('#dd2200')); return QPixmap.fromImage(image)
        r.monkeypatch.setattr(screen,'grabWindow',late)
    if finish=='pick':
        s10.drag(session.overlays[0]); assert len(results)==1 and results[0].image.pixelColor(0,0)==QColor('#336699')
    elif finish=='cancel': QTest.mouseClick(session.bar.cancel_button,Qt.LeftButton); assert results==[None]
    else: QTest.keyClick(session.overlays[0],Qt.Key_Escape); assert results==[None]
    session._tick(); session._settled(); assert len(results)==1 and sum(map(lambda s:len(s.calls),r.screens))==2
    r.monkeypatch.setattr(r.cap.LiveOverlay,'supports_translucency',lambda _:True)
    again,out=r.start()
    if remembered: s10.settle(again)
    assert again.freeze==remembered and again.timer==5 and again.bar.freeze_button.isEnabled()
    assert not again._forced_freeze
    QTest.mouseClick(again.bar.cancel_button,Qt.LeftButton); assert out==[None]


@pytest.mark.parametrize('platform',['darwin','win32'])
@pytest.mark.parametrize('lost',[False,True])
def test_R2_thaw_boundary(capture_rig,platform,lost):
    r=capture_rig; r2_platform(r,platform)
    session,results=r.start(freeze=True,timer=5); s10.settle(session)
    assert session.bar.freeze_button.isEnabled()
    session.select(session.overlays[0],QRectF(120,120,200,100))
    old=session.selected; pixels=old.grab.image.copy(); area=QRectF(old.area); bar=session.bar
    if lost: r.monkeypatch.setattr(r.cap.LiveOverlay,'supports_translucency',lambda _:False)
    QTest.mouseClick(bar.freeze_button,Qt.LeftButton)
    if lost:
        assert session.freeze and session.selected is old and old.area==area and old.grab.image==pixels and session.bar is bar
        assert session.settings.value('capture/freeze',type=bool) and not bar.freeze_button.isEnabled()
        session.shoot(); assert len(results)==1 and results[0].image.pixelColor(0,0)==QColor('#336699')
    else:
        assert not session.freeze and session.bar.timer_button.isEnabled() and session.timer==5
        assert session.bar.freeze_button.toolTip()=='Hold the screen now while you choose'
        s10.drag(old); assert session.remaining==5
        for _ in range(5): session._tick()
        def late(ident):
            image=QImage(1800,1200,QImage.Format_RGB32); image.fill(QColor('#dd2200')); return QPixmap.fromImage(image)
        r.monkeypatch.setattr(old.grab.screen,'grabWindow',late)
        s10.settle(session); assert len(results)==1 and results[0].image.pixelColor(0,0)==QColor('#dd2200')


@pytest.mark.parametrize('platform',['darwin','win32'])
@pytest.mark.parametrize('mode',['window','area'])
@pytest.mark.parametrize('gesture',['click','drag'])
def test_R2_frozen_instructions_and_pixels(capture_rig,platform,mode,gesture,tmp_path):
    r=capture_rig; r2_platform(r,platform)
    session,results=r.start(mode=mode,freeze=True,timer=5); s10.settle(session)
    ov=session.overlays[0]; bar=session.bar
    expected=('Screen frozen. No window is available. Choose Area or Whole screen. The picture is already taken, so the wait is off.' if mode=='window' else
              'Screen frozen. Drag an area or click for the whole screen. The picture is already taken, so the wait is off.')
    assert bar.help.text()==expected and bar.help.accessibleDescription()==expected
    assert ov.hint()==('No window is available · Choose Area or Whole screen · Esc to cancel' if mode=='window' else 'Drag an area · Click for the whole screen · Esc to cancel')
    assert bar.freeze_button.toolTip()=='Resume live capture. Your 5-second wait starts after you pick.'
    if mode=='window':
        QTest.mouseClick(ov,Qt.LeftButton,pos=QPoint(150,150)); assert not results
        QTest.mouseClick(bar.mode_buttons['area'],Qt.LeftButton)
        assert session.mode=='area'
    # Frame color is a separate rendering witness before the real gesture.
    session.select(ov,QRectF(120,120,200,100))
    image=QImage(ov.size(),QImage.Format_ARGB32); image.fill(Qt.transparent); ov.render(image)
    assert image.pixelColor(119,170)==QColor('#E53935')
    assert bar.grab().save(str(tmp_path/'fresh-frozen-bar.png'))
    if gesture=='drag': s10.drag(ov)
    else: QTest.mouseClick(ov,Qt.LeftButton,pos=QPoint(150,150))
    assert len(results)==1 and results[0].image.pixelColor(0,0)==QColor('#336699')
    assert results[0].image.size().toTuple()==((400,200) if gesture=='drag' else (1800,1200))
    assert results[0].title is None


@pytest.mark.parametrize('phase',['beat','minimizing','armed'])
@pytest.mark.parametrize('recipient',['copy','reset','off'])
@pytest.mark.parametrize('key',[Qt.Key_Shift,Qt.Key_F8,Qt.Key_Tab,Qt.Key_Escape,Qt.Key_Return])
def test_R2_try_keyboard_focus_route(rig,case,phase,recipient,key):
    """Each independent Try has a no-Try twin at the actual recipient."""
    def trial(trying):
        w,native,captured=s33.raw_setup(rig,s33.Case(11,case.platform,'D','open'))
        def action(page):
            target={'copy':page.edits['copy'],'reset':page.hotkey_reset,'off':page.hotkey_off}[recipient]
            s35.place(rig,target)
            stale=[]; endings=[]; raw=native.raw(); backend=w.hotkey._backend
            if trying:
                if phase=='minimizing': rig.monkeypatch.setattr(w,'showMinimized',lambda:None)
                s33.menu_try(w)
                if phase!='beat': w.key_clock.advance(1000)
                assert w._key_try['phase']==phase
                stale=[cb for _,cb in w.key_clock.queue]
            assert QApplication.focusWidget() is target
            end=w.end_key_try
            def ending(reason='',restore=False):
                active=w._key_try is not None; result=end(reason,restore)
                if active: endings.append((reason,QApplication.focusWidget()))
                return result
            rig.monkeypatch.setattr(w,'end_key_try',ending)
            writes,calls,chords=s37.observe(rig,w,page)
            edge(QApplication.focusWidget(),key,S if key==Qt.Key_Shift else N)
            focus=QApplication.focusWidget()
            focused=('copy' if focus is page.edits['copy'] else 'copy-reset' if focus is page.resets['copy'] else
                     'reset' if focus is page.hotkey_reset else 'off' if focus is page.hotkey_off else 'other')
            result=(focused,page.isVisible(),page.edits['copy'].text(),page.edits['copy']._paint_parts,
                    page.hotkey_edit.text(),page.message.text(),page.hotkey_off.isChecked(),
                    tuple(q.toString() for q in chords),tuple(len(calls[k]) for k in ('set_shortcut','set_hotkey')),len(writes))
            if trying:
                assert endings==[('Try cancelled',target)]
                assert w._key_try is None
                after=s37.invariant(rig,w,page)
                for cb in stale: cb()
                s33.dispatch_to(rig,backend,raw); w.key_clock.advance(20000)
                assert s37.invariant(rig,w,page)==after and endings==[('Try cancelled',target)]
            assert not captured
            return result
        return visit(rig,w,action)
    assert trial(True)==trial(False)


@pytest.mark.parametrize('row',['copy','hotkey'])
def test_R2_overtaken_reopen_and_invoke(rig,case,row,white):
    from annotshot.scene import Document
    if row=='hotkey': w,native,captured=s33.raw_setup(rig,s33.Case(11,case.platform,'D','open'))
    else:
        w=s33.setup(rig,case); white.setPixelColor(0,0,QColor('#e83319')); w._bind(Document(white))
    def action(page):
        f=field_for(page,row); s35.place(rig,f); original=f._present; fired=[]; chords=[]
        f.chordEntered.connect(chords.append)
        def present(*args):
            original(*args)
            if fired:return
            fired.append(True)
            if row=='hotkey':
                assert w.set_hotkey(s33.QKeySequence('F9'),False,True) is None
                page._restore_capture_field()
            else:
                assert w.set_shortcut('copy',s33.QKeySequence('F9')) is None
                page._show_key('copy')
        rig.monkeypatch.setattr(f,'_present',present)
        edge(f,Qt.Key_F8); release(f,Qt.Key_F8)
        assert not chords; quiet(f,'F9')
    visit(rig,w,action)
    visit(rig,w,lambda page:quiet(field_for(page,row),'F9'))
    w.activateWindow(); w.view.setFocus(); QApplication.processEvents()
    if row=='hotkey':
        assert w.hotkey.sequence==s33.QKeySequence('F9') and w.hotkey.registered and not w.hotkey_off()
        w.key_clock.advance(1); native.dispatch(native.raw()); assert captured==[1]
    else:
        QApplication.clipboard().clear(); QTest.keyClick(w.view.viewport(),Qt.Key_F9); QApplication.processEvents()
        image=QApplication.clipboard().image()
        assert not image.isNull() and image.pixelColor(0,0)==QColor('#e83319')


@pytest.mark.parametrize('platform',['darwin','win32'])
@pytest.mark.parametrize('inside',[False,True])
def test_R2_frozen_populated_area(capture_rig,platform,inside):
    r=capture_rig; r2_platform(r,platform)
    rect=QRect(200,200,480,320) if platform=='win32' else QRectF(100,100,240,160)
    window=s10.SimpleNamespace(hwnd=99,title='Marked Window',rect=rect)
    r.monkeypatch.setattr(r.cap.win32,'list_windows',lambda:[window])
    r.monkeypatch.setattr(r.cap.macos,'list_windows',lambda:[window])
    session,results=r.start(mode='area',freeze=True,timer=5); s10.settle(session)
    ov=session.overlays[0]
    if platform=='win32':
        assert ov.hint()=='Drag an area · Click a window to capture it · Click outside windows for the whole screen · Esc to cancel'
    else: assert ov.hint()=='Drag an area · Click for the whole screen · Esc to cancel'
    QTest.mouseClick(ov,Qt.LeftButton,pos=QPoint(150,150) if inside else QPoint(600,300))
    assert len(results)==1 and results[0].image.pixelColor(0,0)==QColor('#336699')
    picked=inside and platform=='win32'
    assert results[0].image.size().toTuple()==((480,320) if picked else (1800,1200))
    assert results[0].title==('Marked Window' if picked else None)


@pytest.mark.parametrize('platform',['darwin','win32'])
@pytest.mark.parametrize('timer',[0,3,5,10])
def test_R2_tooltip_and_narrow_controls(capture_rig,platform,timer,tmp_path):
    r=capture_rig; r2_platform(r,platform)
    r.screens[0]._geometry=QRect(0,0,420,360); r.screens[1]._geometry=QRect(-320,0,320,360)
    session,results=r.start(mode='window',freeze=True,timer=timer); s10.settle(session)
    for ov in session.overlays:
        session.pointer_on(ov); QApplication.processEvents(); bar=session.bar
        assert ov.rect().contains(bar.geometry())
        assert bar.rect().contains(bar.cancel_button.geometry()) and bar.cancel_button.isVisible()
        assert bar.help.height()>=bar.help.fontMetrics().height()*2
        expected=f'Resume live capture. Your {timer}-second wait starts after you pick.' if timer else 'Resume live capture. Your next pick takes the picture immediately.'
        assert bar.freeze_button.toolTip()==expected and bar.freeze_button.accessibleDescription()==expected
        assert bar.grab().save(str(tmp_path/f'bar-{platform}-{timer}-{ov.width()}.png'))
    QTest.mouseClick(session.bar.freeze_button,Qt.LeftButton)
    assert not session.freeze and session.bar.timer_button.isEnabled()
    assert session.bar.freeze_button.toolTip()=='Hold the screen now while you choose'
    QTest.mouseClick(session.bar.freeze_button,Qt.LeftButton); s10.settle(session)
    assert session.freeze and session.bar.freeze_button.toolTip()==expected
    QTest.mouseClick(session.bar.cancel_button,Qt.LeftButton); assert results==[None]


@pytest.mark.parametrize('phase',['beat','minimizing','armed'])
def test_R2_try_departure_is_not_return(rig,case,phase):
    w,native,captured=s33.raw_setup(rig,s33.Case(11,case.platform,'D','open'))
    def action(page):
        old=page.hotkey_reset; s35.place(rig,old)
        if phase=='minimizing': rig.monkeypatch.setattr(w,'showMinimized',lambda:None)
        s33.menu_try(w)
        if phase!='beat': w.key_clock.advance(1000)
        attempt=w._key_try
        # The departure edge alone says nothing about a return destination.
        QApplication.sendEvent(old,QEvent(QEvent.FocusAboutToChange))
        from PySide6.QtGui import QFocusEvent
        QApplication.sendEvent(old,QFocusEvent(QEvent.FocusOut,Qt.ActiveWindowFocusReason))
        assert w._key_try is attempt and attempt['phase']==phase and not captured
        w.end_key_try('Try cancelled')
    visit(rig,w,action)


@pytest.mark.parametrize('row',['copy','hotkey'])
def test_R2_altgr_foreign_repeat_and_preedit(rig,case,row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f)
        # Preserve a genuine refusal as well as a working binding.
        edge(f,Qt.Key_Z,C,scan=44); release(f,Qt.Key_Z,C,scan=44)
        assert page.message.text()
        before=s37.invariant(rig,w,page); words=rig.words(f.keySequence())
        writes,calls,chords=s37.observe(rig,w,page)
        QApplication.sendEvent(f,QInputMethodEvent('candidate',[]))
        edge(f,Qt.Key_AltGr,Qt.GroupSwitchModifier,scan=100,virtual=65027)
        release(f,Qt.Key_AltGr,scan=999,virtual=65027)  # conflicting known scan
        edge(f,Qt.Key_AltGr,Qt.GroupSwitchModifier,scan=100,virtual=65027,repeat=True)
        edge(f,Qt.Key_AltGr,N,QEvent.KeyRelease,scan=100,virtual=65027,repeat=True)
        edge(f,Qt.Key_Q,C|A,text='@'); release(f,Qt.Key_Q,C|A)
        quiet(f,words); assert s37.invariant(rig,w,page)==before
        assert not writes and not chords and not any(calls.values())
        release(page.resets['copy'],Qt.Key_AltGr,virtual=65027)  # unique partial id
        edge(f,Qt.Key_E,text='é'); release(f,Qt.Key_E)
        quiet(f,words); assert s37.invariant(rig,w,page)==before and not chords
        QApplication.sendEvent(f,QInputMethodEvent('',[]))  # its own terminal
        edge(f,Qt.Key_Control,C,scan=29); edge(f,Qt.Key_Alt,C|A,scan=56)
        edge(f,Qt.Key_Q,C|A); release(f,Qt.Key_Q,C|A)
        assert chords==[s33.QKeySequence('Ctrl+Alt+Q')]
        release(f,Qt.Key_Control,A,scan=29); release(f,Qt.Key_Alt,scan=56)
    visit(rig,w,action)


@pytest.mark.parametrize('platform',['darwin','win32'])
def test_R2_forced_empty_window_escape(capture_rig,platform):
    r=capture_rig; r2_platform(r,platform)
    r.screens[0]._geometry=QRect(0,0,320,360)
    r.monkeypatch.setattr(r.cap.LiveOverlay,'supports_translucency',lambda _:False)
    session,results=r.start(mode='window',freeze=True,timer=5); s10.settle(session)
    ov=session.overlays[0]; bar=session.bar
    assert bar.help.text()==('Live capture is unavailable on this display. No window is available. '
        'Choose Area or Whole screen from this still, or cancel. The picture is already taken, so the wait is off.')
    assert ov.hint()=='No window is available · Choose Area or Whole screen · Esc to cancel'
    assert not bar.freeze_button.isEnabled() and not bar.timer_button.isEnabled()
    assert ov.rect().contains(bar.geometry()) and bar.rect().contains(bar.cancel_button.geometry())
    QTest.mouseClick(ov,Qt.LeftButton,pos=QPoint(15,5)); assert not results
    QTest.mouseClick(bar.mode_buttons['area'],Qt.LeftButton)
    expected=('Live capture is unavailable on this display. '
              'Drag an area or click for the whole screen from this still, or cancel. '
              'The picture is already taken, so the wait is off.')
    assert bar.help.text()==expected and bar.help.accessibleDescription()==expected
    assert ov.hint()=='Drag an area · Click for the whole screen · Esc to cancel'
    assert not bar.geometry().contains(QPoint(15,5)) and not bar.geometry().contains(QPoint(85,15))
    s10.drag(ov,QPoint(15,5),QPoint(85,15))
    assert len(results)==1 and results[0].image.size().toTuple()==(140,20)
    assert results[0].image.pixelColor(0,0)==QColor('#336699') and results[0].title is None


# s43e3: the review's missing edges, before changing the reviewed product.
@pytest.mark.parametrize('row',['copy','hotkey'])
@pytest.mark.parametrize('publication',['echo','new','new-then-echo'])
def test_R3_publication_during_owner_callback(rig,case,row,publication):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f)
        original=f.settleChord; receipts=[]; observations=[]
        def settle(sequence,taken,*,origin=None):
            receipts.append(origin)
            # The real owner has already received F8 and echoed its result.
            assert origin==s33.QKeySequence('F8') and f.keySequence()==s33.QKeySequence('F8')
            if publication!='echo':
                if row=='hotkey':
                    assert w.set_hotkey(s33.QKeySequence('F9'),False,True) is None
                    page._restore_capture_field()
                else:
                    assert w.set_shortcut('copy',s33.QKeySequence('F9')) is None
                    page._show_key('copy')
                quiet(f,'F9')
                if publication=='new-then-echo':
                    f.setKeySequence(s33.QKeySequence('F8'))
                    f.setKeySequence(s33.QKeySequence('F9'))
            original(sequence,taken,origin=origin)
            observations.append((f.text(),tuple(p[4] for p in f._paint_parts)))
        rig.monkeypatch.setattr(f,'settleChord',settle)
        writes,calls,chords=s37.observe(rig,w,page)
        edge(f,Qt.Key_F8)
        expected='F8' if publication=='echo' else 'F9'
        assert chords==[s33.QKeySequence('F8')] and len(receipts)==1
        assert observations==[(expected,(publication=='echo',))]
        assert f.keySequence()==s33.QKeySequence(expected)
        assert (w.hotkey_sequence() if row=='hotkey' else w.a_copy.shortcut())==s33.QKeySequence(expected)
        release(f,Qt.Key_F8); quiet(f,expected)
        assert sum(map(len,calls.values()))==(1 if publication=='echo' else 2)
    visit(rig,w,action)


@pytest.mark.parametrize('siblings',[1,2])
def test_R3_foreign_altgr_makes_no_query(own,case,monkeypatch,siblings):
    from annotshot import shortcut_field
    f,_,_=own; reads=[]
    monkeypatch.setattr(shortcut_field,'_altgr_all_up',lambda:(reads.append(1),True)[1])
    for scan in range(100,100+siblings):
        edge(f,Qt.Key_AltGr,Qt.GroupSwitchModifier,scan=scan,virtual=65027)
    before=dict(f._presses.records)
    release(f,Qt.Key_AltGr,scan=999,virtual=65027)
    assert reads==[], 'a known foreign scan is not an ambiguous compatible release'
    assert f._presses.records==before


@pytest.mark.parametrize('row',['copy','hotkey'])
def test_R3_fkey_preserves_preedit_through_owner_echo(rig,case,row):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f)
        QApplication.sendEvent(f,QInputMethodEvent('candidate',[]))
        edge(f,Qt.Key_AltGr,Qt.GroupSwitchModifier,scan=100,virtual=65027)
        observed=[]
        f.chordEntered.connect(lambda seq:observed.append((s33.QKeySequence(seq),f._composition)))
        writes,calls,chords=s37.observe(rig,w,page)
        edge(f,Qt.Key_F8); release(f,Qt.Key_F8)
        assert observed==[(s33.QKeySequence('F8'),'preedit')]
        assert f._composition=='preedit'; quiet(f,'F8')
        release(f,Qt.Key_AltGr,scan=100,virtual=65027)
        before=s37.invariant(rig,w,page); counts=(len(writes),sum(map(len,calls.values())))
        edge(f,Qt.Key_E,text='é'); release(f,Qt.Key_E)
        quiet(f,'F8')
        assert s37.invariant(rig,w,page)==before
        assert chords==[s33.QKeySequence('F8')] and (len(writes),sum(map(len,calls.values())))==counts
        QApplication.sendEvent(f,QInputMethodEvent('',[]))
        edge(f,Qt.Key_F9); release(f,Qt.Key_F9)
        assert chords==[s33.QKeySequence('F8'),s33.QKeySequence('F9')]
        quiet(f,'F9')
    visit(rig,w,action)


@pytest.mark.parametrize('row,draft',[('copy',False),('hotkey',False),('hotkey',True)])
def test_R3_repeated_mixed_preview(rig,case,row,draft):
    w=s33.setup(rig,case)
    def action(page):
        f=field_for(page,row); s35.place(rig,f)
        if draft:s33.click(rig,f.clearButton())
        words='' if draft else rig.words(f.keySequence())
        before=s37.invariant(rig,w,page); writes,calls,chords=s37.observe(rig,w,page)
        edge(f,Qt.Key_Shift,S,scan=50); edge(f,Qt.Key_Control,S|C,scan=55)
        release(f,Qt.Key_Shift,C,scan=50); quiet(f,words)
        edge(f,Qt.Key_Shift,S|C,scan=50)
        assert f.text()==('Shift+Command' if case.platform=='darwin' else 'Ctrl+Shift')
        assert all(p[3:]==('preview',True) for p in f._paint_parts)
        stale=f._preview_callback
        release(f,Qt.Key_Control,S,scan=55)
        quiet(f,words)
        assert description(f)=='Hold a modifier and press another key.'
        stale(); quiet(f,words)
        assert QApplication.focusWidget() is f and s37.invariant(rig,w,page)==before
        assert not writes and not chords and not any(calls.values())
        edge(f,Qt.Key_J,S); assert chords==[s33.QKeySequence('Shift+J')]
        release(f,Qt.Key_J,S); release(f,Qt.Key_Shift,scan=50); quiet(f,'Shift+J')
    visit(rig,w,action)


@pytest.mark.parametrize('platform',['darwin','win32'])
def test_R3_lost_live_area_instructions(capture_rig,platform):
    r=capture_rig; r2_platform(r,platform)
    session,results=r.start(mode='area',freeze=True,timer=5); s10.settle(session)
    ov=session.overlays[0]; bar=session.bar
    r.monkeypatch.setattr(r.cap.LiveOverlay,'supports_translucency',lambda _:False)
    QTest.mouseClick(bar.freeze_button,Qt.LeftButton)
    expected=('Live capture is unavailable on this display. '
              'Drag an area or click for the whole screen from this still, or cancel. '
              'The picture is already taken, so the wait is off.')
    assert bar.help.text()==expected and bar.help.accessibleDescription()==expected
    assert ov.hint()=='Drag an area · Click for the whole screen · Esc to cancel'
    assert not bar.freeze_button.isEnabled() and not bar.timer_button.isEnabled()
    s10.drag(ov); assert len(results)==1 and results[0].image.pixelColor(0,0)==QColor('#336699')


@pytest.mark.parametrize('row',['copy','hotkey'])
@pytest.mark.parametrize('name',['light','dark','retro'])
@pytest.mark.parametrize('dpr',[1,2])
def test_R3_active_layout_ink_caret_and_clear(rig,case,row,name,dpr,tmp_path,record_property):
    from annotshot import shortcut_field
    from PySide6.QtGui import QIcon, QPainter
    w=s33.setup(rig,case); theme.apply(rig.qapp,name)
    def action(page):
        f=field_for(page,row); s35.place(rig,f)
        f.setKeySequence(s33.QKeySequence('Alt+Shift+Space'))
        natural=f.width(); frames=[]; widths=[]; ink=[]; carets=[]; omit_caret=[False]
        draw=shortcut_field._ink; fill=QPainter.fillRect
        def drawing(p,rect,word,*args,**kwargs):
            ink.append((QRectF(rect),word)); return draw(p,rect,word,*args,**kwargs)
        def filling(p,*args):
            if len(args)==2 and hasattr(args[0],'width') and args[0].width()==1.5:
                carets.append(QRectF(args[0]))
                if omit_caret[0]:return
            return fill(p,*args)
        rig.monkeypatch.setattr(shortcut_field,'_ink',drawing)
        rig.monkeypatch.setattr(QPainter,'fillRect',filling)
        def render():
            image=QImage(f.width()*dpr,f.height()*dpr,QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr); image.fill(Qt.transparent); f.render(image)
            return image
        def differs(a,b,rect):
            bounds=rect.toAlignedRect().intersected(f.rect())
            return [(x,y) for y in range(bounds.top()*dpr,(bounds.bottom()+1)*dpr)
                    for x in range(bounds.left()*dpr,(bounds.right()+1)*dpr)
                    if a.pixel(x,y)!=b.pixel(x,y)]
        for stage in ('normal','80','restored'):
            f.setMaximumWidth(80 if stage=='80' else 16777215)
            page.layout().activate(); QApplication.processEvents()
            assert page.layout().isEnabled() and f.width()==(80 if stage=='80' else natural)
            widths.append(f.width()); ink.clear(); carets.clear()
            image=render(); frames.append(image)
            expected=['Option' if case.platform=='darwin' else 'Alt','Shift','Space']
            words=[word for _,word in ink]
            if stage=='80':
                assert len(words)==3 and all(short and short[0]==word[0] for short,word in zip(words,expected))
            else:assert words==expected
            assert carets and all(r.right()<=f.clearButton().x() for r in carets)
            assert QApplication.focusWidget() is f
            # Actual raster evidence for the caret, beyond a painter-call spy.
            caret=carets[-1]
            omit_caret[0]=True; no_caret=render(); omit_caret[0]=False
            assert differs(image,no_caret,caret), 'the focused caret has no rendered ink'
            assert all(x+width<=f.clearButton().x()-2+.001 for x,y,width,height in f._paint_slots)
            # Removing only text must remove ink inside every painted cap.
            rig.monkeypatch.setattr(shortcut_field,'_ink',lambda *a,**k:None)
            no_ink=render()
            rig.monkeypatch.setattr(shortcut_field,'_ink',drawing)
            assert all(differs(image,no_ink,QRectF(*slot)) for slot in f._paint_slots)
            button=f.clearButton(); icon=button.icon()
            assert button.isVisible() and not icon.isNull() and f.rect().contains(button.geometry())
            button.setIcon(QIcon()); no_glyph=render(); button.setIcon(icon)
            glyph=differs(image,no_glyph,QRectF(button.geometry()))
            assert glyph, 'the visible clear glyph has no rendered ink'
            xs=[x for x,y in glyph]; ys=[y for x,y in glyph]
            point=f.mapTo(page,QPoint(round((min(xs)+max(xs))/(2*dpr)),round((min(ys)+max(ys))/(2*dpr))))
            assert page.childAt(point) is button
            assert image.save(str(tmp_path/f'{row}-{name}-{dpr}-{stage}.png'))
        record_property('active_layout_widths',','.join(map(str,widths)))
        assert frames[0]==frames[2] and frames[0].size()!=frames[1].size()
    visit(rig,w,action)


@pytest.mark.parametrize('phase',['beat','minimizing','armed'])
@pytest.mark.parametrize('key',[Qt.Key_Shift,Qt.Key_F8,Qt.Key_Return])
def test_R3_try_return_from_outside_settings(rig,case,phase,key,record_property):
    """Qt focus restoration is real; OS activation/forwarding is caller-owned."""
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget
    def trial(trying):
        w,native,captured=s33.raw_setup(rig,s33.Case(11,case.platform,'D','open'))
        def action(page):
            f=page.hotkey_edit; s35.place(rig,f)
            # A distinct top-level Qt window owns the departure focus. The
            # remembered child of Settings remains the global key field.
            outside=QWidget(); box=QVBoxLayout(outside); editor=QLineEdit(outside); box.addWidget(editor)
            outside.show(); outside.activateWindow(); editor.setFocus(); QApplication.processEvents()
            assert QApplication.focusWidget() is editor and page.focusWidget() is f
            if phase=='minimizing':rig.monkeypatch.setattr(w,'showMinimized',lambda:None)
            if trying:
                s33.menu_try(w)
                if phase!='beat':w.key_clock.advance(1000)
                assert w._key_try['phase']==phase
            assert QApplication.focusWidget() is editor
            trace=[]; stale=[cb for _,cb in w.key_clock.queue]; raw=native.raw(); backend=w.hotkey._backend
            ending=w.end_key_try
            def end(reason='',restore=False):
                active=w._key_try is not None; result=ending(reason,restore)
                if active:trace.append(('end',QApplication.focusWidget(),w._key_try))
                return result
            rig.monkeypatch.setattr(w,'end_key_try',end)
            class Witness(QObject):
                def eventFilter(self,obj,event):
                    if event.type() in (QEvent.WindowActivate,QEvent.WindowDeactivate,QEvent.FocusAboutToChange,QEvent.FocusOut,QEvent.FocusIn):
                        trace.append((event.type(),obj,w._key_try))
                    if event.type()==QEvent.FocusIn and obj is f:
                        s33.dispatch_to(rig,backend,raw)
                        assert not captured
                    return False
            witness=Witness(page)
            for widget in (page,f,editor):widget.installEventFilter(witness)
            def changed(a,b):trace.append(('changed',(a,b),w._key_try))
            QApplication.instance().focusChanged.connect(changed)
            try:
                # Do not set child focus: normal top-level restoration must
                # select the remembered field before the first key is sent.
                page.showNormal(); page.activateWindow(); QApplication.processEvents()
                assert QApplication.focusWidget() is f
                arrivals=[i for i,r in enumerate(trace) if r[0]==QEvent.FocusIn and r[1] is f]
                assert arrivals and ('changed',(editor,f),None) in trace,trace
                if trying:
                    ends=[i for i,r in enumerate(trace) if r[0]=='end']
                    assert len(ends)==1 and ends[0]<arrivals[0] and trace[arrivals[0]][2] is None,trace
                writes,calls,chords=s37.observe(rig,w,page); effects=[]
                present=f._present
                def effect(*a,**k):
                    assert w._key_try is None
                    trace.append(('effect',QApplication.focusWidget(),w._key_try))
                    effects.append('present'); return present(*a,**k)
                rig.monkeypatch.setattr(f,'_present',effect)
                # Resolve the destination from QApplication after restoration.
                edge(QApplication.focusWidget(),key,S if key==Qt.Key_Shift else N)
                assert effects
                if key==Qt.Key_Shift:
                    shown(f,'Shift',((0,Qt.Key_Shift,'Shift','preview',True),)); assert not chords
                elif key==Qt.Key_F8:
                    assert chords==[s33.QKeySequence('F8')] and w.hotkey_sequence()==s33.QKeySequence('F8')
                else:
                    assert chords==[s33.QKeySequence('Return')] and page.message.text()==hotkey.NEED_MODIFIER
                result=(f.text(),f._paint_parts,page.message.text(),tuple(q.toString() for q in chords),
                        tuple(len(calls[k]) for k in ('set_shortcut','set_hotkey')),len(writes))
                after=s37.invariant(rig,w,page)
                for cb in stale:cb()
                s33.dispatch_to(rig,backend,raw); w.key_clock.advance(20000)
                assert s37.invariant(rig,w,page)==after and not captured
                assert len([r for r in trace if r[0]=='end'])==int(trying)
                return result
            finally:
                def label(obj):
                    if isinstance(obj,tuple):return '->'.join(label(item) for item in obj)
                    return 'global-field' if obj is f else 'outside-editor' if obj is editor else 'settings' if obj is page else 'none' if obj is None else type(obj).__name__
                record_property('try-return-trace' if trying else 'idle-return-trace',
                                ' | '.join(f'{kind}:{label(obj)}:try={attempt is not None}' for kind,obj,attempt in trace))
                record_property('native-activation-and-forwarding','unrun; Qt offscreen restoration and delivery only')
                QApplication.instance().focusChanged.disconnect(changed)
                outside.close(); outside.deleteLater()
        return visit(rig,w,action)
    assert trial(True)==trial(False)
