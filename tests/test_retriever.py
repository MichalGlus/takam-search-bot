import pytest


def top_docs(hits, n=3):
    return list(dict.fromkeys(h.doc_code for h in hits))[:n]


@pytest.mark.parametrize(
    "query, expected, section",
    [
        # The site's own search returns 0 results for both of these.
        ("חתימה דיגיטלית", "H.1.3.1", "2.1.5"),
        ("עבירת משמעת", "H.1.3.1", "2.5.1"),
    ],
)
def test_golden_queries_found_in_instruction_body(retriever, query, expected, section):
    hits = retriever.search(query, k=5)
    assert hits[0].doc_code == expected
    assert any(h.section == section for h in hits if h.doc_code == expected)


def test_redirect_stub_leads_to_temporary_instruction(retriever):
    # H.1.3.3 only says "see temporary instruction HZ.1.3.3.1"; its content must be reachable.
    assert "HZ.1.3.3.1" in top_docs(retriever.search("כתבי שיפוי", k=5))
    assert retriever.related(["H.1.3.3"])["H.1.3.3"][0]["code"] == "HZ.1.3.3.1"


def test_answer_from_table_row(retriever):
    hits = retriever.search("סכום רמת אישור 3", k=5)
    assert hits[0].doc_code == "H.1.3.1"
    assert "43,000" in hits[0].text


def test_prefix_and_article_variants_match(retriever):
    # Query without the article / prefix still finds "היועץ המשפטי" in the text.
    hits = retriever.search("יועץ משפטי", k=8)
    assert any("היועץ המשפטי" in h.text for h in hits)


def test_question_phrasing_works(retriever):
    hits = retriever.search("האם אפשר לחתום על התחייבות בסיגמה בחתימה דיגיטלית?", k=5)
    assert hits[0].doc_code == "H.1.3.1"


def test_expired_documents_hidden_by_default(retriever):
    default = retriever.search("כרטיסי אשראי נטענים", k=20)
    assert "HZ.1.6.2.1" not in {h.doc_code for h in default}  # expired 2025-02-05
    expired = retriever.search("כרטיסי אשראי נטענים", k=20, include_expired=True)
    hz = [h for h in expired if h.doc_code == "HZ.1.6.2.1"]
    assert hz and not hz[0].in_force


def test_related_hides_expired_children_by_default(retriever):
    assert [r["code"] for r in retriever.related(["H.1.6.2"])["H.1.6.2"]] == ["HOD.1.6.2.1"]
    with_expired = [r["code"] for r in retriever.related(["H.1.6.2"], include_expired=True)["H.1.6.2"]]
    assert "HZ.1.6.2.1" in with_expired


def test_empty_query_returns_nothing(retriever):
    assert retriever.search("") == []
    assert retriever.search("   ") == []


def test_no_match_returns_nothing(retriever):
    assert retriever.search("קוונטים אסטרופיזיקה") == []


def test_very_long_query_does_not_fail(retriever):
    assert isinstance(retriever.search("חתימה " * 2000), list)


def test_fts_syntax_in_query_does_not_crash(retriever):
    assert isinstance(retriever.search('"AND OR NEAR( * חתימה'), list)


def test_at_most_three_chunks_per_document(retriever):
    hits = retriever.search("חשב המשרד", k=20)
    counts = {}
    for h in hits:
        counts[h.doc_code] = counts.get(h.doc_code, 0) + 1
    assert max(counts.values()) <= 3


@pytest.mark.parametrize("question", [
    "האם אפשר לחתום בחתימה דיגיטלית?",  # regression: §2.1.5 was ranked 7th
    "האם אפשר לחתום על התחייבות בחתימה דיגיטלית?",
])
def test_exact_phrase_section_ranks_high(retriever, question):
    top = [(h.doc_code, h.section) for h in retriever.search(question, 8)][:3]
    assert ("H.1.3.1", "2.1.5") in top


def test_generic_phrase_does_not_crowd_out_answer(retriever):
    # regression: phrase-first ranking let "חשבון בנק" push out the 25,000 ceiling (1.5.2 §2.3.3)
    hits = retriever.search("מה התקרה של דמי מחזור בחשבון בנק?", 8)
    assert any(h.doc_code == "H.1.5.2" and "25,000" in h.text for h in hits[:5])


def test_rewrites_cannot_push_out_original_top_hits(retriever):
    # Regression: LLM rewrites with a term the instructions don't use displaced 1.3.1 §2.1.5.
    q = "האם אפשר לחתום על התחייבות בחתימה דיגיטלית?"
    rewrites = ["חתימה אלקטרונית התחייבות", "חתימה דיגיטלית מורשה חתימה", "אישור התחייבות חתימה אלקטרונית"]
    original_top = [h.chunk_id for h in retriever.search(q, 8)][:5]
    fused = [h.chunk_id for h in retriever.search_many([q, *rewrites], 8)]
    assert fused[:5] == original_top
    assert any(h.section == "2.1.5" for h in retriever.search_many([q, *rewrites], 8))


def test_search_many_merges_phrasings(retriever):
    hits = retriever.search_many(["חתימה דיגיטלית", "קופה קטנה"], k=10)
    assert {"H.1.3.1", "H.1.5.2"} <= {h.doc_code for h in hits}
