"""Context Manager — token-aware context assembly for LLM prompts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from suho_agent.agent.state import TaskState

log = structlog.get_logger(__name__)

ACTION_SYSTEM_PROMPT = """You are SUHO Agent, a powerful autonomous AI assistant for developers.

Your role: understand the task, use tools to accomplish it, and verify your work.

Rules:
- Use tools systematically. Read before you write.
- Never blindly overwrite files. Prefer patch-based edits.
- After making changes, run verification tools.
- If a tool fails, diagnose the error before retrying.
- When the task is complete, respond with {"tool": "__complete__", "args": {}}

Always respond with a tool call JSON:
{"tool": "tool.name", "args": {"key": "value"}}

Or to complete:
{"tool": "__complete__", "args": {}}"""


class ContextManager:
    """
    Assembles LLM context from task state.

    Key responsibilities:
    - Token budgeting (don't exceed model context)
    - Prioritizing relevant information
    - Context compression for long conversations
    """

    def __init__(self, max_tokens: int = 8192) -> None:
        self.max_tokens = max_tokens
        # Reserve tokens for system prompt and response
        self._reserved_tokens = 2048

    async def build_action_context(
        self,
        state: "TaskState",
        available_tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build messages for the action-selection LLM call."""
        messages: list[dict[str, Any]] = []

        # System prompt
        messages.append({"role": "system", "content": self._action_system_prompt(state, available_tools)})

        # Conversation history (most recent, within token budget)
        budget = self.max_tokens - self._reserved_tokens
        history = self._select_history(state.conversation_history, budget)
        messages.extend(history)

        # Current task context
        if not state.conversation_history:
            messages.append({
                "role": "user",
                "content": self._build_initial_context(state),
            })

        return messages

    def _action_system_prompt(self, state: "TaskState", tools: list[dict]) -> str:
        tool_names = [t.get("name", "") for t in tools[:20]]
        tool_list = ", ".join(tool_names)

        context_parts = [
            ACTION_SYSTEM_PROMPT,
            f"\nCurrent task: {state.user_request}",
            f"Working directory: {state.working_directory}",
            f"Iteration: {state.iteration_count}/{state.max_iterations}",
            f"Tool calls used: {state.tool_call_count}/{state.max_tool_calls}",
        ]

        if state.plan and state.plan.current_step:
            context_parts.append(f"Current plan step: {state.plan.current_step.description}")

        if state.observations:
            recent = state.observations[-3:]
            obs_text = "\n".join(f"- {o[:300]}" for o in recent)
            context_parts.append(f"\nRecent observations:\n{obs_text}")

        if state.errors:
            recent_errors = state.errors[-3:]
            err_text = "\n".join(f"- {e[:200]}" for e in recent_errors)
            context_parts.append(f"\nRecent errors:\n{err_text}")

        context_parts.append(f"\nAvailable tools: {tool_list}")

        return "\n".join(context_parts)

    def _build_initial_context(self, state: "TaskState") -> str:
        parts = [f"Please help me: {state.user_request}"]

        if state.plan and state.plan.steps:
            plan_text = "\n".join(
                f"{i+1}. {s.description}"
                for i, s in enumerate(state.plan.steps[:10])
            )
            parts.append(f"\nPlan:\n{plan_text}")
            parts.append("\nBegin executing the plan. Start with step 1.")

        return "\n".join(parts)

    def _select_history(
        self,
        history: list[dict[str, Any]],
        token_budget: int,
    ) -> list[dict[str, Any]]:
        """Select the most recent history entries that fit within token budget."""
        if not history:
            return []

        # Simple estimation: 1 token ≈ 4 chars
        selected = []
        used_tokens = 0

        for msg in reversed(history):
            content = str(msg.get("content", ""))
            tokens = len(content) // 4
            if used_tokens + tokens > token_budget:
                break
            selected.insert(0, msg)
            used_tokens += tokens

        return selected
