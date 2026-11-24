from datetime import date

from takam_search.validity import current_version, is_in_force, parse_date

TODAY = date(2026, 11, 23)


def v(num, frm, to, cid="c"):
    return {"rtn_versionnumber__c": num, "rtn_validfrom__c": frm, "rtn_validto__c": to,
            "rtn_contentversionid__c": cid}


def test_parse_date_formats():
    assert parse_date("2027-12-31T00:00:00.000Z") == date(2027, 12, 31)
    assert parse_date(None) is None and parse_date("garbage") is None


def test_in_force_boundaries():
    assert is_in_force(None, None, TODAY)
    assert is_in_force(None, TODAY, TODAY)  # last valid day counts
    assert not is_in_force(None, date(2025, 2, 5), TODAY)
    assert not is_in_force(date(2027, 1, 1), None, TODAY)  # not yet in force


def test_current_version_prefers_version_in_force():
    versions = [v(2, "2017-08-01T00:00:00.000Z", "2020-06-23T00:00:00.000Z", "old"),
                v(3, "2020-06-24T00:00:00.000Z", None, "new")]
    assert current_version(versions, TODAY)["rtn_contentversionid__c"] == "new"


def test_current_version_falls_back_to_latest_when_all_expired():
    versions = [v(1, "2020-01-01T00:00:00.000Z", "2021-01-01T00:00:00.000Z", "a"),
                v(2, "2022-01-01T00:00:00.000Z", "2025-02-05T00:00:00.000Z", "b")]
    assert current_version(versions, TODAY)["rtn_contentversionid__c"] == "b"


def test_versions_without_content_id_are_ignored():
    assert current_version([v(1, None, None, None)], TODAY) is None
    assert current_version([], TODAY) is None
