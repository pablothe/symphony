"""Loads workflow configuration and prompt from WORKFLOW.md.

Parses YAML front matter (between --- delimiters) and the remaining
Markdown body as the prompt template.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class WorkflowDefinition:
    """Parsed WORKFLOW.md payload."""

    config: dict  # type: ignore[type-arg]
    prompt_template: str


def load(path: str | Path) -> WorkflowDefinition:
    """Load and parse a WORKFLOW.md file.

    Raises FileNotFoundError if the file doesn't exist.
    Raises ValueError if the front matter is invalid.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Missing WORKFLOW.md at {path}")

    content = path.read_text(encoding="utf-8")
    return parse(content)


def parse(content: str) -> WorkflowDefinition:
    """Parse WORKFLOW.md content into config and prompt template.

    Raises ValueError if YAML front matter doesn't decode to a dict.
    """
    front_matter_lines, prompt_lines = _split_front_matter(content)
    config = _parse_front_matter(front_matter_lines)
    prompt_template = "\n".join(prompt_lines).strip()

    return WorkflowDefinition(config=config, prompt_template=prompt_template)


def _split_front_matter(content: str) -> tuple[list[str], list[str]]:
    """Split content into YAML front matter lines and prompt body lines."""
    lines = re.split(r"\r\n|\r|\n", content)

    if not lines or lines[0] != "---":
        return [], lines

    # Find the closing ---
    tail = lines[1:]
    front_matter: list[str] = []
    rest: list[str] = []

    found_end = False
    for i, line in enumerate(tail):
        if line == "---":
            rest = tail[i + 1 :]
            found_end = True
            break
        front_matter.append(line)

    if not found_end:
        # No closing ---, treat everything after opening as front matter
        return front_matter, []

    return front_matter, rest


def _parse_front_matter(lines: list[str]) -> dict:  # type: ignore[type-arg]
    """Parse YAML front matter lines into a config dict."""
    yaml_text = "\n".join(lines)

    if not yaml_text.strip():
        return {}

    decoded = yaml.safe_load(yaml_text)

    if decoded is None:
        return {}

    if not isinstance(decoded, dict):
        raise ValueError("WORKFLOW.md front matter must decode to a map")

    return decoded
