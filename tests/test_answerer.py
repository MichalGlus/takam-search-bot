import pytest
from pydantic import BaseModel

from takam_search.answerer import (
    Answerer,
    GroundedAnswer,
    LangChainLLM,
    LLMError,
    build_answer_prompt,
    build_llm,
)

from .conftest import make_settings
from .fakes import FakeLLM, cite_first, first_excerpt_id

Q = "האם אפשר לחתום על התחייבות בסיגמה בחתימה דיגיטלית?"


def test_answer_with_verified_citation(retriever):
    result = Answerer(retriever, FakeLLM(cite_first)).ask(Q)
    assert result.mode == "answer"
    assert result.citations and result.citations[0].doc_code == "H.1.3.1"
    assert {c.chunk_id for c in result.citations} <= {h.chunk_id for h in result.hits}


def test_citation_to_unknown_excerpt_is_dropped(retriever):
    def answer(prompt):
        return GroundedAnswer(found=True, answer="תשובה", citations=[first_excerpt_id(prompt), 999999])

    result = Answerer(retriever, FakeLLM(answer)).ask(Q)
    assert result.mode == "answer"
    assert [c.chunk_id for c in result.citations] == [result.hits[0].chunk_id] or 999999 not in [
        c.chunk_id for c in result.citations]


def test_answer_without_any_valid_citation_is_not_shown(retriever):
    llm = FakeLLM(lambda p: GroundedAnswer(found=True, answer="המצאה", citations=[123456789]))
    result = Answerer(retriever, llm).ask(Q)
    assert result.mode == "search_only" and result.answer is None and result.hits


def test_model_says_not_found(retriever):
    llm = FakeLLM(lambda p: GroundedAnswer(found=False, answer="", citations=[]))
    result = Answerer(retriever, llm).ask(Q)
    assert result.mode == "not_found" and result.answer is None


def test_no_relevant_chunks_skips_llm(retriever):
    llm = FakeLLM(cite_first)
    result = Answerer(retriever, llm).ask("קוונטים אסטרופיזיקה")
    assert result.mode == "not_found"
    assert [name for name, _ in llm.calls] == ["QueryRewrite"]  # no answer call without excerpts


def test_llm_failure_falls_back_to_search_results(retriever):
    result = Answerer(retriever, FakeLLM(cite_first, fail_answer=True)).ask(Q)
    assert result.mode == "search_only" and result.hits and "אינו זמין" in result.notice


def test_rewrite_failure_still_answers(retriever):
    result = Answerer(retriever, FakeLLM(cite_first, fail_rewrite=True)).ask(Q)
    assert result.mode == "answer" and result.queries == [Q]


def test_rewrites_are_used_for_retrieval(retriever):
    llm = FakeLLM(cite_first, rewrites=["קופה קטנה", "", "דמי מחזור"])
    result = Answerer(retriever, llm).ask("איך מנהלים כסף מזומן ביחידה?")
    assert result.queries == ["איך מנהלים כסף מזומן ביחידה?", "קופה קטנה", "דמי מחזור"]
    assert "H.1.5.2" in {h.doc_code for h in result.hits}


def test_without_llm_returns_search_only(retriever):
    result = Answerer(retriever, None).ask(Q)
    assert result.mode == "search_only" and result.hits and result.answer is None


def test_prompt_marks_validity_and_ids(retriever):
    hits = retriever.search("כרטיסי אשראי נטענים", k=20, include_expired=True)
    prompt = build_answer_prompt("שאלה", hits)
    assert "[ID " in prompt and "לא בתוקף" in prompt


# ---------------------------------------------------------------- LangChain adapter

class _StubRunnable:
    def __init__(self, result):
        self.result = result

    def invoke(self, messages):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _StubChatModel:
    def __init__(self, result):
        self.result = result

    def with_structured_output(self, schema):
        return _StubRunnable(self.result)


def test_langchain_adapter_accepts_dict_output():
    llm = LangChainLLM(_StubChatModel({"found": True, "answer": "x", "citations": [1]}))
    out = llm.structured("s", "p", GroundedAnswer)
    assert isinstance(out, GroundedAnswer) and out.citations == [1]


def test_langchain_adapter_wraps_provider_errors():
    llm = LangChainLLM(_StubChatModel(RuntimeError("quota exceeded")))
    with pytest.raises(LLMError, match="quota"):
        llm.structured("s", "p", GroundedAnswer)


def test_langchain_adapter_rejects_wrong_type():
    class Other(BaseModel):
        x: int = 1

    with pytest.raises(LLMError):
        LangChainLLM(_StubChatModel(Other())).structured("s", "p", GroundedAnswer)


def test_langchain_adapter_uses_fallback_model_when_primary_fails():
    primary = _StubChatModel(RuntimeError("503 UNAVAILABLE high demand"))
    fallback = _StubChatModel({"found": True, "answer": "x", "citations": [1]})
    out = LangChainLLM(primary, fallback).structured("s", "p", GroundedAnswer)
    assert out.answer == "x"


def test_langchain_adapter_fails_when_all_models_fail():
    llm = LangChainLLM(_StubChatModel(RuntimeError("503")), _StubChatModel(RuntimeError("504")))
    with pytest.raises(LLMError, match="503.*504"):
        llm.structured("s", "p", GroundedAnswer)


def test_build_llm_is_none_without_key(tmp_path, monkeypatch):
    for var in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert build_llm(make_settings(tmp_path, llm_enabled=True)) is None
