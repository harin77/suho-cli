# SUHO Agent — Architecture Documentation

## Core Design Principles

1. **LLM != Agent**: The LLM is the reasoning component; the Agent Runtime is the software system managing state, tools, context, and execution loops.
2. **Rust CLI / Python Agent Split**:
   - **Rust**: CLI frontend, clap parsing, TUI rendering, SecurityGate (final authority), Process Executor, process isolation.
   - **Python**: Agent Loop, Planner, Context Manager, LLM Router, Policy Engine (advisory), Memory store.
3. **Rust-Enforced Security Gate**: Python proposes tool actions via JSON IPC; Rust independently validates and decides whether to execute, prompt the user, or deny.

---

## Component Diagram

```
                 ┌─────────────┐
                 │    USER     │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │ Rust CLI/TUI│  (clap, ratatui, terminal I/O)
                 └──────┬──────┘
                        │ IPC (newline-delimited JSON)
                        ▼
              ┌──────────────────┐
              │ Python Agent     │
              │ Runtime          │
              ├──────────────────┤
              │ Context          │
              │ Planner          │
              │ LLM Router       │
              │ State            │
              │ Memory           │
              └────────┬─────────┘
                       ▼
                 ┌─────────────┐
                 │ Tool Router │  (30+ built-in tools)
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐
                 │ Policy      │  (5-layer advisory validation)
                 │ Engine      │
                 └──────┬──────┘
                        │ ToolRequest (JSON over IPC)
                        ▼
             ┌─────────────────────┐
             │ Rust SecurityGate   │  (FINAL AUTHORITY)
             │ Permission Gate     │  (Session grants, prompt overlay)
             │ Sandbox             │
             └──────────┬──────────┘
                        ▼
                    Executor      (Subprocess manager, output capture)
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
    Filesystem       Terminal          Git
        │               │               │
        └───────────────┼───────────────┘
                        ▼
                  Observation     (Error extraction, key findings)
                        │
                        ▼
                   Verification    (Project-aware runner: Flutter/Cargo/Pytest)
```

---

## Agent Loop

The agent operates in a controlled loop:

```
UNDERSTAND
→ PLAN
→ SELECT ACTION
→ POLICY ENGINE (advisory)
→ RUST SECURITY GATE (binding)
→ EXECUTE
→ OBSERVE
→ VERIFY
→ REPLAN IF NECESSARY
→ COMPLETE
```

### Safety Controls
- **Max Iterations**: Default 30 (configurable)
- **Max Tool Calls**: Default 100 per task
- **Timeout**: Default 300 seconds
- **Retry Limit**: Default 3 retries on tool failure
- **Secret Redaction**: Redacts API keys, bearer tokens, private keys from tool outputs before sending to LLM.
