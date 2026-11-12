from __future__ import annotations

from investment_engine.providers.output_sanitizer import sanitize_llm_json


def test_plain_json():
    assert sanitize_llm_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert sanitize_llm_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_fenced_no_lang():
    assert sanitize_llm_json('```\n{"a": 1}\n```') == {"a": 1}


def test_answer_tags():
    assert sanitize_llm_json("<answer>{\"a\": 1}</answer>") == {"a": 1}


def test_prose_around_json():
    assert sanitize_llm_json('Here is the result: {"a": 1} thanks') == {"a": 1}


def test_list():
    assert sanitize_llm_json('[1, 2, 3]') == [1, 2, 3]


def test_trailing_comma_repair():
    assert sanitize_llm_json('{"a": 1,}') == {"a": 1}


def test_none_on_garbage():
    assert sanitize_llm_json("not json at all") is None


def test_none_on_empty():
    assert sanitize_llm_json("") is None
    assert sanitize_llm_json(None) is None


def test_never_raises():
    assert sanitize_llm_json(123) is None or sanitize_llm_json(123) == 123
