import httpx
import pytest

from takam_search.client import InvalidDocumentError, TakamAPIError, TakamClient


def make_client(handler, retries=2):
    sleeps = []
    client = TakamClient("https://example.test/", max_retries=retries,
                         transport=httpx.MockTransport(handler), sleep=sleeps.append)
    return client, sleeps


def test_retries_server_errors_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500) if calls["n"] < 3 else httpx.Response(200, json=[{"sfid": "x"}])

    client, sleeps = make_client(handler)
    assert client.documents() == [{"sfid": "x"}]
    assert calls["n"] == 3 and sleeps == [1, 2]  # exponential backoff


def test_timeout_raises_after_retries():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client, sleeps = make_client(handler)
    with pytest.raises(TakamAPIError, match="ReadTimeout"):
        client.documents()
    assert len(sleeps) == 2


def test_client_errors_are_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    client, _ = make_client(handler)
    with pytest.raises(TakamAPIError, match="404"):
        client.versions("missing")
    assert calls["n"] == 1


def test_download_rejects_non_docx_payload():
    # e.g. an HTML error page returned with status 200
    client, _ = make_client(lambda r: httpx.Response(200, content=b"<html>error</html>"))
    with pytest.raises(InvalidDocumentError):
        client.download("cid", "H.1.3.1")


def test_download_returns_docx_bytes():
    client, _ = make_client(lambda r: httpx.Response(200, content=b"PK\x03\x04data"))
    assert client.download("cid", "H.1.3.1").startswith(b"PK")
