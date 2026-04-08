"""Per-issue workspace directory management.

Creates isolated directories for each issue, runs lifecycle hooks,
and supports both local and SSH remote workspaces.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from symphony.config.config import settings
from symphony.models.issue import Issue
from symphony.ssh import client as ssh_client
from symphony.workspace.path_safety import (
    canonicalize,
    sanitize_workspace_key,
    workspace_path_for_issue,
)

logger = logging.getLogger(__name__)


class WorkspaceError(Exception):
    """Workspace operation error."""


async def create_for_issue(
    issue: Issue | str | None,
    worker_host: str | None = None,
) -> str:
    """Create a workspace directory for an issue.

    Returns the workspace path.
    Raises WorkspaceError on failure.
    """
    identifier = _extract_identifier(issue)
    safe_id = sanitize_workspace_key(identifier)
    config = settings()

    workspace = workspace_path_for_issue(config.workspace.root, safe_id)

    if worker_host is None:
        _validate_local_workspace(workspace, config.workspace.root)

    workspace_path, created = await _ensure_workspace(workspace, worker_host)

    if created:
        hook = config.hooks.after_create
        if hook:
            await _run_hook(
                hook, workspace_path, identifier, "after_create",
                worker_host, config.hooks.timeout_ms,
            )

    return workspace_path


async def remove(
    workspace: str,
    worker_host: str | None = None,
) -> None:
    """Remove a workspace directory.

    Runs the before_remove hook if configured.
    """
    config = settings()
    hook = config.hooks.before_remove

    if worker_host is None:
        if Path(workspace).is_dir() and hook:
            await _run_hook(
                hook, workspace, Path(workspace).name, "before_remove",
                None, config.hooks.timeout_ms,
            )
        if Path(workspace).exists():
            _validate_local_workspace(workspace, config.workspace.root)
            shutil.rmtree(workspace, ignore_errors=True)
    else:
        if hook:
            script = (
                f"workspace={_shell_escape(workspace)}\n"
                f'if [ -d "$workspace" ]; then\n'
                f'  cd "$workspace"\n'
                f"  {hook}\n"
                f"fi"
            )
            try:
                await ssh_client.run(worker_host, script, timeout_s=config.hooks.timeout_ms / 1000)
            except Exception:
                logger.exception("before_remove hook failed on %s", worker_host)

        script = f"rm -rf {_shell_escape(workspace)}"
        await ssh_client.run(worker_host, script, timeout_s=config.hooks.timeout_ms / 1000)


async def remove_issue_workspaces(
    identifier: str,
    worker_host: str | None = None,
) -> None:
    """Remove workspaces for a given issue identifier."""
    config = settings()
    safe_id = sanitize_workspace_key(identifier)
    workspace = workspace_path_for_issue(config.workspace.root, safe_id)

    try:
        await remove(workspace, worker_host)
    except Exception:
        logger.exception("Failed to remove workspace for %s", identifier)


async def run_before_run_hook(
    workspace: str,
    issue: Issue | str | None,
    worker_host: str | None = None,
) -> None:
    """Run the before_run lifecycle hook if configured."""
    config = settings()
    hook = config.hooks.before_run
    if hook:
        identifier = _extract_identifier(issue)
        await _run_hook(hook, workspace, identifier, "before_run", worker_host, config.hooks.timeout_ms)


async def run_after_run_hook(
    workspace: str,
    issue: Issue | str | None,
    worker_host: str | None = None,
) -> None:
    """Run the after_run lifecycle hook if configured (failures ignored)."""
    config = settings()
    hook = config.hooks.after_run
    if hook:
        identifier = _extract_identifier(issue)
        try:
            await _run_hook(hook, workspace, identifier, "after_run", worker_host, config.hooks.timeout_ms)
        except Exception:
            logger.exception("after_run hook failed for %s", identifier)


async def _ensure_workspace(
    workspace: str,
    worker_host: str | None,
) -> tuple[str, bool]:
    """Ensure the workspace directory exists. Returns (path, was_created)."""
    if worker_host is None:
        path = Path(workspace)
        if path.is_dir():
            return workspace, False
        if path.exists():
            shutil.rmtree(workspace)
        path.mkdir(parents=True, exist_ok=True)
        return workspace, True
    else:
        # Remote workspace creation
        config = settings()
        script = (
            f"set -eu\n"
            f"workspace={_shell_escape(workspace)}\n"
            f'case "$workspace" in\n'
            f"  '~') workspace=\"$HOME\" ;;\n"
            f"  '~/'*) workspace=\"$HOME/${{workspace#~/}}\" ;;\n"
            f"esac\n"
            f'if [ -d "$workspace" ]; then\n'
            f"  created=0\n"
            f'elif [ -e "$workspace" ]; then\n'
            f'  rm -rf "$workspace"\n'
            f'  mkdir -p "$workspace"\n'
            f"  created=1\n"
            f"else\n"
            f'  mkdir -p "$workspace"\n'
            f"  created=1\n"
            f"fi\n"
            f'cd "$workspace"\n'
            f"printf '%s\\t%s\\t%s\\n' '__SYMPHONY_WORKSPACE__' \"$created\" \"$(pwd -P)\""
        )

        output, exit_code = await ssh_client.run(
            worker_host, script, timeout_s=config.hooks.timeout_ms / 1000
        )

        if exit_code != 0:
            raise WorkspaceError(
                f"Remote workspace creation failed on {worker_host}: exit {exit_code}, output: {output}"
            )

        return _parse_remote_workspace_output(output)


def _parse_remote_workspace_output(output: str) -> tuple[str, bool]:
    """Parse the remote workspace creation output."""
    for line in output.strip().split("\n"):
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0] == "__SYMPHONY_WORKSPACE__":
            created = parts[1] == "1"
            path = parts[2]
            if path:
                return path, created

    raise WorkspaceError(f"Invalid remote workspace output: {output}")


def _validate_local_workspace(workspace: str, workspace_root: str) -> None:
    """Validate that a local workspace path is safely under the root."""
    canonical_workspace = canonicalize(workspace)
    canonical_root = canonicalize(workspace_root)

    if canonical_workspace == canonical_root:
        raise WorkspaceError(f"Workspace path equals root: {canonical_workspace}")

    if not (canonical_workspace + "/").startswith(canonical_root + "/"):
        raise WorkspaceError(
            f"Workspace {canonical_workspace} is outside root {canonical_root}"
        )


async def _run_hook(
    command: str,
    workspace: str,
    identifier: str,
    hook_name: str,
    worker_host: str | None,
    timeout_ms: int,
) -> None:
    """Run a workspace lifecycle hook."""
    timeout_s = timeout_ms / 1000
    log_host = worker_host or "local"
    logger.info(
        "Running workspace hook hook=%s identifier=%s workspace=%s worker_host=%s",
        hook_name, identifier, workspace, log_host,
    )

    if worker_host is None:
        proc = await asyncio.create_subprocess_exec(
            "sh", "-lc", command,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise WorkspaceError(
                f"Workspace hook '{hook_name}' timed out after {timeout_ms}ms"
            )

        if proc.returncode != 0:
            output = stdout.decode("utf-8", errors="replace")[:2048] if stdout else ""
            raise WorkspaceError(
                f"Workspace hook '{hook_name}' failed with status {proc.returncode}: {output}"
            )
    else:
        full_command = f"cd {_shell_escape(workspace)} && {command}"
        output, exit_code = await ssh_client.run(worker_host, full_command, timeout_s=timeout_s)

        if exit_code != 0:
            raise WorkspaceError(
                f"Workspace hook '{hook_name}' failed on {worker_host} with status {exit_code}: {output[:2048]}"
            )


def _extract_identifier(issue: Issue | str | None) -> str:
    """Extract the issue identifier string."""
    if isinstance(issue, Issue):
        return issue.identifier or "issue"
    if isinstance(issue, str):
        return issue
    return "issue"


def _shell_escape(value: str) -> str:
    """Shell-escape a value using single quotes."""
    return "'" + value.replace("'", "'\"'\"'") + "'"
