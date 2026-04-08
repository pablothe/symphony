"""Runtime configuration access.

Provides typed access to the current WORKFLOW.md configuration,
delegating to the WorkflowStore when available, or loading directly.
"""

from __future__ import annotations

from symphony.config.schema import SymphonyConfig, normalize_issue_state, parse_config
from symphony.workflow.loader import WorkflowDefinition

# Module-level state for the current workflow. Set by the WorkflowStore
# or directly during startup.
_current_workflow: WorkflowDefinition | None = None

DEFAULT_PROMPT_TEMPLATE = """\
You are working on a Linear issue.

Identifier: {{ issue.identifier }}
Title: {{ issue.title }}

Body:
{% if issue.description %}
{{ issue.description }}
{% else %}
No description provided.
{% endif %}
"""


def set_current_workflow(workflow: WorkflowDefinition) -> None:
    """Set the current workflow (called by WorkflowStore or startup)."""
    global _current_workflow
    _current_workflow = workflow


def get_current_workflow() -> WorkflowDefinition | None:
    """Get the current workflow definition, if loaded."""
    return _current_workflow


def settings() -> SymphonyConfig:
    """Get the current typed configuration.

    Raises RuntimeError if no workflow has been loaded.
    """
    workflow = _current_workflow
    if workflow is None:
        raise RuntimeError("No workflow loaded. Call set_current_workflow() first.")
    return parse_config(workflow.config)


def max_concurrent_agents_for_state(state_name: str) -> int:
    """Get the concurrency limit for a specific issue state."""
    config = settings()
    normalized = normalize_issue_state(state_name)
    return config.agent.max_concurrent_agents_by_state.get(
        normalized, config.agent.max_concurrent_agents
    )


def workflow_prompt() -> str:
    """Get the current workflow prompt template."""
    workflow = _current_workflow
    if workflow is None or not workflow.prompt_template.strip():
        return DEFAULT_PROMPT_TEMPLATE
    return workflow.prompt_template


def server_port() -> int | None:
    """Get the configured HTTP server port."""
    return settings().server.port


def validate() -> None:
    """Validate the current configuration semantically.

    Raises ValueError on validation failure.
    """
    config = settings()

    if config.tracker.kind is None:
        raise ValueError("Missing tracker.kind")

    if config.tracker.kind not in ("linear", "memory"):
        raise ValueError(f"Unsupported tracker.kind: {config.tracker.kind}")

    if config.tracker.kind == "linear":
        if not config.tracker.api_key:
            raise ValueError("Missing LINEAR_API_KEY (set tracker.api_key or LINEAR_API_KEY env var)")
        if not config.tracker.project_slug:
            raise ValueError("Missing tracker.project_slug")
