"""The live Claude check is opt-in and paid: without ANTHROPIC_API_KEY it must stop before any request."""

import sys

import pytest

from inkfall import eval_generative


def test_claude_live_check_refuses_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["eval_generative", "--backend", "claude"])
    with pytest.raises(SystemExit) as exc:
        eval_generative.main()
    assert "ANTHROPIC_API_KEY is not set" in str(exc.value)


def test_reported_usage_totals_accept_both_provider_shapes():
    # OpenAI-style usage carries total_tokens; Anthropic-style carries input/output only (the 2026-11-09 run read 0).
    assert eval_generative._reported_total({"total_tokens": 15801}) == 15801
    assert eval_generative._reported_total({"input_tokens": 2139, "output_tokens": 281,
                                            "cache_read_input_tokens": 0}) == 2420
    assert eval_generative._reported_total(None) == 0
