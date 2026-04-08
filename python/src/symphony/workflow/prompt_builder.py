"""Builds agent prompts from issue data using Jinja2 templates.

Replaces the Elixir PromptBuilder that used Liquid/Solid templates.
Jinja2 is syntax-compatible for simple variable interpolation ({{ var }})
and conditionals ({% if %}...{% endif %}).
"""

from __future__ import annotations

from jinja2 import Environment, StrictUndefined

from symphony.config.config import workflow_prompt
from symphony.models.issue import Issue

_jinja_env = Environment(undefined=StrictUndefined)


def build_prompt(issue: Issue, attempt: int | None = None) -> str:
    """Render the workflow prompt template with issue context.

    Args:
        issue: The issue to build the prompt for.
        attempt: Retry attempt number (None for first run, >=1 for retries).

    Returns:
        The rendered prompt string.
    """
    template_str = workflow_prompt()
    template = _jinja_env.from_string(template_str)

    return template.render(
        issue=issue.to_template_dict(),
        attempt=attempt,
    )
