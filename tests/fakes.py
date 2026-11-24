"""Test doubles for the LLM."""

from __future__ import annotations

from collections.abc import Callable

from takam_search.answerer import GroundedAnswer, LLMError, QueryRewrite


class FakeLLM:
    """Answers with a function of the prompt; records calls."""

    def __init__(self, answer: Callable[[str], GroundedAnswer] | None = None,
                 rewrites: list[str] | None = None, fail_answer: bool = False, fail_rewrite: bool = False):
        self._answer = answer
        self._rewrites = rewrites or []
        self.fail_answer = fail_answer
        self.fail_rewrite = fail_rewrite
        self.calls: list[tuple[str, str]] = []

    def structured(self, system, prompt, schema):
        self.calls.append((schema.__name__, prompt))
        if schema is QueryRewrite:
            if self.fail_rewrite:
                raise LLMError("rewrite down")
            return QueryRewrite(queries=self._rewrites)
        if self.fail_answer:
            raise LLMError("answer down")
        return self._answer(prompt)


def first_excerpt_id(prompt: str) -> int:
    return int(prompt.split("[ID ", 1)[1].split("]", 1)[0])


def cite_first(prompt: str) -> GroundedAnswer:
    return GroundedAnswer(found=True, answer="כן, בחתימה דיגיטלית (הוראה 1.3.1 סעיף 2.1.5).",
                          citations=[first_excerpt_id(prompt)])
