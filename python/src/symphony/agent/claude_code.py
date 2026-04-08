"""Claude Code subprocess management.

Replaces the Elixir Codex AppServer (JSON-RPC 2.0 protocol over stdio).
Claude Code uses a simpler model: one subprocess invocation per turn
using `claude --print --output-format json`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from symphony.config.config import settings
from symphony.models.issue import Issue
from symphony.ssh import client as ssh_client

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    """Result from a single Claude Code turn."""

    success: bool = True
    output: str = ""
    exit_code: int = 0
    session_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    turn_number: int = 0
    error: str | None = None
    raw_json: dict = field(default_factory=dict)  # type: ignore[type-arg]


UpdateCallback = Callable[[dict], None]  # type: ignore[type-arg]


class ClaudeCodeSession:
    """Manages Claude Code CLI subprocess invocations for an issue."""

    def __init__(
        self,
        workspace: str,
        worker_host: str | None = None,
    ):
        self.workspace = workspace
        self.worker_host = worker_host
        self._process: asyncio.subprocess.Process | None = None
        self._turn_count = 0

    async def run_turn(
        self,
        prompt: str,
        issue: Issue,
        on_update: UpdateCallback | None = None,
    ) -> TurnResult:
        """Run a single Claude Code turn as a subprocess.

        Args:
            prompt: The prompt to send to Claude Code.
            issue: The issue being worked on (for session ID generation).
            on_update: Optional callback for progress updates.

        Returns:
            TurnResult with output, token usage, and status.
        """
        self._turn_count += 1
        config = settings().claude_code
        turn_timeout_s = config.turn_timeout_ms / 1000
        session_id = f"{issue.id or 'unknown'}-{self._turn_count}-{int(time.time())}"

        if on_update:
            on_update({
                "event": "session_started",
                "session_id": session_id,
                "turn_number": self._turn_count,
            })

        try:
            if self.worker_host:
                stdout, stderr, exit_code = await self._run_remote(prompt, turn_timeout_s)
            else:
                stdout, stderr, exit_code = await self._run_local(prompt, turn_timeout_s)

            result = self._parse_output(stdout, stderr, exit_code, session_id)

            if on_update:
                on_update({
                    "event": "turn_completed" if result.success else "turn_failed",
                    "session_id": session_id,
                    "turn_number": self._turn_count,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "total_tokens": result.total_tokens,
                })

            return result

        except asyncio.TimeoutError:
            await self.cancel()
            error_msg = f"Claude Code turn timed out after {config.turn_timeout_ms}ms"
            logger.error(error_msg)

            if on_update:
                on_update({
                    "event": "turn_failed",
                    "session_id": session_id,
                    "turn_number": self._turn_count,
                    "error": error_msg,
                })

            return TurnResult(
                success=False,
                session_id=session_id,
                turn_number=self._turn_count,
                error=error_msg,
            )

        except Exception as e:
            logger.exception("Claude Code turn failed")

            if on_update:
                on_update({
                    "event": "turn_failed",
                    "session_id": session_id,
                    "turn_number": self._turn_count,
                    "error": str(e),
                })

            return TurnResult(
                success=False,
                session_id=session_id,
                turn_number=self._turn_count,
                error=str(e),
            )

    async def _run_local(
        self, prompt: str, timeout_s: float
    ) -> tuple[bytes, bytes, int]:
        """Run Claude Code locally as a subprocess."""
        cmd = self._build_command()
        logger.info("Running Claude Code: %s", " ".join(cmd))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.workspace,
        )

        stdout, stderr = await asyncio.wait_for(
            self._process.communicate(input=prompt.encode("utf-8")),
            timeout=timeout_s,
        )

        return stdout, stderr, self._process.returncode or 0

    async def _run_remote(
        self, prompt: str, timeout_s: float
    ) -> tuple[bytes, bytes, int]:
        """Run Claude Code on a remote host via SSH."""
        cmd = self._build_command()
        cmd_str = " ".join(cmd)

        # Pipe prompt via stdin over SSH
        escaped_prompt = ssh_client.shell_escape(prompt)
        remote_cmd = f"cd {ssh_client.shell_escape(self.workspace)} && echo {escaped_prompt} | {cmd_str}"

        output, exit_code = await ssh_client.run(
            self.worker_host,  # type: ignore[arg-type]
            remote_cmd,
            timeout_s=timeout_s,
        )

        return output.encode("utf-8"), b"", exit_code

    def _build_command(self) -> list[str]:
        """Build the Claude Code CLI command."""
        config = settings().claude_code
        cmd = [config.command, "--print", "--output-format", "json"]

        if config.model:
            cmd.extend(["--model", config.model])
        if config.max_turns:
            cmd.extend(["--max-turns", str(config.max_turns)])

        cmd.extend(["--permission-mode", config.permission_mode])

        if config.mcp_config:
            cmd.extend(["--mcp-config", config.mcp_config])

        for tool in config.allowed_tools:
            cmd.extend(["--allowedTools", tool])

        # Read prompt from stdin
        cmd.extend(["-p", "-"])

        return cmd

    def _parse_output(
        self,
        stdout: bytes,
        stderr: bytes,
        exit_code: int,
        session_id: str,
    ) -> TurnResult:
        """Parse Claude Code JSON output into a TurnResult."""
        output_str = stdout.decode("utf-8", errors="replace")

        result = TurnResult(
            success=exit_code == 0,
            output=output_str,
            exit_code=exit_code,
            session_id=session_id,
            turn_number=self._turn_count,
        )

        if stderr:
            stderr_str = stderr.decode("utf-8", errors="replace")
            if stderr_str.strip():
                logger.warning("Claude Code stderr: %s", stderr_str[:2048])

        # Try to parse JSON output for token usage
        try:
            data = json.loads(output_str)
            result.raw_json = data

            # Extract token usage from Claude Code JSON output
            usage = data.get("usage", {})
            if usage:
                result.input_tokens = usage.get("input_tokens", 0)
                result.output_tokens = usage.get("output_tokens", 0)
                result.total_tokens = (
                    result.input_tokens + result.output_tokens
                )

            # Check for error in response
            if data.get("is_error"):
                result.success = False
                result.error = data.get("error", "Unknown error")

        except (json.JSONDecodeError, TypeError):
            # Output may not be JSON (e.g., plain text mode or error)
            if exit_code != 0:
                result.error = output_str[:1000]

        return result

    async def cancel(self) -> None:
        """Cancel any running Claude Code subprocess."""
        if self._process is not None and self._process.returncode is None:
            logger.info("Cancelling Claude Code subprocess")
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

    @property
    def turn_count(self) -> int:
        return self._turn_count
