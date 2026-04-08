"""SSH command execution for remote worker hosts.

Ports the Elixir SSH module using subprocess.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)


class SSHError(Exception):
    """SSH execution error."""


def parse_target(target: str) -> dict[str, str | None]:
    """Parse a host target into destination and optional port.

    Supports "host:port" shorthand (e.g., "localhost:2222").
    """
    trimmed = target.strip()

    match = re.match(r"^(.*):(\d+)$", trimmed)
    if match:
        destination, port = match.group(1), match.group(2)
        if _valid_port_destination(destination):
            return {"destination": destination, "port": port}

    return {"destination": trimmed, "port": None}


def _valid_port_destination(destination: str) -> bool:
    """Check if a destination is valid for port extraction."""
    if not destination:
        return False
    if ":" not in destination:
        return True
    # IPv6 literals with brackets are OK
    return "[" in destination and "]" in destination


def shell_escape(value: str) -> str:
    """Shell-escape a value using single quotes."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_shell_command(command: str) -> str:
    """Wrap a command for remote shell execution."""
    return "bash -lc " + shell_escape(command)


def _ssh_args(host: str, command: str) -> list[str]:
    """Build SSH command arguments."""
    target = parse_target(host)
    args: list[str] = []

    # Optional SSH config file
    config_path = os.environ.get("SYMPHONY_SSH_CONFIG", "")
    if config_path:
        args.extend(["-F", config_path])

    args.append("-T")

    if target["port"]:
        args.extend(["-p", target["port"]])

    args.append(target["destination"] or host)
    args.append(remote_shell_command(command))

    return args


async def run(
    host: str,
    command: str,
    timeout_s: float | None = None,
) -> tuple[str, int]:
    """Execute a command on a remote host via SSH.

    Returns (output, exit_code).
    Raises SSHError if SSH executable is not found.
    """
    ssh_path = shutil.which("ssh")
    if ssh_path is None:
        raise SSHError("ssh executable not found")

    args = _ssh_args(host, command)
    proc = await asyncio.create_subprocess_exec(
        ssh_path,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SSHError(f"SSH command timed out after {timeout_s}s")

    return stdout.decode("utf-8", errors="replace"), proc.returncode or 0


async def start_subprocess(
    host: str,
    command: str,
) -> asyncio.subprocess.Process:
    """Start a long-running SSH subprocess for streaming communication.

    Returns the Process object for the caller to manage.
    Raises SSHError if SSH executable is not found.
    """
    ssh_path = shutil.which("ssh")
    if ssh_path is None:
        raise SSHError("ssh executable not found")

    args = _ssh_args(host, command)
    proc = await asyncio.create_subprocess_exec(
        ssh_path,
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    return proc
