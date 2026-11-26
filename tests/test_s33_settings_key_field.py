from key_field_support import field_parts
"""s33's complete amended grid. Real Qt gestures, stubbed native boundaries.

Startup uses the same apply as app.py; every user-level action uses a widget.
Raw timed events stay outside the production adapters until dispatch.
"""
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit, QToolButton

import test_s30_key_button as s30
from annotshot import hotkey, settings_dialog

D, Y = s30.D, s30.Y
STATES = ('D', 'Y', 'U', 'O', 'R', 'F', 'TD', 'TY')
# One row per coverage-grid row, in its original order. Zero = unreachable.
GRID = [
 ('a_free',             (1,1,3,3,1,1,1,1)),
 ('b_taken',            (2,2,4,4,2,2,2,2)),
 ('c_copy',             (6,6,6,6,6,6,6,6)),
 ('d_invalid',          (6,6,6,6,6,6,6,6)),
 ('e_same_free',         (8,8,3,3,8,8,8,8)),
 ('e_same_taken',        (8,8,4,4,8,8,8,8)),
 ('e_legacy',            (0,6,6,6,0,6,0,6)),
 ('f_clear',             (6,6,6,6,6,6,6,6)),
 ('g_shift',             (6,6,6,6,6,6,6,6)),
 ('h_abandon',           (7,7,7,7,7,7,7,7)),
 ('i_focus',             (7,7,7,7,7,7,7,7)),
 ('j_reset_free',        (8,1,3,5,8,5,8,1)),
 ('j_reset_taken',       (8,2,4,5,8,5,8,2)),
 ('j_reset_copy',        (0,6,6,6,0,6,0,6)),
 ('k_off',               (9,9,9,0,9,0,9,9)),
 ('l_on_free',           (0,0,0,3,0,8,0,0)),
 ('l_on_taken',          (0,0,0,4,0,8,0,0)),
 ('l_on_invalid',        (0,0,0,6,0,6,0,0)),
 ('m_all_free',          (8,1,3,5,8,5,8,1)),
 ('m_all_taken',         (8,2,4,5,8,5,8,2)),
 ('n_empty_leave',       (6,6,6,6,6,6,6,6)),
 ('n_mid_leave',         (7,7,7,7,7,7,7,7)),
 ('o_off',               (9,9,9,0,9,0,9,9)),
 ('o_on_free',           (0,0,0,3,0,8,0,0)),
 ('o_on_taken',          (0,0,0,4,0,8,0,0)),
 ('o_on_invalid',        (0,0,0,6,0,6,0,0)),
 ('o_reset_free',        (8,1,3,5,8,5,8,1)),
 ('o_reset_taken',       (8,2,4,5,8,5,8,2)),
 ('o_reset_copy',        (0,6,6,6,0,6,0,6)),
 ('o_all_free',          (8,1,3,5,8,5,8,1)),
 ('o_all_taken',         (8,2,4,5,8,5,8,2)),
 ('native_focus',        (10,10,0,0,10,10,10,10)),
 ('open',                (7,7,7,7,7,7,11,11)),
]

@dataclass(frozen=True)
class Case:
    kid: int
    platform: str
    state: str
    action: str
    variant: str = 'ordinary'

    @property
    def name(self):
        return f'K{self.kid:02}_{self.platform}_{self.state}_{self.action}_{self.variant}'

CASES = []
for action, outcomes in GRID:
    for state, kid in zip(STATES, outcomes):
        if not kid:
            continue
        variants = ['ordinary']
        if action in ('f_clear', 'g_shift'):
            variants = ['ordinary', 'click']
        elif action == 'd_invalid':
            variants = ['bare', 'keypad', 'keypad_bare', 'unmappable']
        elif action == 'h_abandon':
            variants = ['escape', 'held']
        elif action in ('n_empty_leave', 'n_mid_leave'):
            variants = [f'{draft}_{leave}' for draft in (
                ['clear','released'] if action == 'n_empty_leave' else ['held'])
                for leave in ('close','window','tab')]
        elif action.startswith('o_'):
            variants = ['clear','released','held']
        if kid in (1,5,8,9):
            variants += [v + '_release_fail' for v in list(variants)]
        if kid in (2,4):
            variants += ['backend_error']
        for platform in ('darwin','win32'):
            CASES.extend(Case(7 if action in ('f_clear','g_shift','n_empty_leave') else kid,platform,state,action,v) for v in variants)
# Additional storage spellings and handle identities from the table's prose.
for platform in ('darwin','win32'):
    for action,kid in (('e_same_free',8),('j_reset_free',8),('m_all_free',8)):
        CASES.append(Case(kid,platform,'D',action,'explicit_D'))
    for action,kid in (('e_same_free',3),('e_same_taken',4),('l_on_free',3),('l_on_taken',4)):
        CASES.append(Case(kid,platform,'O',action,'remember_D'))
    CASES.append(Case(3,platform,'U','e_same_free','retry_ctrl_alt'))
    for action,kid in (('a_free',1),('b_taken',2)):
        CASES.append(Case(kid,platform,'R',action,'retained_target'))
        CASES.append(Case(kid,platform,'F',action,'two_handles_retained_target'))
    CASES.append(Case(9,platform,'R','k_off','primary_release_fail'))
    for action,kid in (('c_copy',6),('e_same_free',8),('i_focus',7)):
        CASES.append(Case(kid,platform,'D',action,'verified'))
    for action,kid in (('a_free',1),('b_taken',2),('e_same_free',8),('j_reset_free',5)):
        CASES.append(Case(kid,platform,'F',action,'two_handles'))
    for variant in ('focus','close','inactive','retained','retired'):
        CASES.append(Case(10,platform,'D','adapter_focus',variant))
    CASES.append(Case(9,platform,'U','k_off','legacy'))
    for state,kid in (('D',2),('O',4)):
        for variant in ('taken','backend_error'):
            CASES.append(Case(kid,platform,state,'adapter_refusal',variant))
# Native try boundary cases, plus the stale-outcome recovery paths.
for platform in ('darwin','win32'):
    for phase in ('beat','minimizing','armed','inactive_observer','first_input'):
        CASES.append(Case(11,platform,'TD','handoff',phase))
    for variant in ('before_choice','before_arm','same_tick','wrap_before','wrap_same'):
        if variant.startswith('wrap') and platform != 'win32':
            continue
        CASES.append(Case(12,platform,'TD','raw',variant))
    for variant in ('one_tick','later','no_timestamp'):
        CASES.append(Case(13,platform,'TD','raw',variant))
    for variant in ('swap','copy'):
        CASES.append(Case(14,platform,'D','reopen',variant))

@pytest.fixture
def rig(case, request, monkeypatch, qapp, private_settings):
    gen = s30.rig.__wrapped__(SimpleNamespace(param=case.platform), monkeypatch, qapp, private_settings)
    result = next(gen)
    # This constant is selected at import on an installed app. Model that
    # import-time platform choice as well as the runtime adapter path.
    monkeypatch.setattr(hotkey,'NEED_MODIFIER',
        'Use Control, Option, Shift or Command with the key (or an F key alone)'
        if case.platform=='darwin' else
        'Use Ctrl, Alt or Shift with the key (or an F key alone)')
    yield result
    try:
        next(gen)
    except StopIteration:
        pass


def visit(rig, w, action, *, full=True):
    """Enter the public modal Settings action; run gestures in its Qt loop."""
    errors = []
    result = []
    def run():
        page = next(d for d in w.findChildren(settings_dialog.SettingsDialog) if d.isVisible())
        try:
            # Historical full-list proofs enter through the real disclosure.
            # s43's folded-page proofs opt out; no input edge is replaced.
            more = getattr(page, 'more_shortcuts', None)
            if full and more is not None and not more.isChecked():
                QTest.mouseClick(more, Qt.LeftButton)
                rig.qapp.processEvents()
            result.append(action(page))
        except BaseException as exc:
            errors.append(exc)
        finally:
            page.reject()
    QTimer.singleShot(0, run)
    w.a_settings.trigger()
    rig.qapp.processEvents()
    if errors:
        raise errors[0]
    return result[0] if result else None


def focus(rig, page):
    page.activateWindow()
    page.hotkey_edit.setFocus()
    rig.qapp.processEvents()
    assert page.capture_key_has_focus()


def click(rig, button):
    QTest.mouseClick(button, Qt.LeftButton)
    rig.qapp.processEvents()


def chord(rig, page, seq, *, release=True):
    focus(rig,page)
    combo = QKeySequence(seq)[0]
    mods = combo.keyboardModifiers()
    modifier_keys = [(Qt.ControlModifier,Qt.Key_Control), (Qt.AltModifier,Qt.Key_Alt),
                     (Qt.ShiftModifier,Qt.Key_Shift), (Qt.MetaModifier,Qt.Key_Meta)]
    for flag,key in modifier_keys:
        if mods & flag:
            QTest.keyPress(page.hotkey_edit,key)
    QTest.keyPress(page.hotkey_edit,combo.key(),mods)
    # The outcome must already be observable before the base release.
    if release:
        QTest.keyRelease(page.hotkey_edit,combo.key(),mods)
        for flag,key in reversed(modifier_keys):
            if mods & flag:
                QTest.keyRelease(page.hotkey_edit,key)
    rig.qapp.processEvents()


def draft(rig,page,kind):
    focus(rig,page)
    rig.field_held = {Qt.Key_Shift} if kind == 'held' else set()
    if kind == 'clear':
        clear = field_parts(page.hotkey_edit)[1]
        assert clear is not None and clear.isVisible()
        click(rig,clear)
    else:
        QTest.keyPress(page.hotkey_edit,Qt.Key_Shift)
        if kind == 'released':
            QTest.keyRelease(page.hotkey_edit,Qt.Key_Shift)


def blur(rig,page):
    if not page.isVisible():
        return
    held = getattr(rig, 'field_held', set())
    if page.capture_key_has_focus() and not held.intersection((Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr)):
        mods = Qt.ShiftModifier if Qt.Key_Shift in held else Qt.NoModifier
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Tab, mods)
    else:
        page.edits['copy'].setFocus()
    rig.qapp.processEvents()
    assert not page.capture_key_has_focus()


def bytes_(w):
    w.settings.sync()
    p = Path(w.settings.fileName())
    return p.read_bytes() if p.exists() else b''


def captures(w):
    return {k:w.settings.value(k) for k in ('hotkey/sequence','hotkey/off') if w.settings.contains(k)}


def setup(rig,case,*,help_window=True):
    state,action = case.state,case.action
    invalid = 'invalid' in action or action == 'e_legacy'
    copy_default = action in ('j_reset_copy','o_reset_copy')
    saved = None if state in ('D','TD') else Y
    if case.variant=='explicit_D':
        saved=hotkey.DEFAULT
    elif case.variant=='remember_D':
        saved=hotkey.DEFAULT
    elif case.variant=='retry_ctrl_alt':
        saved='Ctrl+Alt+Y'
    elif case.variant=='legacy':
        saved='Alt+Num+1'
    if invalid and state in ('U','O'):
        saved = 'A'
    if invalid and state in ('Y','TY','F'):
        saved = 'Ctrl+C'
    local = 'Alt+8' if saved == 'Ctrl+C' else D if copy_default else None
    # These cases open Settings through its public modal action. Do not first
    # construct a second, unused 28-field dialog in the legacy s30 fixture.
    w = rig.create(saved=saved,off=state=='O',refused=[saved or D] if state=='U' else (),local=local,
                   settings_page=False,help_window=help_window)
    # Startup boundary, as in app.main; never used for a Settings gesture.
    w.apply_hotkey()
    w._s33_captures=[]
    rig.monkeypatch.setattr(w,'_may_record_screen',lambda: w._s33_captures.append(1) or False)
    rig.qapp.processEvents()
    w.show()
    w.activateWindow()
    rig.qapp.processEvents()
    if state == 'R':
        rig.backend.fail_release.add(w.hotkey._backend.identity)
        visit(rig,w,lambda p: click(rig,p.hotkey_reset))
        assert w.hotkey._retained
    elif state == 'F':
        if case.variant.startswith('two_handles'):
            rig.backend.fail_release.add(w.hotkey._backend.identity)
            visit(rig,w,lambda p: click(rig,p.hotkey_reset))
        rig.backend.fail_release.add(w.hotkey._backend.identity)
        visit(rig,w,lambda p: click(rig,p.hotkey_off))
        assert w.hotkey_off() and w.hotkey.registered
    if saved == 'Ctrl+C':
        # A held key becomes locally invalid through the reachable Reset all
        # path: restore Copy first, refuse D, keep the held key.
        if state in ('Y','TY'):
            rig.backend.refused.add(D)
            visit(rig,w,lambda p: click(rig,p.reset_all))
        else:
            visit(rig,w,lambda p: click(rig,p.resets['copy']))
    if state in ('TD','TY'):
        w.welcome.capture_bar.key_menu.actions()[0].trigger()
        w.key_clock.advance(1000)
        assert w._key_try is not None
    if case.variant=='verified':
        menu_try(w)
        w.key_clock.advance(1000)
        w.hotkey._backend.press()
        w.hotkey._backend.press(False)
        assert w._key_green
    if case.variant=='retry_ctrl_alt':
        w.statusBar().showMessage(w.capture_status(),10000)
    return w


def oracle(rig,w,page,case):
    """Check the transaction at its native, storage and published boundaries."""
    kid,action = case.kid,case.action
    # T columns hand off exactly once before the row action.
    if case.state in ('TD','TY'):
        assert w._key_try is None
        assert w.statusBar().currentMessage() == 'Try cancelled'
    initial = (captures(w),bytes_(w),list(rig.backend.calls),dict(rig.backend.held),
               w.key_state().copy(),w.statusBar().currentMessage())
    prefs,data,calls,held,incoming,status = initial
    local_prefs={k:w.settings.value(k) for k in w.settings.allKeys() if k.startswith('shortcuts/')}
    q = w.hotkey_sequence()
    h = QKeySequence(w.hotkey.sequence)
    old_id = w.hotkey._backend.identity if w.hotkey.registered else None
    retained = [(b.identity,QKeySequence(s)) for b,s in w.hotkey._retained]
    rig.backend.fail_release.clear()
    release_fail = 'release_fail' in case.variant
    primary_failure = case.variant=='primary_release_fail'
    if release_fail:
        if retained and not primary_failure:
            rig.backend.fail_release.add(retained[0][0])
        elif old_id is not None:
            rig.backend.fail_release.add(old_id)
    is_reset = '_reset_' in action or action.startswith('j_')
    is_all = '_all_' in action or action.startswith('m_')
    is_on = '_on_' in action or action.startswith('l_')
    is_off = action in ('k_off','o_off')
    target = QKeySequence(D if is_reset or is_all else q if action.startswith('e_') or is_on or is_off else 'Alt+X')
    if case.variant.endswith('retained_target'):
        target=QKeySequence(Y)
    if 'taken' in action:
        rig.backend.refused.add(target.toString(QKeySequence.PortableText))
    else:
        rig.backend.refused.discard(target.toString(QKeySequence.PortableText))
    if case.variant == 'backend_error':
        original = rig.backend.register
        def fail(backend,seq):
            rig.backend.calls.append(('register',seq.toString(QKeySequence.PortableText)))
            raise RuntimeError('stub backend unavailable')
        rig.monkeypatch.setattr(rig.backend,'register',fail)
    audit_active=[True]
    for method in ('register','unregister'):
        original=getattr(rig.backend,method)
        def guarded(backend,*args,_original=original):
            if audit_active[0]:
                assert captures(w)==prefs, 'capture preferences changed before native transaction settled'
            return _original(backend,*args)
        rig.monkeypatch.setattr(rig.backend,method,guarded)
    # Record every preference mutation, independently from final bytes.
    writes = []
    put,remove = w.settings.setValue,w.settings.remove
    rig.monkeypatch.setattr(w.settings,'setValue',lambda *args: (writes.append(('set',*args)),put(*args))[1])
    rig.monkeypatch.setattr(w.settings,'remove',lambda *args: (writes.append(('remove',*args)),remove(*args))[1])
    messages = []
    w.statusBar().messageChanged.connect(messages.append)
    if action.startswith('o_'):
        draft(rig,page,case.variant.split('_release')[0])
    if is_reset:
        click(rig,page.hotkey_reset)
    elif is_all:
        click(rig,page.reset_all)
    elif is_off or is_on:
        click(rig,page.hotkey_off)
    elif action == 'c_copy':
        target = w.a_copy.shortcut()
        chord(rig,page,target)
    elif action == 'd_invalid':
        target = QKeySequence('A' if case.variant == 'bare' else 'Alt+Num+1' if case.variant == 'keypad'
                              else 'Num+1' if case.variant == 'keypad_bare' else 'Alt+Volume Up')
        chord(rig,page,target)
    elif action in ('f_clear','g_shift','n_empty_leave','n_mid_leave','h_abandon'):
        kind = ('clear' if action == 'f_clear' else 'released' if action == 'g_shift'
                else case.variant.split('_')[0] if action.startswith('n_') else 'held')
        draft(rig,page,kind)
        if action == 'h_abandon' and case.variant == 'escape':
            QTest.keyClick(page.hotkey_edit,Qt.Key_Escape)
        if action.startswith('n_'):
            leave = case.variant.split('_')[1]
            if leave == 'close':
                click(rig,page.findChild(QDialogButtonBox).button(QDialogButtonBox.Close))
            elif leave == 'window':
                page.close()
            else:
                bar = page.tabs.tabBar()
                QTest.mouseClick(bar,Qt.LeftButton,pos=bar.tabRect(1).center())
        elif case.variant == 'click':
            click(rig,page.edits['copy'])
            assert QApplication.focusWidget() is page.edits['copy']
            assert field_parts(page.hotkey_edit)[0].text()==rig.words(w.hotkey_sequence())
        else:
            blur(rig,page)
    elif action in ('i_focus','open'):
        focus(rig,page)
        blur(rig,page)
    elif action == 'native_focus':
        focus(rig,page)
        w.hotkey._backend.press()
    else:
        chord(rig,page,target,release=False)
    delta = rig.backend.calls[len(calls):]
    audit_active[0]=False
    capture_writes = [x for x in writes if x[1].startswith('hotkey/')]
    stop = release_fail and bool(retained) and not primary_failure
    if kid in (6,7,10,11):
        assert delta == []
        assert not w._s33_captures
        assert captures(w) == prefs
        assert bytes_(w) == data
        assert dict(rig.backend.held) == held
        assert not capture_writes
        if kid == 6:
            if action in ('f_clear','g_shift','n_empty_leave'):
                reason = hotkey.ONE_KEY
            elif is_reset:
                reason = f'{rig.d} is already used by Copy image.'
            elif action=='c_copy' or (action=='e_legacy' or is_on) and q==QKeySequence('Ctrl+C'):
                reason = f'{rig.words(QKeySequence("Ctrl+C"))} is already used by Copy image.'
            elif action=='d_invalid' and case.variant in ('keypad','keypad_bare'):
                reason = hotkey.MAC_KEYPAD if case.platform=='darwin' else hotkey.WIN_KEYPAD
            elif action=='d_invalid' and case.variant=='unmappable':
                reason = hotkey.UNKNOWN_KEY
            else:
                reason = hotkey.NEED_MODIFIER
            expected = reason
            if retained or (incoming['off'] and held):
                failed = retained[0][1] if retained else h
                expected += '\n' + hotkey.RELEASE.format(key=rig.words(failed))
            elif not incoming['off'] and not held:
                expected += '\n' + rig.words(q) + ' is unavailable.'
            assert page.message.text() == expected
            assert w.statusBar().currentMessage() == s30.error(reason)
        else:
            assert page.message.text() == incoming['outcome']
            assert w.statusBar().currentMessage() == status
    else:
        expected_calls = [('release',s.toString(QKeySequence.PortableText),i) for i,s in retained]
        if stop:
            expected_calls = expected_calls[:1]
        elif kid == 9 or kid == 5:
            if old_id is not None:
                expected_calls += [('release',h.toString(QKeySequence.PortableText),old_id)]
        elif kid in (1,2,3,4):
            expected_calls += [('register',target.toString(QKeySequence.PortableText))]
            if kid == 1 and old_id is not None:
                expected_calls += [('release',h.toString(QKeySequence.PortableText),old_id)]
        assert delta == expected_calls
        failed = stop or (release_fail and old_id is not None and kid in (5,9))
        refused = kid in (2,4)
        unchanged = (stop and kid != 9) or kid == 2 or (kid == 5 and failed)
        if unchanged:
            assert captures(w) == prefs
            assert not capture_writes
        elif kid == 9:
            assert captures(w) == dict(prefs,**{'hotkey/off':True})
        else:
            expected_prefs = dict(prefs)
            if is_reset or is_all:
                expected_prefs.pop('hotkey/sequence',None)
            elif q != target:
                expected_prefs['hotkey/sequence'] = target.toString(QKeySequence.PortableText)
            if incoming['off'] and kid != 5:
                expected_prefs['hotkey/off'] = False
            assert captures(w) == expected_prefs
        if kid == 2 and incoming['off']:
            expected_message = incoming['outcome']
        elif stop or (release_fail and old_id is not None and kid in (1,5,9)):
            expected_message = hotkey.RELEASE.format(key=rig.words(retained[0][1] if stop else h))
        elif refused:
            expected_message = ('The capture key could not be set: stub backend unavailable'
                if case.variant == 'backend_error' else hotkey.STILL_USING.format(new=rig.words(target),old=rig.words(h))
                if kid == 2 else hotkey.TAKEN.format(key=rig.words(target)))
        else:
            expected_message = ''
        assert page.message.text() == expected_message
        assert w.statusBar().currentMessage() == (s30.error(expected_message) if expected_message else status if status and status != getattr(w,'_last_key_status',None) and not status.startswith('Capture from anywhere:') else ''), (messages,status,getattr(w,'_last_key_status',None))
        if (action.startswith('o_')):
            assert not any(hotkey.ONE_KEY in m for m in messages)
        if is_all:
            assert not any(k.startswith('shortcuts/') for k in w.settings.allKeys())
            assert w.a_copy.shortcut() != QKeySequence(D)
        if not failed and not refused and kid not in (5,9):
            assert w.hotkey.registered and w.hotkey.sequence == target
        if not failed and kid in (5,9):
            assert not rig.backend.held
    # Passive blur and a real tab round trip cannot repeat this transaction.
    assert page.hotkey_edit.keySequence()==w.hotkey_sequence()
    assert page.hotkey_off.isChecked()==w.hotkey_off()
    assert field_parts(page.hotkey_edit)[0].text()==rig.words(w.hotkey_sequence())
    primary=(rig.backend.held.get(w.hotkey._backend.identity,'')
             if w.hotkey.registered else '')
    live=rig.words(QKeySequence(primary)) if primary and not w.hotkey_off() else ''
    state=w.key_state()
    if case.variant=='verified':
        assert w._key_green and state['face']=='green'
    assert state['live']==live
    assert w.capture_key_text()==live
    button=w.welcome.capture_bar.key_button
    assert button.text()==(live or ('Key off' if w.hotkey_off() and not primary else 'Choose another key'))
    assert button.accessibleName()=='Capture key: '+button.text()
    assert button.accessibleDescription()==w.welcome.key_row.text()==state['line']
    help_key=s30.help_module.keys_text(w.shortcut_rows()[-1][1])
    assert help_key==(live or 'no key')
    assert f"{live or 'no key'}\nCapture from anywhere" in w._help_window.browser.toPlainText()
    if rig.platform=='win32':
        assert [a.text() for a in w.tray.menu.actions()]==[
            f'Capture ({live})' if live else 'Capture','Open Annotshot','Quit Annotshot']
        assert w.tray.icon.messages==[]
    else:
        assert w.tray is None
    if not is_all:
        assert {k:w.settings.value(k) for k in w.settings.allKeys() if k.startswith('shortcuts/')}==local_prefs
    settled = (captures(w),list(rig.backend.calls),page.message.text(),w.statusBar().currentMessage())
    blur(rig,page)
    if page.isVisible():
        bar = page.tabs.tabBar()
        QTest.mouseClick(bar,Qt.LeftButton,pos=bar.tabRect(1).center())
        QTest.mouseClick(bar,Qt.LeftButton,pos=bar.tabRect(0).center())
    QTest.keyRelease(page.hotkey_edit,Qt.Key_Shift)
    rig.qapp.processEvents()
    assert (captures(w),list(rig.backend.calls),page.message.text(),w.statusBar().currentMessage()) == settled
    return settled[2:]


def run_grid(rig,case):
    w = setup(rig,case)
    expected = visit(rig,w,lambda page: oracle(rig,w,page,case))
    visit(rig,w,lambda page: (
        pytest_check(page.message.text() == expected[0]),
        pytest_check(w.statusBar().currentMessage() == expected[1])))
    if case.kid==4:
        before=captures(w),bytes_(w),len(rig.backend.calls)
        menu_try(w)
        assert w._key_try is None and not w.isMinimized() and w.key_clock.queue==[]
        assert captures(w)==before[0] and bytes_(w)==before[1]
        assert len(rig.backend.calls)==before[2]+1
        assert w.key_state()['outcome']==expected[0]
        assert w.statusBar().currentMessage()==s30.error(expected[0])


def pytest_check(value):
    assert value

# Separate families make every K independently reportable. Parameter names
# carry the platform, arrival state, gesture and native-result variant.

@pytest.mark.parametrize('case',[c for c in CASES if c.kid==1],ids=lambda c:c.name)
def test_K01(rig,case): run_grid(rig,case)
@pytest.mark.parametrize('case',[c for c in CASES if c.kid==2],ids=lambda c:c.name)
def test_K02(rig,case):
    if case.action=='adapter_refusal':
        return adapter_refusal(rig,case)
    run_grid(rig,case)
@pytest.mark.parametrize('case',[c for c in CASES if c.kid==3],ids=lambda c:c.name)
def test_K03(rig,case): run_grid(rig,case)
@pytest.mark.parametrize('case',[c for c in CASES if c.kid==4],ids=lambda c:c.name)
def test_K04(rig,case):
    if case.action=='adapter_refusal':
        return adapter_refusal(rig,case)
    run_grid(rig,case)
@pytest.mark.parametrize('case',[c for c in CASES if c.kid==5],ids=lambda c:c.name)
def test_K05(rig,case): run_grid(rig,case)
@pytest.mark.parametrize('case',[c for c in CASES if c.kid==6],ids=lambda c:c.name)
def test_K06(rig,case): run_grid(rig,case)
@pytest.mark.parametrize('case',[c for c in CASES if c.kid==7],ids=lambda c:c.name)
def test_K07(rig,case): run_grid(rig,case)
@pytest.mark.parametrize('case',[c for c in CASES if c.kid==8],ids=lambda c:c.name)
def test_K08(rig,case): run_grid(rig,case)
@pytest.mark.parametrize('case',[c for c in CASES if c.kid==9],ids=lambda c:c.name)
def test_K09(rig,case): run_grid(rig,case)
@pytest.mark.parametrize('case',[c for c in CASES if c.kid==10],ids=lambda c:c.name)
def test_K10(rig,case):
    if case.action=='adapter_focus':
        return native_focus(rig,case)
    run_grid(rig,case)


def raw_setup(rig,case):
    native = s30.native_adapter(rig,wrap=case.variant.startswith('wrap'))
    w = rig.create()
    native.window = w
    w.apply_hotkey()  # app startup boundary
    w._s30_page.deleteLater()
    rig.qapp.processEvents()
    w.show()
    captures_ = []
    rig.monkeypatch.setattr(w,'_may_record_screen',lambda: captures_.append(1) or False)
    return w,native,captures_


def menu_try(w):
    w.welcome.capture_bar.key_menu.actions()[0].trigger()


@pytest.mark.parametrize('case',[c for c in CASES if c.kid==11],ids=lambda c:c.name)
def test_K11(rig,case):
    if case.action == 'open':
        return run_grid(rig,case)
    w,native,captured = raw_setup(rig,case)
    existing=None
    if case.variant=='first_input':
        existing=settings_dialog.SettingsDialog(w)
        existing.show()
        rig.qapp.processEvents()
    menu_try(w)
    if case.variant == 'minimizing':
        rig.monkeypatch.setattr(w,'showMinimized',lambda:None)
        w.key_clock.advance(1000)
    elif case.variant == 'armed':
        w.key_clock.advance(1000)
    raw = native.raw()
    callbacks = [callback for _,callback in w.key_clock.queue]
    before = captures(w),bytes_(w),list(native.calls)
    if case.variant == 'inactive_observer':
        # Construction and passive snapshots are not input.
        p = settings_dialog.SettingsDialog(w)
        w.key_clock.advance(1000)
        w._publish_key()
        assert w._key_try['phase']=='armed'
        p.show()
        p.activateWindow()
        rig.qapp.processEvents()
        assert w._key_try is None
        p.close()
        p.deleteLater()
    elif existing is not None:
        focus(rig,existing)
        QTest.keyPress(existing.hotkey_edit,Qt.Key_Shift)
        assert w._key_try is None
        QTest.keyClick(existing.hotkey_edit,Qt.Key_Escape)
        QTest.keyRelease(existing.hotkey_edit,Qt.Key_Shift)
        existing.close()
        existing.deleteLater()
    else:
        visit(rig,w,lambda p: pytest_check(w.statusBar().currentMessage()=='Try cancelled'))
    native.dispatch(raw)
    for callback in callbacks:
        callback()
    w.key_clock.advance(20000)
    assert captured==[] and w._key_try is None
    assert (captures(w),bytes_(w),list(native.calls))==before
    assert w.statusBar().currentMessage()=='Try cancelled'


@pytest.mark.parametrize('case',[c for c in CASES if c.kid==12],ids=lambda c:c.name)
def test_K12(rig,case):
    w,native,captured=raw_setup(rig,case)
    if case.variant.startswith('wrap'):
        w.key_clock.advance(280)  # minimize is tick zero; the old raw down is 0xffffffff
    before=captures(w),bytes_(w),list(native.calls)
    if case.variant=='before_choice':
        raw=native.raw()
    menu_try(w)
    if case.variant in ('before_arm','wrap_before'):
        w.key_clock.advance(999)
        raw=native.raw()
        w.key_clock.advance(1)
    else:
        w.key_clock.advance(1000)
        if case.variant!='before_choice':
            raw=native.raw()
    attempt=w._key_try
    deadline=list(w.key_clock.queue)
    native.dispatch(raw)
    assert w._key_try is attempt and w.key_clock.queue==deadline
    assert captured==[] and not w._key_green and w.isMinimized()
    assert w.key_state()['outcome']=='' and w.statusBar().currentMessage()==w.capture_status()
    if rig.platform=='darwin':
        native.dispatch(native.raw(False))
    w.key_clock.advance(1)
    native.dispatch(native.raw())
    assert w._key_try is None and w._key_green and captured==[]
    assert (captures(w),bytes_(w),list(native.calls))==before


@pytest.mark.parametrize('case',[c for c in CASES if c.kid==13],ids=lambda c:c.name)
def test_K13(rig,case):
    w,native,captured=raw_setup(rig,case)
    menu_try(w)
    w.key_clock.advance(1000)
    w.key_clock.advance(9999 if case.variant=='later' else 1)
    raw=native.raw()
    if case.variant=='no_timestamp':
        w.hotkey.deliver()
    else:
        native.dispatch(raw)
    assert captured==[] and w._key_green and w._key_try is None
    assert not w.isMinimized()
    assert w.statusBar().currentMessage()=='Annotshot received your key'
    rig.qapp.processEvents()
    assert w.welcome.capture_bar.key_button.hasFocus()
    native.dispatch(raw)
    assert captured==[]
    if rig.platform=='darwin':
        native.dispatch(native.raw(False))
    w.key_clock.advance(1)
    native.dispatch(native.raw())
    assert captured==[1]


@pytest.mark.parametrize('case',[c for c in CASES if c.kid==14],ids=lambda c:c.name)
def test_K14(rig,case):
    w=setup(rig,case)
    if case.variant=='swap':
        rig.backend.refused.add(Y)
    visit(rig,w,lambda p: chord(rig,p,Y if case.variant=='swap' else 'Ctrl+C'))
    assert w.key_state()['outcome']
    menu_try(w)
    assert w._key_feedback=='' and w._hotkey_problem is None and w._key_edit_error==''
    w.key_clock.advance(1000)
    w.hotkey._backend.press()
    assert w._key_green
    if case.variant=='swap':
        QTest.qWait(5200)
    visit(rig,w,lambda p: (
        pytest_check(p.message.text()==''),pytest_check(not p.hotkey_off.isChecked()),
        pytest_check(p.hotkey_edit.keySequence()==QKeySequence(D))))
    assert w.statusBar().currentMessage()=='Annotshot received your key'
    if case.variant=='swap':
        QTest.qWait(5800)
        assert not w.statusBar().currentMessage()
        assert w._key_green and w.key_state()['outcome']==''
    w.welcome.capture_bar.key_menu.actions()[1].trigger()
    w.welcome.recorder.cancel.click()
    assert not w.statusBar().currentMessage() and w.key_state()['outcome']==''


@pytest.mark.parametrize('case',[Case(7,p,'D','status_deadline') for p in ('darwin','win32')],ids=lambda c:c.name)
def test_K07_original_status_deadline(rig,case):
    w=setup(rig,case)
    rig.backend.refused.add(Y)
    visit(rig,w,lambda p: chord(rig,p,Y))
    reason=w.key_state()['outcome']
    assert 'Still using' in reason
    QTest.qWait(5200)
    def passive(page):
        focus(rig,page)
        blur(rig,page)
        bar=page.tabs.tabBar()
        QTest.mouseClick(bar,Qt.LeftButton,pos=bar.tabRect(1).center())
        QTest.mouseClick(bar,Qt.LeftButton,pos=bar.tabRect(0).center())
        assert page.message.text()==reason
    visit(rig,w,passive)
    QTest.qWait(5800)
    assert not w.statusBar().currentMessage()
    visit(rig,w,lambda p: pytest_check(p.message.text()==reason))

PROBES = ('untouched_signals','clear_signals','shift_released','shift_held',
          'escape_stock','base_before_finish','raw_keypad','portable_words')

@pytest.mark.parametrize('case',[Case(7,p,'D','probe',v) for p in ('darwin','win32')
                                 for v in PROBES],ids=lambda c:c.name)
def test_probed_assumptions(rig,case):
    """Product equivalents of the stock probes: s37 F11/F13/F14/F16/F35."""
    w=setup(rig,case)
    def probe(page):
        edit=page.edits['copy']
        line,clear=field_parts(edit)
        edit.setFocus()
        rig.qapp.processEvents()
        submissions=[]
        edit.chordEntered.connect(lambda seq: submissions.append(QKeySequence(seq)))
        initial=edit.keySequence()
        v=case.variant
        if v=='untouched_signals':
            page.hotkey_off.setFocus()
            rig.qapp.processEvents()
            assert not submissions and edit.keySequence()==initial
        elif v=='clear_signals':
            click(rig,clear)
            assert edit.keySequence().isEmpty() and line.text()==''
            assert w.a_copy.shortcut().isEmpty() and not submissions
            page.hotkey_off.setFocus()
            rig.qapp.processEvents()
            assert w.a_copy.shortcut().isEmpty()
        elif v in ('shift_released','shift_held'):
            QTest.keyPress(edit,Qt.Key_Shift)
            assert edit.keySequence()==initial and line.text()=='Shift'
            if v=='shift_released':
                QTest.keyRelease(edit,Qt.Key_Shift)
                assert line.text()==rig.words(initial)
            page.hotkey_off.setFocus()
            rig.qapp.processEvents()
            QTest.keyRelease(edit,Qt.Key_Shift)
            assert not submissions and edit.keySequence()==initial
            assert line.text()==rig.words(initial)
        elif v=='escape_stock':
            QTest.keyPress(edit,Qt.Key_Escape)
            assert not page.isVisible() and edit.keySequence()==initial
            assert not submissions
        elif v=='base_before_finish':
            for n in range(2):
                QTest.keyPress(edit,Qt.Key_Alt)
                QTest.keyPress(edit,Qt.Key_Y,Qt.AltModifier)
                assert edit.keySequence()==QKeySequence(Y) and w.a_copy.shortcut()==QKeySequence(Y)
                assert len(submissions)==n+1
                QTest.keyRelease(edit,Qt.Key_Y,Qt.AltModifier)
                QTest.keyRelease(edit,Qt.Key_Alt)
                assert len(submissions)==n+1
            page.hotkey_off.setFocus()
            rig.qapp.processEvents()
            assert len(submissions)==2
        elif v=='raw_keypad':
            QTest.keyPress(edit,Qt.Key_Alt)
            QTest.keyPress(edit,Qt.Key_1,Qt.AltModifier|Qt.KeypadModifier)
            assert submissions==[QKeySequence('Alt+Num+1')]
            assert edit.keySequence()==w.a_copy.shortcut()==QKeySequence('Alt+1')
            QTest.keyRelease(edit,Qt.Key_1,Qt.AltModifier|Qt.KeypadModifier)
            QTest.keyRelease(edit,Qt.Key_Alt)
        else:
            assert QKeySequence(hotkey.DEFAULT).toString(QKeySequence.PortableText)==D
            assert s30.key_words(QKeySequence(D),'darwin')=='Option+Shift+Space'
            assert s30.key_words(QKeySequence(D),'win32')=='Alt+Shift+Space'
            chord(rig,page,D)
            assert field_parts(page.hotkey_edit)[0].text()==rig.d
    visit(rig,w,probe)


@pytest.mark.parametrize('variant', ['untouched_signals','clear_signals','shift_released','shift_held','escape_stock','base_before_finish','raw_keypad'])
def test_stock_control_premises(qapp, variant):
    """Original stock probes, isolated from the product recorder."""
    from PySide6.QtWidgets import QKeySequenceEdit, QWidget, QVBoxLayout, QPushButton
    parent=QWidget(); layout=QVBoxLayout(parent)
    edit=QKeySequenceEdit(QKeySequence('Ctrl+C')); edit.setMaximumSequenceLength(1); edit.setClearButtonEnabled(True)
    other=QPushButton('Reset'); layout.addWidget(edit); layout.addWidget(other)
    page=SimpleNamespace(hotkey_off=other)
    rig=SimpleNamespace(qapp=qapp)
    line=edit.findChild(QLineEdit)
    parent.show(); edit.setFocus(); qapp.processEvents()
    changes,finishes,texts=[],[],[]
    edit.keySequenceChanged.connect(lambda s: changes.append(QKeySequence(s)))
    edit.editingFinished.connect(lambda: finishes.append(QKeySequence(edit.keySequence())))
    line.textEdited.connect(texts.append)
    initial=edit.keySequence(); v=variant
    try:
        if v=='untouched_signals':
            page.hotkey_off.setFocus()
            rig.qapp.processEvents()
            assert changes and finishes and changes[-1]==initial and finishes[-1]==initial
        elif v=='clear_signals':
            click(rig,line.findChild(QToolButton))
            assert changes[-1].isEmpty() and texts[-1]=='' and not finishes
            page.hotkey_off.setFocus()
            rig.qapp.processEvents()
            assert finishes[-1].isEmpty()
        elif v in ('shift_released','shift_held'):
            QTest.keyPress(edit,Qt.Key_Shift)
            if v=='shift_released':
                QTest.keyRelease(edit,Qt.Key_Shift)
            assert edit.keySequence().isEmpty()
            page.hotkey_off.setFocus()
            rig.qapp.processEvents()
            assert changes[-1].isEmpty() and finishes[-1].isEmpty()
            QTest.keyRelease(edit,Qt.Key_Shift)
        elif v=='escape_stock':
            QTest.keyPress(edit,Qt.Key_Escape)
            assert edit.keySequence()==QKeySequence('Esc')
            QTest.keyRelease(edit,Qt.Key_Escape)
            page.hotkey_off.setFocus()
            rig.qapp.processEvents()
            assert finishes and QKeySequence('Esc') in changes
        elif v=='base_before_finish':
            for _ in range(2):
                QTest.keyPress(edit,Qt.Key_Alt)
                QTest.keyPress(edit,Qt.Key_Y,Qt.AltModifier)
                assert edit.keySequence()==QKeySequence(Y)
                n=len(finishes)
                QTest.keyRelease(edit,Qt.Key_Y,Qt.AltModifier)
                QTest.keyRelease(edit,Qt.Key_Alt)
                assert len(finishes)>n
            page.hotkey_off.setFocus()
            rig.qapp.processEvents()
            assert len(finishes)>=3
        elif v=='raw_keypad':
            QTest.keyPress(edit,Qt.Key_Alt)
            QTest.keyPress(edit,Qt.Key_1,Qt.AltModifier|Qt.KeypadModifier)
            assert edit.keySequence()==QKeySequence('Alt+1')
            QTest.keyRelease(edit,Qt.Key_1,Qt.AltModifier|Qt.KeypadModifier)
            QTest.keyRelease(edit,Qt.Key_Alt)
    finally:
        parent.close(); parent.deleteLater(); qapp.processEvents()


def dispatch_to(rig,backend,event):
    import ctypes
    if rig.platform=='win32':
        assert backend._filter.nativeEventFilter(b'windows_dispatcher_MSG',ctypes.addressof(event))==(True,0)
    else:
        assert backend._handler(None,ctypes.addressof(event),None)==0


def native_focus(rig,case):
    from PySide6.QtWidgets import QApplication
    w,native,captured=raw_setup(rig,case)
    old=w.hotkey._backend
    raw_old=native.raw()
    unregister=old.unregister
    if case.variant=='retained':
        rig.monkeypatch.setattr(old,'unregister',lambda: (_ for _ in ()).throw(RuntimeError('stub release')))
    def edit(page):
        chord(rig,page,'F8')
        assert w.hotkey.sequence==QKeySequence('F8') and page.capture_key_has_focus()
        w.key_clock.advance(1)
        raw=native.raw()
        native.dispatch(raw)
        assert not captured and not w._key_green
        if rig.platform=='darwin':
            native.dispatch(native.raw(False))
        dispatch_to(rig,old,raw_old)
        assert not captured and not w._key_green
        if rig.platform=='darwin' and case.variant=='retained':
            raw_old.kind=hotkey.K_EVENT_HOTKEY_RELEASED
            dispatch_to(rig,old,raw_old)
        if case.variant=='inactive':
            rig.monkeypatch.setattr(QApplication,'applicationState',lambda:Qt.ApplicationInactive)
        elif case.variant=='close':
            page.close()
        else:
            blur(rig,page)
        if case.variant!='retired':
            w.key_clock.advance(1)
            native.dispatch(native.raw())
            assert captured==[1]
    visit(rig,w,edit)
    rig.monkeypatch.setattr(old,'unregister',unregister)
    if case.variant=='retired':
        menu_try(w)
        w.key_clock.advance(1000)
        dispatch_to(rig,old,raw_old)
        assert w._key_try and not captured and not w._key_green
        w.key_clock.advance(1)
        native.dispatch(native.raw())
        assert w._key_green and not captured


def adapter_refusal(rig,case):
    """Taken versus backend failure through real adapters and their cleanup."""
    from PySide6.QtCore import QCoreApplication
    native=s30.native_adapter(rig)
    w=rig.create(off=case.state=='O')
    native.window=w
    w.apply_hotkey()  # startup boundary, before the Settings action
    w._s30_page.deleteLater()
    rig.qapp.processEvents()
    w.show()
    old=w.hotkey._backend
    original_prefs=captures(w)
    install,remove=[],[]
    app=QCoreApplication.instance()
    add_filter,remove_filter=app.installNativeEventFilter,app.removeNativeEventFilter
    rig.monkeypatch.setattr(app,'installNativeEventFilter',lambda f:(install.append(f),add_filter(f))[1])
    rig.monkeypatch.setattr(app,'removeNativeEventFilter',lambda f:(remove.append(f),remove_filter(f))[1])
    attempts=[]
    if rig.platform=='win32':
        if case.variant=='backend_error':
            rig.monkeypatch.setattr(hotkey.WinBackend,'__init__',
                lambda *args: (_ for _ in ()).throw(RuntimeError('stub backend unavailable')))
            reason='The capture key could not be set: stub backend unavailable'
        else:
            register=hotkey.WinBackend.register
            def refuse(backend,seq):
                attempts.append(backend)
                rig.monkeypatch.setattr(backend._user32.RegisterHotKey,'callback',lambda *args:0)
                return register(backend,seq)
            rig.monkeypatch.setattr(hotkey.WinBackend,'register',refuse)
    else:
        register=hotkey.MacBackend.register
        def refuse(backend,seq):
            attempts.append(backend)
            carbon=backend._carbon
            if case.variant=='backend_error':
                rig.monkeypatch.setattr(carbon.InstallEventHandler,'callback',lambda *args:-50)
            else:
                rig.monkeypatch.setattr(carbon.RegisterEventHotKey,'callback',lambda *args:-9878)
                original_remove=carbon.RemoveEventHandler.callback
                rig.monkeypatch.setattr(carbon.RemoveEventHandler,'callback',
                    lambda ref:(remove.append(ref),original_remove(ref))[1])
            return register(backend,seq)
        rig.monkeypatch.setattr(hotkey.MacBackend,'register',refuse)
        reason='The capture key could not be set: could not install its handler (-50)'
    if case.variant=='taken':
        reason=(hotkey.STILL_USING.format(new=rig.y,old=rig.d) if old else hotkey.TAKEN.format(key=rig.y))
    def edit(page):
        chord(rig,page,Y)
        assert page.message.text()==reason and w.statusBar().currentMessage()==s30.error(reason)
        assert w.hotkey.registered==(old is not None)
        if old:
            assert w.hotkey._backend is old and captures(w)==original_prefs
            assert not any(call[0]=='release' for call in native.calls)
            expected_line=reason if case.variant=='taken' else f'Capture from anywhere with {rig.d}'
            assert w.welcome.key_row.text()==expected_line
        else:
            assert captures(w)=={'hotkey/off':False,'hotkey/sequence':Y}
            assert w.key_state()['face']=='amber'
        if rig.platform=='win32':
            assert install==remove
            if attempts:
                assert not attempts[0]._installed and not attempts[0]._on
        elif attempts:
            assert not attempts[0]._key_ref and not attempts[0]._handler_ref
            assert len(remove)==(1 if case.variant=='taken' else 0)
        settled=(list(native.calls),captures(w),page.message.text())
        blur(rig,page)
        assert (list(native.calls),captures(w),page.message.text())==settled
    visit(rig,w,edit)
    if old is None:
        menu_try(w)
        assert w._key_try is None and not w.isMinimized() and w.key_state()['outcome']==reason
