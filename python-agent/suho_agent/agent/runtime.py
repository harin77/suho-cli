"""AgentRuntime — the top-level orchestrator that manages the agent lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog

from suho_agent.config import AgentConfig
from suho_agent.ipc.bridge import IPCBridge
from suho_agent.ipc.protocol import (
    CliMessage,
    TaskRequestMessage,
    ListToolsMessage,
    ListModelsMessage,
    HistoryMessage,
    StatusMessage,
    MemoryListMessage,
    MemorySearchMessage,
    MemoryDeleteMessage,
    MemoryClearMessage,
    SessionListMessage,
    ResumeMessage,
    CancelMessage,
)
from suho_agent.agent.state import TaskState, TaskStatus
from suho_agent.agent.loop import AgentLoop

log = structlog.get_logger(__name__)


class AgentRuntime:
    """
    Top-level agent runtime. Responsibilities:
    - Read messages from IPC bridge
    - Dispatch task requests to AgentLoop
    - Handle non-task queries (tools list, memory, etc.)
    - Manage cancellation and shutdown

    Separation axiom: AgentRuntime is NOT the LLM. It is NOT the tools.
    It is the orchestrator that connects them.
    """

    def __init__(self, config: AgentConfig, bridge: IPCBridge) -> None:
        self.config = config
        self.bridge = bridge
        self._shutdown_requested = False
        self._active_loop: Optional[AgentLoop] = None
        self._start_time = datetime.now(timezone.utc)

    def request_shutdown(self) -> None:
        """Request graceful shutdown (called from signal handler)."""
        log.info("Shutdown requested")
        self._shutdown_requested = True
        if self._active_loop:
            self._active_loop.cancel()

    async def run(self) -> None:
        """Main event loop — read messages and dispatch."""
        log.info("AgentRuntime ready, waiting for messages")

        while not self._shutdown_requested:
            msg = await self.bridge.recv()
            if msg is None:
                log.info("stdin closed, shutting down")
                break

            # Check if it's a response to a pending request
            if self.bridge.dispatch_response(msg):
                continue

            # Dispatch to appropriate handler
            await self._dispatch(msg)

        log.info("AgentRuntime exiting")

    async def _dispatch(self, msg: CliMessage) -> None:
        """Route incoming message to the correct handler."""
        # Always reload config from disk
        self.config = AgentConfig.load()

        match msg:
            case TaskRequestMessage():
                await self._handle_task(msg)

            case ResumeMessage():
                await self._handle_resume(msg)

            case CancelMessage():
                await self._handle_cancel(msg)

            case ListToolsMessage():
                await self._handle_list_tools(msg)

            case ListModelsMessage():
                await self._handle_list_models(msg)

            case HistoryMessage():
                await self._handle_history(msg)

            case StatusMessage():
                await self._handle_status(msg)

            case MemoryListMessage() | MemorySearchMessage() | MemoryDeleteMessage() | MemoryClearMessage():
                await self._handle_memory(msg)

            case SessionListMessage():
                await self._handle_session_list(msg)

            case _:
                log.warning("Unhandled message type", type=getattr(msg, "type", "unknown"))

    async def _handle_task(self, msg: TaskRequestMessage) -> None:
        """Run a task through the AgentLoop."""
        log.info("Starting task", task_id=msg.id, request=msg.request[:80])

        state = TaskState(
            task_id=msg.id,
            user_request=msg.request,
            working_directory=msg.cwd,
            mode=msg.mode,
            max_iterations=msg.max_iterations,
            max_tool_calls=self.config.agent.max_tool_calls,
            max_retries=self.config.agent.max_retries,
        )

        loop = AgentLoop(
            config=self.config,
            bridge=self.bridge,
            state=state,
        )
        self._active_loop = loop

        try:
            await asyncio.wait_for(
                loop.run(),
                timeout=float(msg.timeout_secs),
            )
        except asyncio.TimeoutError:
            log.warning("Task timed out", task_id=msg.id, timeout=msg.timeout_secs)
            from suho_agent.ipc.protocol import TaskFailedMessage
            await self.bridge.send(TaskFailedMessage(
                task_id=msg.id,
                error=f"Task timed out after {msg.timeout_secs} seconds",
                recoverable=False,
            ))
        except asyncio.CancelledError:
            log.info("Task cancelled", task_id=msg.id)
        except Exception as e:
            log.exception("Unhandled error in AgentLoop", task_id=msg.id)
            from suho_agent.ipc.protocol import TaskFailedMessage
            await self.bridge.send(TaskFailedMessage(
                task_id=msg.id,
                error=f"Internal agent error: {e}",
                recoverable=False,
            ))
        finally:
            self._active_loop = None

    async def _handle_resume(self, msg: ResumeMessage) -> None:
        """Resume a previous session from SQLite."""
        from suho_agent.memory.store import MemoryStore
        from suho_agent.ipc.protocol import InfoMessage, TaskFailedMessage

        if not self.config.memory.enabled:
            await self.bridge.send(InfoMessage(
                task_id=msg.id or "resume",
                message="Memory is disabled. Cannot resume sessions.",
            ))
            return

        store = MemoryStore(self.config.get_db_path())
        await store.initialize()

        task_id = msg.id
        if not task_id:
            # Get most recent incomplete task
            task_id = await store.get_most_recent_task_id()

        if not task_id:
            await self.bridge.send(InfoMessage(
                task_id="resume",
                message="No previous session found to resume.",
            ))
            return

        state = await store.load_task_state(task_id)
        if not state:
            await self.bridge.send(InfoMessage(
                task_id=task_id,
                message=f"Session {task_id} not found.",
            ))
            return

        log.info("Resuming task", task_id=task_id)
        loop = AgentLoop(config=self.config, bridge=self.bridge, state=state)
        self._active_loop = loop

        try:
            await loop.run()
        finally:
            self._active_loop = None

    async def _handle_cancel(self, msg: CancelMessage) -> None:
        if self._active_loop:
            self._active_loop.cancel()
        log.info("Task cancelled by user", task_id=msg.task_id)

    async def _handle_list_tools(self, msg: ListToolsMessage) -> None:
        from suho_agent.tools.router import ToolRouter
        from suho_agent.ipc.protocol import QueryResponseMessage

        router = ToolRouter()
        tools = await router.list_tools(verbose=msg.verbose, category=msg.category)

        await self.bridge.send(QueryResponseMessage(
            id=getattr(msg, "id", "list_tools"),
            data={"tools": [t.model_dump() for t in tools]},
        ))

    async def _handle_list_models(self, msg: ListModelsMessage) -> None:
        from suho_agent.models.router import ModelRouter
        from suho_agent.ipc.protocol import QueryResponseMessage

        router = ModelRouter(self.config)
        models = await router.list_available_models()

        await self.bridge.send(QueryResponseMessage(
            id="list_models",
            data={"models": [m.model_dump() for m in models]},
        ))

    async def _handle_history(self, msg: HistoryMessage) -> None:
        from suho_agent.memory.store import MemoryStore
        from suho_agent.ipc.protocol import QueryResponseMessage

        store = MemoryStore(self.config.get_db_path())
        await store.initialize()
        entries = await store.get_task_history(limit=msg.limit)

        await self.bridge.send(QueryResponseMessage(
            id="history",
            data={"entries": [e.model_dump(mode="json") for e in entries]},
        ))

    async def _handle_status(self, msg: StatusMessage) -> None:
        from suho_agent.memory.store import MemoryStore
        from suho_agent.ipc.protocol import QueryResponseMessage

        uptime = int((datetime.now(timezone.utc) - self._start_time).total_seconds())

        await self.bridge.send(QueryResponseMessage(
            id="status",
            data={
                "active_task": self._active_loop.state.task_id if self._active_loop else None,
                "model": self.config.model.model,
                "provider": self.config.model.provider,
                "memory_enabled": self.config.memory.enabled,
                "uptime_secs": uptime,
            },
        ))

    async def _handle_memory(self, msg: CliMessage) -> None:
        from suho_agent.memory.store import MemoryStore
        from suho_agent.ipc.protocol import QueryResponseMessage, MemoryListMessage, MemorySearchMessage, MemoryDeleteMessage, MemoryClearMessage

        store = MemoryStore(self.config.get_db_path())
        await store.initialize()

        match msg:
            case MemoryListMessage(limit=limit):
                entries = await store.list_memories(limit=limit)
                data = {"memories": [e.model_dump(mode="json") for e in entries]}

            case MemorySearchMessage(query=query):
                entries = await store.search_memories(query)
                data = {"memories": [e.model_dump(mode="json") for e in entries]}

            case MemoryDeleteMessage(id=mid):
                await store.delete_memory(mid)
                data = {"deleted": mid}

            case MemoryClearMessage():
                await store.clear_memories()
                data = {"cleared": True}

            case _:
                data = {}

        await self.bridge.send(QueryResponseMessage(id="memory", data=data))

    async def _handle_session_list(self, msg: SessionListMessage) -> None:
        from suho_agent.memory.store import MemoryStore
        from suho_agent.ipc.protocol import QueryResponseMessage

        store = MemoryStore(self.config.get_db_path())
        await store.initialize()
        sessions = await store.get_task_history(limit=msg.limit)

        await self.bridge.send(QueryResponseMessage(
            id="sessions",
            data={"sessions": [s.model_dump(mode="json") for s in sessions]},
        ))
