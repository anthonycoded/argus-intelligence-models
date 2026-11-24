"""Opt-in Chromium approval workflow; every write targets disposable fixtures."""
import os
from pathlib import Path
import socket
import threading
import time

import pytest

from tests.test_review_dashboard import dashboard
from tests.test_argilla_bridge import bridge


@pytest.mark.skipif(os.environ.get('AIC_DASHBOARD_BROWSER')!='1',reason='Opt-in local Chromium GUI workflow')
def test_metadata_to_human_approval_in_browser(dashboard,monkeypatch,tmp_path):
    from playwright.sync_api import sync_playwright,expect
    import uvicorn
    from src.review_dashboard import create_app
    from src import argilla_bridge as b
    c=dashboard
    # Second unlabeled fixture proves next-item navigation without production data.
    first=c['row'];second={**first,'candidate_id':'candidate-'+'b'*64,
        'source_id':'https://example.org/second','article_title':'Zeta independent next item'}
    monkeypatch.setattr(b,'load_sample',lambda path:({},[first,second]))
    root=tmp_path/'two-candidate-bridge'
    b.initialize(root,c['sample'],c['root'])
    c['service'].bridge_root=root
    def auth(u,p):
        if u!='reviewer' or p!='fixture-password':raise ValueError()
        return {'id':'12345678-1234-4234-8234-123456789abc','username':'synthetic-reviewer'}
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    app=create_app(c['service'],auth,origin=f'http://127.0.0.1:{port}')
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',access_log=False,proxy_headers=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    assert server.started
    evidence_dir=Path(os.environ.get('AIC_BROWSER_EVIDENCE',str(tmp_path/'browser-evidence')))
    evidence_dir.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1100})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{port}')
            page.get_by_label('Username',exact=True).fill('reviewer')
            page.get_by_label('Password',exact=True).fill('fixture-password')
            page.get_by_role('button',name='Sign in',exact=True).click()
            page.get_by_role('button',name='Synthetic multinational developments',exact=False).click()
            page.get_by_label('Source representation',exact=True).fill('😀 Trade policy cut tariffs.\nA reviewer-authored synthetic summary.')
            page.get_by_label('Actual content type',exact=True).select_option('human_summary')
            page.get_by_label('Handling basis',exact=True).fill('Synthetic disposable browser fixture; rights unverified')
            page.get_by_role('button',name='Attach content',exact=True).click()
            expect(page.get_by_test_id('registered-text')).to_contain_text('Trade policy cut tariffs.')
            page.get_by_label('Article domain economics',exact=True).check()
            page.get_by_label('Article rationale',exact=True).fill('The retained text reports an economic policy development.')
            page.get_by_label('Event coverage',exact=True).select_option('not_enumerated')
            page.get_by_label('Scope explanation',exact=True).fill('Article-level annotation. No individual event instances enumerated.')
            page.get_by_role('button',name='Save Draft',exact=True).click()
            expect(page.get_by_role('status')).to_contain_text('Working draft saved')
            page.get_by_role('button',name='Validate',exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('evidence')
            page.get_by_test_id('registered-text').evaluate("""e=>{const t=e.firstChild;const start=t.textContent.indexOf('Trade');const end=t.textContent.indexOf('.')+1;const r=document.createRange();r.setStart(t,start);r.setEnd(t,end);const s=window.getSelection();s.removeAllRanges();s.addRange(r);e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));}""")
            expect(page.get_by_test_id('selection-preview')).to_have_text('Trade policy cut tariffs.')
            page.get_by_label('Article domain: economics',exact=True).check()
            page.get_by_label('Source attribution',exact=True).fill('Synthetic retained reviewer summary')
            page.get_by_role('button',name='Add supporting selection',exact=True).click()
            expect(page.get_by_role('button',name='Remove evidence 1',exact=True)).to_be_visible()
            page.get_by_label('Article rationale',exact=True).fill('Reviewed trade policy is an economic development; this rationale was edited after selecting evidence.')
            expect(page.get_by_role('button',name='Remove evidence 1',exact=True)).to_be_visible()
            page.get_by_role('button',name='Validate',exact=True).click()
            expect(page.get_by_role('status')).to_contain_text('validated')
            page.screenshot(path=str(evidence_dir/'01-validated-form.png'),full_page=True)
            page.get_by_role('button',name='Submit',exact=True).click()
            page.get_by_role('button',name='Inspect Staged Draft',exact=True).click()
            expect(page.get_by_role('heading',name='Immutable staged annotation',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='Approve',exact=True)).to_be_disabled()
            page.screenshot(path=str(evidence_dir/'02-staged-inspection.png'),full_page=True)
            page.get_by_label('Confirm exact staged review',exact=True).check()
            page.get_by_role('button',name='Approve',exact=True).click()
            expect(page.get_by_role('heading',name='Approved annotation — read only',exact=True)).to_be_visible()
            expect(page.get_by_test_id('counts')).to_contain_text('1 approved · 0 eligible')
            page.screenshot(path=str(evidence_dir/'03-approved-rights-blocked.png'),full_page=True)
            page.get_by_role('button',name='Audit / history',exact=True).click()
            expect(page.get_by_role('heading',name='Immutable history',exact=True)).to_be_visible()
            page.get_by_role('button',name='Next article',exact=True).click()
            expect(page.get_by_role('heading',name='Zeta independent next item',exact=True)).to_be_visible()
            expect(page.get_by_label('Article domain economics',exact=True)).not_to_be_checked()
            assert not errors,errors
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);sock.close()
