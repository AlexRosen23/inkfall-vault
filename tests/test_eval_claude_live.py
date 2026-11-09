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
