"""Tests for _strip_control_tokens in orchestrator/step.py."""

from jarvis.orchestrator.step import _strip_control_tokens


def test_plain_text_unchanged():
    assert _strip_control_tokens("Hello, how can I help?") == "Hello, how can I help?"


def test_strips_end_token():
    assert _strip_control_tokens("Hello<|end|>") == "Hello"


def test_truncates_at_start_token():
    text = (
        "Sure thing!<|start|>assistant<|channel|>"
        'analysis to=functions.exec_host code<|message|>{"command": "ls"}<|call|>'
    )
    assert _strip_control_tokens(text) == "Sure thing!"


def test_truncates_at_first_marker():
    text = "Here is info<|analysis|>internal reasoning<|final|>done"
    assert _strip_control_tokens(text) == "Here is info"


def test_only_control_tokens_returns_empty():
    text = '<|start|>assistant<|channel|>analysis<|end|>'
    assert _strip_control_tokens(text) == ""


def test_end_token_plus_marker():
    text = "Answer<|end|><|start|>more stuff"
    assert _strip_control_tokens(text) == "Answer"


def test_empty_string():
    assert _strip_control_tokens("") == ""
