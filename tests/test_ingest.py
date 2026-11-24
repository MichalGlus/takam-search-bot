import json
import shutil
from datetime import date

import pytest

from takam_search.client import InvalidDocumentError, TakamAPIError
from takam_search.index import IndexBuildError, read_stats
from takam_search.ingest import build, fetch, select_documents

from .conftest import RAW, make_settings

DOCS = [
    {"sfid": "p1", "documentcodetext": "H.1.3.3", "documenttype": "Instruction", "mainchaptercode": 1, "name": "כתבי שיפוי"},
    {"sfid": "p2", "documentcodetext": "H.2.1.1", "documenttype": "Instruction", "mainchaptercode": 2, "name": "אחר"},
    # Children have no chapter code; they are linked only through parentdocument.
    {"sfid": "c1", "documentcodetext": "HZ.1.3.3.1", "documenttype": "Temporary Instruction",
     "mainchaptercode": None, "parentdocument": "p1", "name": "כתבי שיפוי"},
    {"sfid": "c2", "documentcodetext": "T.1.3.3.1", "documenttype": "Form", "mainchaptercode": None,
     "parentdocument": "p1", "name": "טופס"},
    {"sfid": "c3", "documentcodetext": "HOD.2.1.1.1", "documenttype": "Message", "mainchaptercode": None,
     "parentdocument": "p2", "name": "הודעה"},
    {"sfid": "x", "documentcodetext": None, "documenttype": "Instruction", "mainchaptercode": 1, "name": "ללא קוד"},
]


def test_select_includes_children_of_chapter_but_not_forms():
    codes = [d["documentcodetext"] for d in select_documents(DOCS, [1])]
    assert codes == ["H.1.3.3", "HZ.1.3.3.1"]


class FakeClient:
    def documents(self):
        return DOCS

    def versions(self, sfid):
        if sfid == "c1":
            return [{"rtn_versionnumber__c": 1, "rtn_validfrom__c": None, "rtn_validto__c": None,
                     "rtn_contentversionid__c": None}]  # no downloadable content
        return [{"rtn_versionnumber__c": 1, "rtn_validfrom__c": None, "rtn_validto__c": None,
                 "rtn_contentversionid__c": f"cv-{sfid}"}]

    def download(self, cid, code):
        return (RAW / "docs" / "H.1.3.3.docx").read_bytes()


def test_fetch_records_failures_and_continues(tmp_path):
    settings = make_settings(tmp_path, request_delay=0)
    manifest = fetch(settings, FakeClient(), today=date(2026, 11, 23))
    by_code = {d["code"]: d for d in manifest["documents"]}
    assert by_code["H.1.3.3"]["file"] == "docs/H.1.3.3.docx" and by_code["H.1.3.3"]["error"] is None
    assert by_code["HZ.1.3.3.1"]["file"] is None and "no downloadable version" in by_code["HZ.1.3.3.1"]["error"]
    assert by_code["HZ.1.3.3.1"]["parent_code"] == "H.1.3.3"
    assert json.loads(settings.manifest_path.read_text(encoding="utf-8")) == manifest


def test_fetch_handles_invalid_download(tmp_path):
    class BadDownload(FakeClient):
        def download(self, cid, code):
            raise InvalidDocumentError("not docx")

    manifest = fetch(make_settings(tmp_path, request_delay=0), BadDownload(), today=date(2026, 11, 23))
    assert all(d["error"] for d in manifest["documents"])


def test_fetch_propagates_when_site_is_down(tmp_path):
    class Down(FakeClient):
        def documents(self):
            raise TakamAPIError("GET api/Document failed: HTTP 503")

    with pytest.raises(TakamAPIError):
        fetch(make_settings(tmp_path, request_delay=0), Down())


def _copy_raw(dst):
    shutil.copytree(RAW, dst / "raw")


def test_build_refuses_to_replace_index_when_chunks_drop(tmp_path):
    _copy_raw(tmp_path)
    settings = make_settings(tmp_path)
    good = build(settings)

    # Simulate a broken source: most DOCX files now fail to parse.
    for f in list((tmp_path / "raw" / "docs").glob("*.docx"))[:-3]:
        f.write_bytes(b"not a docx")
    with pytest.raises(IndexBuildError, match="previous index kept"):
        build(settings)
    assert read_stats(settings.db_path)["chunks"] == good["chunks"]  # old index still served
    assert not settings.db_path.with_suffix(".db.tmp").exists()


def test_build_records_failed_documents(tmp_path):
    _copy_raw(tmp_path)
    (tmp_path / "raw" / "docs" / "H.1.3.3.docx").write_bytes(b"broken")
    stats = build(make_settings(tmp_path))
    assert stats["failed_docs"] == ["H.1.3.3"]
