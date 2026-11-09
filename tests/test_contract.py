"""Read-only project contract (/health, /capabilities, /runs): served without a session, aggregate only."""

from inkfall import contract


def test_contract_needs_no_session_and_has_project_id(client):
    for path in ("/health", "/capabilities", "/runs"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.json()["project_id"] == "inkfall"
        assert r.headers["content-security-policy"].startswith("default-src 'none'")


def test_runs_come_from_saved_reports_only(client):
    body = client.get("/runs?limit=8").json()
    assert body["runs"] == contract.runs()[:8]
    for run in body["runs"]:
        assert run["kind"] in {"eval", "adversarial", "generative"}
        assert run["mode"] == "recorded" and run["provenance"]["synthetic"] is True
        assert run["status"] in {"completed", "failed"} and run["headline"]
        assert client.get(f"/runs/{run['run_id']}").json() == run
    assert client.get("/runs/not-a-run").status_code == 404
    assert client.get("/runs/..%2F..%2Fetc").status_code == 404


def test_contract_never_contains_tenant_content(client, corpus):
    blob = client.get("/runs?limit=50").text + client.get("/capabilities").text + client.get("/health").text
    for d in corpus:
        assert d.doc_key not in blob and d.title not in blob
        first = " ".join(d.body.split())[:50]
        assert first not in blob
    for name in ("ava.lindqvist", "Harrow", "Brightwater", "Orion", "Pellmoor Water"):
        assert name not in blob


def test_capabilities_state_limits_honestly(client):
    caps = client.get("/capabilities").json()
    assert caps["dataset"]["synthetic"] is True
    assert any("authentication" in x for x in caps["not_implemented"])
    assert any("decide access" in x for x in caps["disabled_by_design"])
