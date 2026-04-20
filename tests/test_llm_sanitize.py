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


import logging


def test_httpx_logger_at_warning_level():
    import core.llm_client  # noqa: F401，触发模块加载
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_openai_logger_at_warning_level():
    import core.llm_client  # noqa: F401
    assert logging.getLogger("openai").level >= logging.WARNING


def test_llm_client_log_format_uses_name():
    # basicConfig 的 format 字符串必须包含 %(name)s，而不是硬编码 "llm_client"
    import core.llm_client as c
    root = logging.getLogger()
    # 找到 StreamHandler 的 formatter
    fmt = None
    for h in root.handlers:
        if h.formatter is not None:
            fmt = h.formatter._fmt
            break
    assert fmt is not None
    assert "%(name)s" in fmt
    assert "llm_client %(" not in fmt  # 不能硬编码
