"""API contract: response shapes the web app relies on, and the committed OpenAPI snapshot."""

import json
from pathlib import Path

from inkfall.api import create_app

ROOT = Path(__file__).resolve().parents[1]
ASK_KEYS = {"question", "as_of", "scope", "status", "mode", "mode_label", "answer", "abstained", "abstain_reason",
            "trust", "retrieval", "sources", "graph", "generation", "latency_ms", "ranked_refs", "request_id"}
TRUST_KEYS = {"evidence_coverage", "matched_terms", "missing_terms", "gaps", "conflicts", "amendment_overrides",
              "freshness", "untrusted_instructions_in_sources", "untrusted_instructions_in_question", "note"}


def test_openapi_snapshot_is_current():
    live = create_app().openapi()
    snap = json.loads((ROOT / "docs" / "openapi.json").read_text())
    assert live["paths"].keys() == snap["paths"].keys(), "regenerate docs/openapi.json"
    assert live["components"]["schemas"] == snap["components"]["schemas"], "regenerate docs/openapi.json"


def test_ask_shape(client, tokens):
    r = client.post("/api/ask", headers=tokens["dana.whitcombe"], json={"question": "What uptime has Orion committed to?",
                                                                         "as_of": "2026-11-01"})
    body = r.json()
    assert ASK_KEYS <= body.keys() and TRUST_KEYS <= body["trust"].keys()
    assert body["status"] in {"supported", "contradictory", "insufficient_evidence", "partially_unsupported"}
    assert body["mode"] == "extractive" and "no language model" in body["mode_label"]
    for a in body["answer"]:
        assert {"text", "citations", "support", "notes"} <= a.keys()
        for c in a["citations"]:
            assert {"pid", "version_id", "ref", "char_start", "char_end", "quote"} <= c.keys()
    for s in body["sources"]:
        assert {"pid", "ref", "version_id", "char_start", "char_end", "text", "method_ranks", "in_force"} <= s.keys()
    kinds = {n["kind"] for n in body["graph"]["nodes"]}
    assert {"question", "clause", "document"} <= kinds
    assert "ranked_version_ids" not in body


def test_document_shape(client, tokens):
    h = tokens["dana.whitcombe"]
    docs = client.get("/api/documents?include_history=true", headers=h).json()
    assert {"version_id", "ref", "doc_key", "title", "classification", "effective_date", "in_force"} <= docs[0].keys()
    d = client.get(f"/api/documents/{docs[0]['version_id']}", headers=h).json()
    assert {"text", "chunks", "lineage", "access", "versions"} <= d.keys()
    assert {"checksum_sha256", "ingested_at", "extraction_method", "retention"} <= d["lineage"].keys()
    assert d["access"]["decision"] == "allowed" and d["access"]["reasons"]


def test_compare_shape(client, tokens):
    h = tokens["dana.whitcombe"]
    docs = [d for d in client.get("/api/documents?include_history=true", headers=h).json() if d["doc_key"] == "CV-MSA-ORION"]
    a, b = sorted(docs, key=lambda d: d["version"])[:2]
    cmp = client.get(f"/api/compare/{a['version_id']}/{b['version_id']}", headers=h).json()
    assert cmp["a"]["ref"] == "CV-MSA-ORION@1" and cmp["b"]["ref"] == "CV-MSA-ORION@2"
    changes = [p for op in cmp["ops"] if op["op"] != "equal" for p in op["pairs"]]
    assert any(p["value_changes"] for p in changes), "v1->v2 changes notice period and cap"


def test_system_and_identities(client, tokens):
    ids = client.get("/api/identities").json()
    assert len(ids) == 12 and all("tenant_name" in i for i in ids)
    sysinfo = client.get("/api/system", headers=tokens["ava.lindqvist"]).json()
    assert {"embedding", "reranker", "generation_backends", "dataset_version"} <= sysinfo.keys()
