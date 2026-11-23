"""Synthetic global source fixtures; production datasets are never written."""
from copy import deepcopy

import pytest

from src.content_reference import load_source, register_source
from src.global_annotation_schema import evidence_targets
from src.global_io import read_object
from src.global_review import DEFAULT_POLICY, DEFAULT_TAXONOMY


@pytest.fixture
def global_case(tmp_path, monkeypatch):
    import urllib.request

    def no_network(*args, **kwargs):
        pytest.fail("Global review must never fetch external content")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", no_network)
    root = tmp_path / "global-store"
    text_file = tmp_path / "source.txt"
    text = ("Kenya and Brazil held a naval exercise in Mombasa on 2026-11-20.\r\n"
            "Their navies signed a defense cooperation agreement. A trade agreement cut tariffs. Café.\n")
    text_file.write_bytes(text.encode("utf-8"))
    metadata = {"source_id": "https://example.org/report?utm_source=test", "publisher": "Synthetic publisher",
                "adapter": "manual", "article_title": "Synthetic multinational developments",
                "published_at": "2026-11-20T10:00:00Z", "published_at_raw": "20 Nov 2026",
                "collected_at": "2026-11-22T00:00:00Z", "content_type": "human_summary",
                "rights_note": "Synthetic fixture; no production training permission implied",
                "provenance_method": "synthetic_test_fixture"}
    source = register_source(root, metadata, text_file)

    def article_for(source_id=source):
        ref, content, _ = load_source(root, source_id)
        countries = [{"code": "KE", "role": "host"}, {"code": "BR", "role": "participant"}]
        unit = {"domains": ["defense"], "defense_event_types": ["military_exercise"], "countries": countries,
                "organizations": ["Kenyan Navy", "Brazilian Navy"], "event_date": "2026-11-20",
                "event_location": "Mombasa", "evidence_status": "reported", "rationale": "Synthetic reviewed exercise"}
        article = {**deepcopy(unit), "schema_version": "aic-global-annotation-v2", "event_coverage": "complete",
                   "event_coverage_note": None, "events": [{**deepcopy(unit), "instance_id": "exercise-1"}], "evidence": []}
        for target in sorted(evidence_targets(article)):
            article["evidence"].append({"target": target, "content_revision_sha256": ref["content_revision_sha256"],
                                        "start": 0, "end": len(content), "quote": content,
                                        "attribution": "Synthetic source claims; no independent corroboration"})
        return article

    return {"root": root, "source": source, "metadata": metadata, "text_file": text_file, "text": text,
            "annotation": article_for(), "article_for": article_for,
            "taxonomy": read_object(DEFAULT_TAXONOMY), "policy": read_object(DEFAULT_POLICY)}
