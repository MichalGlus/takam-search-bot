from takam_search import hebrew


def test_gershayim_variants_normalize_to_same_token():
    forms = ['תכ"ם', "תכ''ם", "תכ״ם", "תכ׳ם"]
    assert {hebrew.normalize(f) for f in forms} == {"תכם"}


def test_quotes_outside_words_are_kept_as_separators():
    assert hebrew.tokens('הוראת "פורטל ספקים"') == ["הוראת", "פורטל", "ספקים"]


def test_prefix_variants_strip_one_or_two_prefix_letters():
    assert hebrew.prefix_variants("בחתימה") == ["חתימה"]
    assert hebrew.prefix_variants("והמשרד") == ["המשרד", "משרד"]


def test_short_words_are_not_cut():
    assert hebrew.prefix_variants("בית") == []  # would leave only 2 letters


def test_original_word_always_kept_in_query():
    # "משרד" could be cut to "שרד"; the original must stay an alternative.
    q = hebrew.build_match_query("משרד")
    assert '"משרד"' in q


def test_query_strips_stopwords_but_not_everything():
    assert hebrew.query_terms("האם אפשר לחתום בחתימה דיגיטלית?") == ["לחתום", "בחתימה", "דיגיטלית"]
    assert hebrew.query_terms("מה זה") == ["מה", "זה"]  # only stopwords: keep them


def test_empty_and_symbol_only_queries():
    assert hebrew.build_match_query("") is None
    assert hebrew.build_match_query("   ?!  ") is None


def test_fts_operators_in_user_input_are_quoted():
    q = hebrew.build_match_query('NEAR AND OR " * חתימה')
    assert q is not None and all(part.startswith('"') for part in q.replace("(", "").replace(")", "").split(" OR "))


def test_long_query_is_capped():
    q = hebrew.query_terms(" ".join(f"מילה{i}" for i in range(500)))
    assert len(q) == hebrew.MAX_QUERY_TOKENS


def test_niqqud_removed():
    assert hebrew.normalize("חֲתִימָה") == "חתימה"
