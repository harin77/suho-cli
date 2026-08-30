"""IPC bridge — reads CliMessages from stdin, writes AgentMessages to stdout."""

from __future__ import annotations

import asyncio
import json
import sys
from io import TextIOWrapper
from typing import AsyncIterator, Optional

import structlog

from suho_agent.ipc.protocol import AgentMessage, CliMessage

log = structlog.get_logger(__name__)


class IPCBridge:
    """
    Bidirectional JSON bridge between Python agent and Rust CLI.

    - stdin: receives CliMessage (JSON lines from Rust)
    - stdout: sends AgentMessage (JSON lines to Rust)

    All messages are newline-terminated JSON objects.
    stdout is used EXCLUSIVELY for IPC — never for human-readable output.
    Human-readable output goes to stderr (which Rust inherits and may display).
    """

    def __init__(self, stdin: TextIOWrapper, stdout: TextIOWrapper) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._send_lock = asyncio.Lock()
        self._pending_permission: dict[str, asyncio.Future[CliMessage]] = {}
        self._pending_tool_result: dict[str, asyncio.Future[CliMessage]] = {}

    async def send(self, msg: AgentMessage) -> None:
        """Send a message to the Rust CLI."""
        async with self._send_lock:
            data = msg.model_dump(mode="json")
            raw_json = json.dumps(data, ensure_ascii=False)
            clean_json = raw_json.encode("utf-8", errors="replace").decode("utf-8")
            line = clean_json + "\n"
            self._stdout.write(line)
            self._stdout.flush()

    async def recv(self) -> Optional[CliMessage]:
        """Receive the next message from Rust CLI (blocking on stdin)."""
        try:
            loop = asyncio.get_running_loop()
            line = await loop.run_in_executor(None, self._stdin.readline)
        except Exception as e:
            log.error("stdin read error", error=str(e))
            return None

        if not line:
            return None  # EOF

        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
            from suho_agent.ipc.protocol import cli_message_adapter
            msg = cli_message_adapter.validate_python(data)
            log.debug("Received from Rust", type=data.get("type"))
            return msg
        except Exception as e:
            log.warning("Failed to parse CliMessage", error=str(e), line=line[:200])
            return None

    async def send_status(
        self,
        task_id: str,
        status: str,
        message: str,
        step: Optional[str] = None,
        progress: Optional[float] = None,
    ) -> None:
        """Convenience: send a status update."""
        from suho_agent.ipc.protocol import StatusUpdateMessage
        await self.send(StatusUpdateMessage(
            task_id=task_id,
            status=status,
            message=message,
            step=step,
            progress=progress,
        ))

    async def send_stream_chunk(self, task_id: str, content: str) -> None:
        """Convenience: send a streaming LLM chunk."""
        from suho_agent.ipc.protocol import StreamChunkMessage
        await self.send(StreamChunkMessage(task_id=task_id, content=content))

    async def send_tool_request(
        self,
        request_id: str,
        task_id: str,
        tool: str,
        args: dict,
        policy_level: str,
        policy_reasons: list[str],
        description: str,
    ) -> CliMessage:
        """
        Send a tool execution request to Rust and wait for the result.
        Rust will either return ToolResult or ToolDenied.
        """
        from suho_agent.ipc.protocol import ToolRequestMessage
        future: asyncio.Future[CliMessage] = asyncio.get_running_loop().create_future()
        self._pending_tool_result[request_id] = future

        await self.send(ToolRequestMessage(
            id=request_id,
            task_id=task_id,
            tool=tool,
            args=args,
            policy_level=policy_level,
            policy_reasons=policy_reasons,
            description=description,
        ))

        return await future

    async def send_permission_request(
        self,
        request_id: str,
        task_id: str,
        tool: str,
        description: str,
        command_preview: Optional[str],
        level: str,
        consequences: list[str],
    ) -> CliMessage:
        """
        Request explicit user permission via Rust TUI prompt.
        Waits for PermissionDecision from Rust.
        """
        from suho_agent.ipc.protocol import PermissionRequestMessage
        future: asyncio.Future[CliMessage] = asyncio.get_running_loop().create_future()
        self._pending_permission[request_id] = future

        await self.send(PermissionRequestMessage(
            id=request_id,
            task_id=task_id,
            tool=tool,
            description=description,
            command_preview=command_preview,
            level=level,
            consequences=consequences,
        ))

        return await future

    def dispatch_response(self, msg: CliMessage) -> bool:
        """
        Route an incoming CliMessage to its waiting future.
        Returns True if the message was dispatched, False if it should be handled by runtime.
        """
        msg_type = msg.type

        if msg_type == "tool_result" or msg_type == "tool_denied":
            msg_id = getattr(msg, "id", None)
            if msg_id and msg_id in self._pending_tool_result:
                future = self._pending_tool_result.pop(msg_id)
                if not future.done():
                    future.set_result(msg)
                return True

        if msg_type == "permission_decision":
            msg_id = getattr(msg, "id", None)
            if msg_id and msg_id in self._pending_permission:
                future = self._pending_permission.pop(msg_id)
                if not future.done():
                    future.set_result(msg)
                return True

        return False
