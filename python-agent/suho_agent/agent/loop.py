"""AgentLoop — the core UNDERSTAND → PLAN → EXECUTE → OBSERVE → VERIFY loop."""

from __future__ import annotations

import asyncio
import time
from typing import Optional
from uuid import uuid4

import structlog

from suho_agent.agent.observation import Observation, ObservationAnalyzer
from suho_agent.agent.state import Plan, PlanStep, TaskState, TaskStatus, ToolCall
from suho_agent.config import AgentConfig
from suho_agent.ipc.bridge import IPCBridge

log = structlog.get_logger(__name__)


class AgentLoop:
    """
    The agent execution loop.

    Separation axiom:
      AgentLoop ≠ LLM
      AgentLoop ≠ Tools
      AgentLoop uses both via injected components.

    Loop:
      understand → plan → select_action → validate → execute → observe → verify → replan?
    """

    def __init__(
        self,
        config: AgentConfig,
        bridge: IPCBridge,
        state: TaskState,
    ) -> None:
        self.config = config
        self.bridge = bridge
        self.state = state
        self._cancelled = False
        self._observer = ObservationAnalyzer()

        # Lazy-initialized components
        self._llm: Optional[object] = None
        self._planner: Optional[object] = None
        self._tool_router: Optional[object] = None
        self._verifier: Optional[object] = None
        self._context_mgr: Optional[object] = None
        self._memory: Optional[object] = None

    def cancel(self) -> None:
        """Signal cancellation from external caller."""
        self._cancelled = True

    async def run(self) -> None:
        """Execute the full agent loop."""
        task_id = self.state.task_id

        await self._emit_status(TaskStatus.PENDING, "Initializing...")
        await self._init_components()

        # ── Plan-only mode ─────────────────────────────────────────────────
        if self.state.mode == "plan_only":
            await self._run_plan_only()
            return

        # ── Ask-only mode ──────────────────────────────────────────────────
        if self.state.mode == "ask_only":
            await self._run_ask_only()
            return

        # ── Main agent loop ────────────────────────────────────────────────
        await self._emit_status(TaskStatus.PLANNING, "Analyzing task and creating plan...")

        try:
            plan = await self._create_plan()
            self.state.plan = plan
        except Exception as e:
            log.exception("Planner failed")
            await self._fail(f"Planning failed: {e}")
            return

        await self._send_plan_preview(plan)

        # Execute loop
        while not self._should_stop():
            self.state.iteration_count += 1

            await self._emit_status(
                TaskStatus.EXECUTING,
                f"Iteration {self.state.iteration_count}",
            )

            # Select next action via LLM
            try:
                action = await self._select_action()
            except Exception as e:
                log.exception("Action selection failed")
                await self._fail(f"Failed to select action: {e}")
                return

            if action is None:
                # LLM says task is complete
                break

            reasoning = getattr(action, "reasoning", None)
            if reasoning:
                from suho_agent.ipc.protocol import ThinkingMessage
                await self.bridge.send(ThinkingMessage(
                    task_id=self.state.task_id,
                    content=reasoning,
                ))

            tool_name = action.tool if hasattr(action, "tool") else action.get("tool", "")
            tool_args = action.args if hasattr(action, "args") else action.get("args", {})
            description = (action.content if hasattr(action, "content") else action.get("description")) or f"Execute {tool_name}"

            if tool_name in ("__complete__", "complete"):
                break

            observation = await self._execute_action(tool_name, tool_args, description)

            if observation is None:
                # Denied or cancelled
                if self._cancelled:
                    await self._emit_status(TaskStatus.CANCELLED, "Cancelled by user")
                    return
                continue

            # Feed observation back into state
            self.state.add_observation(observation.to_llm_context())
            self._update_state_from_observation(observation)

            # Check if we should replan
            if observation.requires_followup and not observation.success:
                if self.state.retry_count < self.state.max_retries:
                    self.state.retry_count += 1
                    log.info("Replanning due to failure", retry=self.state.retry_count)
                    try:
                        self.state.plan = await self._create_plan(replan=True)
                    except Exception as e:
                        log.warning("Replan failed", error=str(e))

        # ── Verification ──────────────────────────────────────────────────
        if not self._cancelled and self.state.files_changed:
            await self._emit_status(TaskStatus.VERIFYING, "Verifying changes...")
            await self._verify()

        # ── Completion ────────────────────────────────────────────────────
        if not self._cancelled:
            await self._complete()

    # ─── Phase implementations ────────────────────────────────────────────────

    async def _run_plan_only(self) -> None:
        """Generate and display a plan without executing."""
        await self._emit_status(TaskStatus.PLANNING, "Generating plan...")
        plan = await self._create_plan()
        self.state.plan = plan

        from suho_agent.ipc.protocol import PlanGeneratedMessage
        await self.bridge.send(PlanGeneratedMessage(
            task_id=self.state.task_id,
            steps=[
                {
                    "index": s.index,
                    "description": s.description,
                    "tool": s.tool,
                    "rationale": s.rationale,
                    "risk_level": s.risk_level,
                }
                for s in plan.steps
            ],
        ))

    async def _run_ask_only(self) -> None:
        """Pure LLM Q&A — no tool use."""
        from suho_agent.ipc.protocol import StreamChunkMessage, TaskCompleteMessage

        await self._emit_status(TaskStatus.EXECUTING, "Thinking...")

        llm = await self._get_llm()
        context = self._build_simple_context()

        full_response = ""
        async for chunk in llm.stream(messages=context):
            await self.bridge.send(StreamChunkMessage(
                task_id=self.state.task_id,
                content=chunk,
            ))
            full_response += chunk

        await self.bridge.send(TaskCompleteMessage(
            task_id=self.state.task_id,
            summary=full_response,
            tool_calls=0,
            iterations=1,
            token_usage=self.state.token_usage.model_dump(),
            duration_ms=self.state.duration_ms,
        ))

    async def _create_plan(self, replan: bool = False) -> Plan:
        """Ask the Planner to generate or update the execution plan."""
        planner = await self._get_planner()
        context = self._build_planning_context(replan=replan)

        plan_data = await planner.create_plan(
            task=self.state.user_request,
            context=context,
            working_directory=self.state.working_directory,
            replan=replan,
            previous_observations=self.state.observations[-10:] if replan else [],
        )

        return plan_data

    async def _select_action(self) -> Optional[dict]:
        """Use LLM to select the next tool action based on current state."""
        llm = await self._get_llm()
        tool_router = await self._get_tool_router()
        context_mgr = await self._get_context_mgr()

        # Build context for LLM
        messages = await context_mgr.build_action_context(
            state=self.state,
            available_tools=tool_router.get_tool_schemas(),
        )

        # Get tool call from LLM
        response = await llm.tool_call(
            messages=messages,
            tools=tool_router.get_tool_schemas(),
        )

        if response is None:
            return None

        return response

    async def _execute_action(
        self,
        tool_name: str,
        tool_args: dict,
        description: str,
    ) -> Optional[Observation]:
        """
        Send tool request to Rust SecurityGate and await result.
        Returns None if denied or cancelled.
        """
        from suho_agent.ipc.protocol import ToolStartedMessage
        from suho_agent.policy.engine import PolicyEngine

        # Notify UI
        await self.bridge.send(ToolStartedMessage(
            task_id=self.state.task_id,
            tool=tool_name,
            description=description,
        ))

        # Run tool args through Policy Engine (advisory — Rust has final say)
        policy_engine = PolicyEngine()
        policy_result = await policy_engine.evaluate(
            tool=tool_name,
            args=tool_args,
            cwd=self.state.working_directory,
        )

        request_id = str(uuid4())
        start_time = time.monotonic()

        # Send to Rust — Rust will execute after SecurityGate check
        result_msg = await self.bridge.send_tool_request(
            request_id=request_id,
            task_id=self.state.task_id,
            tool=tool_name,
            args=tool_args,
            policy_level=policy_result.level,
            policy_reasons=policy_result.reasons,
            description=description,
        )

        duration_ms = int((time.monotonic() - start_time) * 1000)

        if result_msg.type == "tool_denied":
            log.info("Tool denied by security gate", tool=tool_name, reason=result_msg.reason)
            self.state.add_observation(f"Tool {tool_name} was denied: {result_msg.reason}")
            return None

        # Build observation from result
        obs = self._observer.analyze(tool_name, tool_args, result_msg)

        # Track tool call
        self.state.add_tool_call(ToolCall(
            tool=tool_name,
            args=tool_args,
            result_success=obs.success,
            result_summary=obs.summary or "",
            duration_ms=obs.duration_ms,
        ))

        return obs

    async def _verify(self) -> None:
        """Run verification suite appropriate for detected project type."""
        verifier = await self._get_verifier()
        results = await verifier.verify(
            working_directory=self.state.working_directory,
            files_changed=[f.path for f in self.state.files_changed],
        )

        for r in results:
            self.state.add_observation(r.to_llm_context() if hasattr(r, "to_llm_context") else str(r))

    async def _complete(self) -> None:
        """Send task completion message."""
        from suho_agent.ipc.protocol import TaskCompleteMessage

        # Generate summary using LLM if needed
        summary = self._generate_summary()

        await self.bridge.send(TaskCompleteMessage(
            task_id=self.state.task_id,
            summary=summary,
            files_changed=[
                {"path": f.path, "operation": f.operation}
                for f in self.state.files_changed
            ],
            tool_calls=self.state.tool_call_count,
            iterations=self.state.iteration_count,
            token_usage=self.state.token_usage.model_dump(),
            duration_ms=self.state.duration_ms,
        ))

        # Persist to memory
        if self.config.memory.enabled:
            await self._save_to_memory()

    async def _fail(self, error: str, suggestion: Optional[str] = None) -> None:
        """Send task failure message."""
        from suho_agent.ipc.protocol import TaskFailedMessage
        self.state.status = TaskStatus.FAILED
        await self.bridge.send(TaskFailedMessage(
            task_id=self.state.task_id,
            error=error,
            recoverable=False,
            suggestion=suggestion,
        ))

    # ─── Helper methods ───────────────────────────────────────────────────────

    def _should_stop(self) -> bool:
        return (
            self._cancelled
            or self.state.is_at_limit
            or self.state.status in (TaskStatus.FAILED, TaskStatus.COMPLETED, TaskStatus.CANCELLED)
        )

    async def _emit_status(self, status: TaskStatus, message: str, step: Optional[str] = None) -> None:
        self.state.status = status
        await self.bridge.send_status(
            task_id=self.state.task_id,
            status=status.value,
            message=message,
            step=step,
        )

    def _update_state_from_observation(self, obs: Observation) -> None:
        for path in obs.files_mentioned:
            if any(kw in obs.tool.lower() for kw in ["write", "edit", "create", "delete"]):
                self.state.record_file_change(path, "modified")
        if obs.errors_found:
            for e in obs.errors_found[:3]:
                self.state.add_error(e)

    def _generate_summary(self) -> str:
        summary_parts = [f"Successfully completed: {self.state.user_request}"]
        if self.state.files_changed:
            summary_parts.append(
                f"Updated {len(self.state.files_changed)} file(s): "
                + ", ".join(f.path for f in self.state.files_changed[:5])
            )
        summary_parts.append(
            f"Executed in {self.state.iteration_count} iteration(s) using {self.state.tool_call_count} tool call(s)."
        )
        return "\n".join(summary_parts)

    def _build_simple_context(self) -> list[dict]:
        return [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self.state.user_request},
        ]

    def _build_planning_context(self, replan: bool = False) -> dict:
        return {
            "task": self.state.user_request,
            "cwd": self.state.working_directory,
            "replan": replan,
            "observations": self.state.observations,
        }

    def _system_prompt(self) -> str:
        return (
            "You are SUHO Agent, a capable AI assistant that helps with development tasks. "
            "You have access to tools for reading files, running commands, and editing code. "
            "Be precise, methodical, and verify your work."
        )

    async def _send_plan_preview(self, plan: Plan) -> None:
        if not plan.steps:
            return
        from suho_agent.ipc.protocol import InfoMessage
        preview = "\n".join(f"  {i+1}. {s.description}" for i, s in enumerate(plan.steps[:10]))
        await self.bridge.send(InfoMessage(
            task_id=self.state.task_id,
            message=f"Plan ({len(plan.steps)} steps):\n{preview}",
        ))

    async def _save_to_memory(self) -> None:
        try:
            from suho_agent.memory.store import MemoryStore
            store = MemoryStore(self.config.get_db_path())
            await store.initialize()
            await store.save_task_state(self.state)
        except Exception as e:
            log.warning("Failed to save to memory", error=str(e))

    # ─── Lazy component initialization ───────────────────────────────────────

    async def _init_components(self) -> None:
        """Initialize all components in parallel."""
        await asyncio.gather(
            self._get_llm(),
            self._get_planner(),
            self._get_tool_router(),
            self._get_context_mgr(),
        )
        if self.config.memory.enabled:
            await self._get_memory()

    async def _get_llm(self):
        if self._llm is None:
            from suho_agent.models.router import ModelRouter
            router = ModelRouter(self.config)
            self._llm = await router.get_provider()
        return self._llm

    async def _get_planner(self):
        if self._planner is None:
            from suho_agent.planner.planner import Planner
            llm = await self._get_llm()
            self._planner = Planner(llm=llm)
        return self._planner

    async def _get_tool_router(self):
        if self._tool_router is None:
            from suho_agent.tools.router import ToolRouter
            self._tool_router = ToolRouter()
        return self._tool_router

    async def _get_verifier(self):
        if self._verifier is None:
            from suho_agent.verification.verifier import VerificationSystem
            self._verifier = VerificationSystem(bridge=self.bridge, state=self.state)
        return self._verifier

    async def _get_context_mgr(self):
        if self._context_mgr is None:
            from suho_agent.context.manager import ContextManager
            self._context_mgr = ContextManager(
                max_tokens=self.config.model.max_context_tokens,
            )
        return self._context_mgr

    async def _get_memory(self):
        if self._memory is None:
            from suho_agent.memory.store import MemoryStore
            self._memory = MemoryStore(self.config.get_db_path())
            await self._memory.initialize()
        return self._memory
