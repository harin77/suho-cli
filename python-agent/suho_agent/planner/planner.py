"""Planner — converts natural language tasks into structured execution plans."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import structlog

from suho_agent.agent.state import Plan, PlanStep
from suho_agent.models.base import LLMProvider

log = structlog.get_logger(__name__)

PLANNER_SYSTEM_PROMPT = """You are SUHO Agent Planner. Your job is to create a structured execution plan for a development task.

Given a task, analyze it and create a step-by-step plan. Each step should:
- Be specific and actionable
- Reference the appropriate tool to use
- Indicate the risk level (SAFE, MODERATE, DANGEROUS, CRITICAL)

Return your plan as a JSON array:
```json
[
  {
    "index": 1,
    "description": "Step description",
    "tool": "tool.name",
    "rationale": "Why this step is needed",
    "risk_level": "SAFE"
  }
]
```

Available tools:
- filesystem.read_file, filesystem.write_file, filesystem.edit_file, filesystem.list_directory, filesystem.search_files
- terminal.execute (for running commands)
- git.status, git.diff, git.add, git.commit, git.push
- development.flutter_analyze, development.flutter_test, development.flutter_build
- development.cargo_check, development.cargo_test, development.cargo_build, development.cargo_clippy
- development.pytest_run, development.pip_install
- development.npm_install, development.npm_run, development.npm_test
- system.system_info, system.disk_usage, system.memory_usage

Keep plans focused and practical. Maximum 15 steps. Prefer SAFE read operations before MODERATE write operations."""


class Planner:
    """
    LLM-based planner.
    Converts natural language tasks into structured Plan objects.
    Supports dynamic replanning when observations change context.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def create_plan(
        self,
        task: str,
        context: dict[str, Any],
        working_directory: str,
        replan: bool = False,
        previous_observations: Optional[list[str]] = None,
    ) -> Plan:
        """Generate or update a plan for the given task."""
        messages = self._build_messages(
            task=task,
            context=context,
            working_directory=working_directory,
            replan=replan,
            previous_observations=previous_observations or [],
        )

        try:
            response = await self._llm.generate(messages=messages, temperature=0.1)
            steps = self._parse_plan(response.content)
            log.info("Plan created", steps=len(steps), replan=replan)
            return Plan(steps=steps)
        except Exception as e:
            log.warning("LLM planner failed, using fallback plan", error=str(e))
            return self._fallback_plan(task, working_directory)

    def _build_messages(
        self,
        task: str,
        context: dict,
        working_directory: str,
        replan: bool,
        previous_observations: list[str],
    ) -> list[dict]:
        user_content = f"Task: {task}\nWorking directory: {working_directory}"

        if replan and previous_observations:
            obs_text = "\n".join(f"- {o[:200]}" for o in previous_observations[:5])
            user_content += f"\n\nPrevious observations (replan based on these):\n{obs_text}"
            user_content += "\n\nCreate an updated plan based on what we've learned so far."

        return [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _parse_plan(self, content: str) -> list[PlanStep]:
        """Extract JSON plan from LLM response."""
        # Try to find JSON array
        json_patterns = [
            r"```json\s*(\[.*?\])\s*```",
            r"```\s*(\[.*?\])\s*```",
            r"(\[[\s\S]*?\])",
        ]

        for pattern in json_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                try:
                    raw_steps = json.loads(match.group(1))
                    return [
                        PlanStep(
                            index=s.get("index", i + 1),
                            description=s.get("description", "Unknown step"),
                            tool=s.get("tool"),
                            rationale=s.get("rationale"),
                            risk_level=s.get("risk_level", "SAFE"),
                        )
                        for i, s in enumerate(raw_steps)
                        if isinstance(s, dict)
                    ]
                except (json.JSONDecodeError, KeyError):
                    continue

        # Fallback: parse numbered list
        steps = []
        for i, line in enumerate(content.splitlines()):
            line = line.strip()
            if re.match(r"^\d+[\.\)]\s+", line):
                description = re.sub(r"^\d+[\.\)]\s+", "", line)
                steps.append(PlanStep(
                    index=i + 1,
                    description=description,
                    risk_level="SAFE",
                ))

        return steps

    def _fallback_plan(self, task: str, cwd: str) -> Plan:
        """Minimal fallback plan when LLM fails."""
        return Plan(steps=[
            PlanStep(index=1, description="Inspect current directory", tool="filesystem.list_directory", risk_level="SAFE"),
            PlanStep(index=2, description=f"Execute task: {task[:80]}", tool="terminal.execute", risk_level="MODERATE"),
            PlanStep(index=3, description="Verify results", tool="filesystem.list_directory", risk_level="SAFE"),
        ])
