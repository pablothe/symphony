"""Tests for WORKFLOW.md parsing."""

import pytest

from symphony.workflow.loader import parse, load


def test_parse_with_front_matter():
    content = """---
tracker:
  kind: linear
polling:
  interval_ms: 5000
---

Hello {{ issue.title }}
"""
    result = parse(content)
    assert result.config["tracker"]["kind"] == "linear"
    assert result.config["polling"]["interval_ms"] == 5000
    assert "Hello {{ issue.title }}" in result.prompt_template


def test_parse_no_front_matter():
    content = "Just a prompt template {{ issue.title }}"
    result = parse(content)
    assert result.config == {}
    assert "Just a prompt template" in result.prompt_template


def test_parse_empty_front_matter():
    content = """---
---

Prompt here
"""
    result = parse(content)
    assert result.config == {}
    assert "Prompt here" in result.prompt_template


def test_parse_non_map_front_matter():
    content = """---
- item1
- item2
---

Prompt
"""
    with pytest.raises(ValueError, match="must decode to a map"):
        parse(content)


def test_parse_multiline_prompt():
    content = """---
tracker:
  kind: memory
---

Line 1
Line 2
Line 3
"""
    result = parse(content)
    assert "Line 1" in result.prompt_template
    assert "Line 3" in result.prompt_template


def test_load_missing_file():
    with pytest.raises(FileNotFoundError):
        load("/nonexistent/path/WORKFLOW.md")
