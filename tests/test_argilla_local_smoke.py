"""Explicit opt-in SDK/server smoke test against the local Docker deployment."""
import os
from uuid import uuid4

import pytest


@pytest.mark.skipif(os.environ.get('AIC_ARGILLA_SMOKE') != '1', reason='Set AIC_ARGILLA_SMOKE=1 for local Docker smoke')
def test_local_sdk_question_record_and_draft_round_trip():
    rg = pytest.importorskip('argilla')
    from src.argilla_bridge import local_client, settings
    _, client = local_client()
    name = 'aic-synthetic-smoke-'+uuid4().hex[:12]
    dataset = rg.Dataset(name=name, workspace='aic1', settings=settings(rg), client=client).create()
    # Automated synthetic draft only: never a real candidate, human attestation or approval.
    try:
        fields = {n:'Synthetic automated API smoke fixture; no human review' for n in ('title','source','context','text','guidance')}
        dataset.records.log([rg.Record(id='synthetic-fixture', fields=fields,
            metadata={'candidate_id':'synthetic','state':'pending_content','content_revision':'none'},
            responses=[rg.Response('domains',['economics'],user_id=client.me.id,status='draft'),
                       rg.Response('defense_event_types',['none'],user_id=client.me.id,status='draft')])])
        rows = list(dataset.records)
        assert len(rows)==1 and rows[0].id=='synthetic-fixture'
        assert rows[0].fields.to_dict()==fields
        assert rows[0].responses['domains'][0].value==['economics']
        assert rows[0].responses['domains'][0].status.value=='draft'
        assert str(rows[0].responses['domains'][0].user_id)==str(client.me.id)
    finally:
        # Only this test-created, uniquely named synthetic dataset is removed.
        dataset.delete()
