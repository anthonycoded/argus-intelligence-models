"""Disposable Article 004 workflow. Never approves or contacts production services."""
import os
from pathlib import Path
import socket
import threading
import time
import pytest
from tests.test_review_dashboard import dashboard
from tests.test_argilla_bridge import bridge

pytestmark=pytest.mark.skipif(os.environ.get('AIC_DASHBOARD_BROWSER')!='1',reason='Opt-in local Chromium persistence workflow')
TEXT='A fictional fleet evaluated naval sensors. Economic investment, diplomatic talks and cyber incident response were discussed. This text is a synthetic software fixture.'


@pytest.fixture
def browser_case(dashboard,monkeypatch,tmp_path):
    from playwright.sync_api import sync_playwright
    import uvicorn
    from src.review_dashboard import create_app
    from src import argilla_bridge as b
    c=dashboard;row={**c['row'],'article_title':'Article 004 — disposable multi-domain fixture'}
    other={**row,'candidate_id':'candidate-'+'b'*64,'source_id':'https://example.org/other-fixture','article_title':'Article 005 — navigation fixture'}
    monkeypatch.setattr(b,'load_sample',lambda path:({},[row,other]))
    monkeypatch.setattr('src.global_sampling.load_sample',lambda path:({},[row,other]))
    root=tmp_path/'article004-bridge';b.initialize(root,c['sample'],c['root']);c['service'].bridge_root=root
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    app=create_app(c['service'],lambda u,p:{'id':'12345678-1234-4234-8234-123456789abc','username':'fixture-reviewer'},origin=f'http://127.0.0.1:{port}')
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    output=Path(os.environ.get('AIC_Q1_EVIDENCE',str(tmp_path/'screenshots')));output.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1100})
            page.goto(f'http://127.0.0.1:{port}');page.get_by_label('Username',exact=True).fill('fixture-reviewer');page.get_by_label('Password',exact=True).fill('fixture-only');page.get_by_role('button',name='Sign in',exact=True).click()
            page.get_by_role('button',name=row['article_title'],exact=False).click()
            yield page,c,output
            assert not (c['root']/'approvals').exists(),'This workflow must stop at staged inspection'
            browser.close()
    finally:server.should_exit=True;thread.join(timeout=10);sock.close()


def claims(page,domains=('defense','economics','geopolitics')):
    for label in domains:page.get_by_label('Article domain '+label,exact=True).check()
    page.get_by_label('Article category military_technology',exact=True).check()
    page.get_by_label('Article rationale',exact=True).fill('Independent fixture rationale for the deliberately selected domains.')
    page.get_by_label('Event coverage',exact=True).select_option('not_enumerated')
    page.get_by_label('Scope explanation',exact=True).fill('Article-level fixture; no events enumerated.')


def attach_text(page,text=TEXT):
    from playwright.sync_api import expect
    page.get_by_label('Source representation',exact=True).fill(text)
    page.get_by_label('Actual content type',exact=True).select_option('human_summary')
    page.get_by_label('Handling basis',exact=True).fill('Disposable synthetic fixture supplied by test author; rights unverified')
    page.get_by_role('button',name='Attach content',exact=True).click()
    expect(page.get_by_test_id('registered-text')).to_have_text(text)


def map_claims(page,names,quote=None):
    from playwright.sync_api import expect
    page.get_by_test_id('registered-text').evaluate("""(e,quote)=>{const t=e.firstChild;const start=quote===null?0:t.textContent.indexOf(quote);const end=quote===null?t.textContent.length:start+quote.length;const r=document.createRange();r.setStart(t,start);r.setEnd(t,end);const s=window.getSelection();s.removeAllRanges();s.addRange(r);e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));}""",quote)
    for name in names:page.get_by_label(name,exact=True).check()
    page.get_by_label('Source attribution',exact=True).fill('Explicitly selected disposable fixture text')
    page.get_by_role('button',name='Add supporting selection',exact=True).click()
    expect(page.get_by_test_id('selection-preview')).to_have_count(0)


def test_attachment_keeps_unsaved_fields(browser_case):
    from playwright.sync_api import expect
    page,c,out=browser_case;claims(page)
    page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(out/'attachment-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(out/'attachment-narrow.png'),full_page=True);page.set_viewport_size({'width':1440,'height':1100})
    attach_text(page)
    expect(page.get_by_label('Article domain economics',exact=True)).to_be_checked()
    expect(page.get_by_label('Article rationale',exact=True)).to_have_value('Independent fixture rationale for the deliberately selected domains.')
    expect(page.get_by_label('Scope explanation',exact=True)).to_have_value('Article-level fixture; no events enumerated.')


def test_article004_missing_evidence_preserves_other_mappings(browser_case):
    from playwright.sync_api import expect
    page,c,out=browser_case;attach_text(page);claims(page)
    map_claims(page,['Article domain: defense','Article domain: economics','Article domain: geopolitics','Article category: military technology'])
    expect(page.get_by_role('button',name='Remove evidence 4',exact=True)).to_be_visible()
    page.get_by_role('button',name='Save Draft',exact=True).click();expect(page.get_by_role('status')).to_contain_text('Working draft saved')
    page.get_by_label('Article domain cybersecurity',exact=True).check()
    page.get_by_role('button',name='Validate',exact=True).click()
    expect(page.get_by_role('alert').first).to_contain_text('evidence')
    page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(out/'missing-evidence-desktop.png'),full_page=True)
    expect(page.get_by_role('button',name='Remove evidence 4',exact=True)).to_be_visible()
    map_claims(page,['Article domain: cybersecurity'])
    page.get_by_role('button',name='Validate',exact=True).click();expect(page.get_by_role('status')).to_contain_text('validated')
    page.get_by_role('button',name='Submit',exact=True).click();page.get_by_role('button',name='Inspect Staged Draft',exact=True).click()
    expect(page.get_by_role('heading',name='Immutable staged annotation',exact=True)).to_be_visible()
    page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(out/'article004-staged-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(out/'article004-staged-narrow.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')


def test_revision_change_keeps_recoverable_draft_and_invalidates_old_positions(browser_case):
    from playwright.sync_api import expect
    page,c,_=browser_case;attach_text(page);claims(page,['defense'])
    map_claims(page,['Article domain: defense','Article category: military technology'])
    page.get_by_role('button',name='Save Draft',exact=True).click();expect(page.get_by_role('status')).to_contain_text('Working draft saved')
    page.get_by_text('Attach permitted source content / new revision',exact=True).click()
    attach_text(page,'Different text starts here. A revised fictional fleet sensor assessment.')
    expect(page.get_by_label('Article domain defense',exact=True)).to_be_checked()
    expect(page.get_by_role('button',name='Remove evidence 1',exact=True)).to_have_count(0)
    page.get_by_text('Recoverable prior work',exact=False).click()
    expect(page.get_by_text('Pre-attachment draft retained on its original source revision.',exact=True).first).to_be_visible()
    page.get_by_role('button',name='Validate',exact=True).click();expect(page.get_by_role('alert').first).to_contain_text('evidence')
    assert not (c['root']/'approvals').exists()


def test_refresh_navigation_warning_and_saved_draft_return(browser_case):
    from playwright.sync_api import expect
    page,c,_=browser_case;attach_text(page);claims(page,['defense'])
    map_claims(page,['Article domain: defense','Article category: military technology'])
    page.get_by_role('button',name='Refresh queue',exact=True).click()
    expect(page.get_by_role('button',name='Remove evidence 2',exact=True)).to_be_visible()
    dismissed=[]
    def decline(dialog):dismissed.append(dialog.message);dialog.dismiss()
    page.once('dialog',decline);page.get_by_role('button',name='Next article',exact=True).click()
    expect(page.get_by_role('heading',name='Article 004 — disposable multi-domain fixture',exact=True)).to_be_visible()
    assert dismissed
    page.get_by_role('button',name='Save Draft',exact=True).click();expect(page.get_by_role('status')).to_contain_text('Working draft saved')
    page.get_by_role('button',name='Next article',exact=True).click()
    expect(page.get_by_role('heading',name='Article 005 — navigation fixture',exact=True)).to_be_visible()
    page.get_by_role('button',name='Article 004 — disposable multi-domain fixture',exact=False).click()
    expect(page.get_by_role('button',name='Remove evidence 2',exact=True)).to_be_visible()
    expect(page.get_by_label('Article rationale',exact=True)).to_have_value('Independent fixture rationale for the deliberately selected domains.')


def test_lost_save_response_retry_is_idempotent_and_busy_controls_are_safe(browser_case):
    from playwright.sync_api import expect
    page,c,_=browser_case;attach_text(page);claims(page,['defense'])
    pending=[];page.route('**/api/candidates/*/save',lambda route:pending.append(route))
    page.get_by_role('button',name='Save Draft',exact=True).click()
    expect(page.get_by_test_id('save-state')).to_have_text('saving')
    expect(page.get_by_role('button',name='Save Draft',exact=True)).to_be_disabled()
    expect(page.get_by_label('Article rationale',exact=True)).to_be_disabled()
    page.wait_for_timeout(150);assert len(pending)==1
    # The server saved successfully; only its response is lost.
    response=pending[0].fetch();assert response.status==200;pending[0].abort('failed')
    expect(page.get_by_test_id('save-state')).to_have_text('save failed')
    page.unroute('**/api/candidates/*/save')
    count=len(list((c['service'].root/'work').iterdir()))
    page.get_by_role('button',name='Save Draft',exact=True).click();expect(page.get_by_role('status')).to_contain_text('Working draft saved')
    assert len(list((c['service'].root/'work').iterdir()))==count
    page.get_by_label('Article rationale',exact=True).fill('Newer fixture edit survives retry completion.')
    expect(page.get_by_test_id('save-state')).to_have_text('unsaved')


def test_ai_paste_edit_and_explicit_origin_are_retained_without_approval(browser_case):
    from playwright.sync_api import expect
    page,c,_=browser_case
    page.get_by_label('Source representation',exact=True).fill('domain: defense. Synthetic AI prose supplied for testing.')
    page.get_by_label('Actual content type',exact=True).select_option('ai_assisted_summary')
    expect(page.get_by_text('Possible target-label leakage:',exact=False)).to_be_visible()
    page.get_by_label('Source representation',exact=True).fill('A synthetic AI-assisted report of a fictional fleet sensor evaluation, edited by the fixture author.')
    page.get_by_label('Model provider (unknown: blank)',exact=True).fill('synthetic-provider')
    page.get_by_label('Model name (unknown: blank)',exact=True).fill('synthetic-model')
    page.get_by_label('Human editing status',exact=True).select_option('edited')
    page.get_by_label('Human source review status',exact=True).select_option('not_reviewed')
    page.get_by_label('Handling basis',exact=True).fill('Synthetic AI-assisted fixture; publisher rights remain unverified')
    page.get_by_role('button',name='Attach content',exact=True).click()
    expect(page.get_by_test_id('registered-text')).to_contain_text('edited by the fixture author')
    page.get_by_text('Source and provenance identity',exact=True).click()
    expect(page.get_by_text('AI-assisted origin, declared review:',exact=False)).to_contain_text('not_reviewed')
    expect(page.get_by_test_id('counts')).to_contain_text('0 approved')
    assert not (c['root']/'rights').exists()


def test_unicode_evidence_can_be_explicitly_reassociated(browser_case):
    from playwright.sync_api import expect
    page,c,_=browser_case;attach_text(page,'😀 The consortium’s fictional fleet evaluated sensors. An economic agreement was discussed.')
    page.get_by_label('Article domain economics',exact=True).check()
    page.get_by_label('Article domain geopolitics',exact=True).check()
    quote='😀 The consortium’s fictional fleet evaluated sensors.'
    map_claims(page,['Article domain: economics'],quote)
    expect(page.get_by_text(quote,exact=True).first).to_be_visible()
    page.get_by_label('Evidence 1 claim target',exact=True).select_option('/domains/1')
    expect(page.get_by_label('Evidence 1 claim target',exact=True)).to_have_value('/domains/1')
    page.get_by_role('button',name='Save Draft',exact=True).click()
    expect(page.get_by_role('status')).to_contain_text('Working draft saved')
    actor={'id':'12345678-1234-4234-8234-123456789abc'}
    versions,head=c['service'].working_history(c['candidate'],actor)
    evidence=versions[head]['annotation']['evidence'][0]
    assert evidence['quote']==quote and evidence['end']==len(quote)
    assert evidence['target']=='/domains/1'
