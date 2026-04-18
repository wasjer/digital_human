import pytest
from core.llm_client import _sanitize, EmptyResponseError


def test_strips_json_fence():
    assert _sanitize('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strips_bare_fence():
    assert _sanitize('```\n{"a": 1}\n```') == '{"a": 1}'


def test_passes_through_bare_json():
    assert _sanitize('{"a": 1}') == '{"a": 1}'


def test_strips_think_block_then_fence():
    raw = '<think>reasoning</think>\n```json\n{"a": 1}\n```'
    assert _sanitize(raw) == '{"a": 1}'


def test_strips_multiline_think_block():
    raw = '<think>\nline 1\nline 2\n</think>\n{"a": 1}'
    assert _sanitize(raw) == '{"a": 1}'


def test_strips_unclosed_think_before_json_start():
    raw = '<think>reasoning context...{"a": 1}'
    assert _sanitize(raw) == '{"a": 1}'


def test_strips_unclosed_think_before_array_start():
    raw = '<think>foo...[1, 2, 3]'
    assert _sanitize(raw) == '[1, 2, 3]'


def test_passes_through_plain_string():
    assert _sanitize('hello world') == 'hello world'


def test_raises_on_empty():
    with pytest.raises(EmptyResponseError):
        _sanitize('')


def test_raises_on_whitespace_only():
    with pytest.raises(EmptyResponseError):
        _sanitize('   \n\t  ')


def test_raises_on_none():
    with pytest.raises(EmptyResponseError):
        _sanitize(None)
