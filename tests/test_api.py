import pytest
from fastapi.testclient import TestClient

from takam_search.api import create_app

from .conftest import make_settings
from .fakes import FakeLLM, cite_first


@pytest.fixture(scope="module")
def client(settings):
    with TestClient(create_app(settings, llm=FakeLLM(cite_first))) as c:
        yield c


def test_health_reports_index_and_llm(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["chunks"] > 500 and body["docs"] == 44
    assert body["llm"]["enabled"] is True


def test_search_endpoint(client):
    body = client.get("/search", params={"q": "חתימה דיגיטלית"}).json()
    assert body["hits"][0]["doc_code"] == "H.1.3.1"
    assert body["hits"][0]["url"] == "https://takam.mof.gov.il/document/H.1.3.1"


def test_search_validation(client):
    assert client.get("/search", params={"q": ""}).status_code == 422
    assert client.get("/search", params={"q": "x" * 1001}).status_code == 422
    assert client.get("/search", params={"q": "   "}).json()["hits"] == []


def test_ask_endpoint_returns_cited_answer(client):
    body = client.post("/ask", json={"question": "האם חותמים בחתימה דיגיטלית על התחייבות?"}).json()
    assert body["mode"] == "answer" and body["citations"][0]["doc_code"] == "H.1.3.1"


def test_ask_rejects_blank_question(client):
    assert client.post("/ask", json={"question": "   "}).status_code == 422
    assert client.post("/ask", json={}).status_code == 422


def test_ui_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and 'dir="rtl"' in r.text


def test_widget_and_demo_are_served(client):
    w = client.get("/widget.js")
    assert w.status_code == 200 and "javascript" in w.headers["content-type"] and "takam-close" in w.text
    d = client.get("/demo")
    assert d.status_code == 200 and "/widget.js" in d.text


def test_search_only_mode_without_llm(settings):
    with TestClient(create_app(settings, use_settings_llm=False)) as c:
        body = c.post("/ask", json={"question": "חתימה דיגיטלית"}).json()
        assert body["mode"] == "search_only" and body["hits"]
        assert c.get("/health").json()["llm"]["enabled"] is False


def test_health_is_503_when_index_missing(tmp_path):
    settings = make_settings(tmp_path)  # empty data dir: no manifest, no index
    with TestClient(create_app(settings, use_settings_llm=False)) as c:
        r = c.get("/health")
        assert r.status_code == 503 and r.json()["status"] == "unavailable"


def test_index_is_built_on_startup_when_missing(tmp_path, data_dir):
    import shutil
    shutil.copytree(data_dir / "raw", tmp_path / "raw")
    settings = make_settings(tmp_path)
    assert not settings.db_path.exists()
    with TestClient(create_app(settings, use_settings_llm=False)) as c:
        assert c.get("/health").status_code == 200
