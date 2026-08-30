# SUHO Agent

**Terminal-first autonomous AI agent for developers.**

SUHO Agent understands your goals, plans actions, uses tools, executes work, detects mistakes, corrects them, and verifies the result — all from your terminal.

```
> suho run "Fix my Flutter build"

🧠 Planning...
  1. Inspect project
  2. Run flutter analyze
  3. Diagnose errors
  4. Apply fixes
  5. Run tests
  6. Verify build

⚡ filesystem.list_directory  ✓ (12ms)
⚡ terminal.execute           → flutter analyze
⚡ filesystem.read_file       → pubspec.yaml ✓
⚡ filesystem.edit_file       → pubspec.yaml ✓
⚡ terminal.execute           → flutter test ✓
⚡ terminal.execute           → flutter build apk ✓

✓ Task Complete
Build fixed. Updated pubspec.yaml dependency constraints.
Changed: pubspec.yaml
Tool calls: 6  Tokens: 2,341  Time: 8,432ms
```

---

## Architecture

```
USER → Rust CLI/TUI → [IPC] → Python Agent Runtime
                                  ├── Context Manager
                                  ├── Planner (LLM)
                                  ├── LLM Router
                                  ├── State
                                  └── Memory
                               ↓
                          Tool Router
                               ↓
                          Policy Engine (advisory)
                               ↓
                    Rust Security Gate (FINAL AUTHORITY)
                               ↓
                           Executor
                      ┌─────┼──────┐
                  Files  Terminal  Git
                               ↓
                         Observation
                               ↓
                        Verification
                          ↙       ↘
                        PASS     FAIL → REPLAN
```

**Separation axioms:**
- `TUI ≠ Agent` — Rust renders, Python reasons
- `Agent ≠ Tools` — Agent selects tools, Executor runs them
- `Tools ≠ Security` — Tools request, SecurityGate enforces
- `LLM ≠ Agent` — LLM is the reasoning component, not the runtime

---

## Installation

### Prerequisites

- Rust 1.80+ (`rustup`)
- Python 3.12+ (`uv` recommended)
- Ollama (for local models) or OpenAI API key

### Build

```bash
git clone https://github.com/suho-ai/suho-cli
cd suho-cli

# Build Rust CLI
cargo build --release

# Install Python agent dependencies
cd python-agent
uv sync

# Copy default config
mkdir -p ~/.config/suho
cp configs/default.toml ~/.config/suho/config.toml
```

### Quick Start

```bash
# Run with Ollama (local)
ollama pull llama3.2
suho doctor          # check everything is working
suho chat            # start interactive session
```

---

## Commands

| Command | Description |
|---------|-------------|
| `suho` / `suho chat` | Interactive chat session |
| `suho run "task"` | Execute a task autonomously |
| `suho run --dry-run "task"` | Show planned actions, don't execute |
| `suho run --auto "task"` | Autonomous mode (minimal interruption) |
| `suho plan "task"` | Generate plan without executing |
| `suho ask "question"` | Direct LLM answer (no tools) |
| `suho tools` | List available tools |
| `suho memory list` | List stored memories |
| `suho config show` | Show current configuration |
| `suho doctor` | System diagnostics |
| `suho history` | Task history |
| `suho resume` | Resume last session |
| `suho models` | List available LLM models |

---

## LLM Providers

### Ollama (default, local)

```toml
[model]
provider = "ollama"
model = "llama3.2"
api_base = "http://localhost:11434"
```

### OpenAI

```toml
[model]
provider = "openai"
model = "gpt-4o-mini"
api_key_env = "OPENAI_API_KEY"
```

### OpenAI-compatible (LM Studio, vLLM)

```toml
[model]
provider = "openai_compat"
model = "your-model"
api_base = "http://localhost:1234/v1"
```

---

## Security

SUHO uses a **two-layer security architecture**:

1. **Python PolicyEngine** (advisory) — 5-layer validation:
   - Schema validation
   - Path traversal detection
   - Shell token analysis
   - Pattern classification (SAFE/MODERATE/DANGEROUS/CRITICAL)
   - Session-level policy

2. **Rust SecurityGate** (final authority) — Rust independently validates and makes the binding decision. Python's assessment is advisory only.

Permission levels:
- **SAFE** — auto-allowed (read-only operations, analysis)
- **MODERATE** — auto-allowed by default (configurable)
- **DANGEROUS** — always prompts user
- **CRITICAL** — always prompts; can be auto-denied in config

---

## Supported Project Types

- **Flutter/Dart** — analyze, test, build, format
- **Rust/Cargo** — check, test, build, clippy
- **Python** — pytest, pip, run
- **Node.js/npm** — install, test, run
- **Unity** — detected (specialized tools coming in V0.4)

---

## Project Structure

```
suho-cli/
├── rust-cli/          # Rust: CLI, TUI, SecurityGate, Executor
├── python-agent/      # Python: Agent, LLM, Tools, Memory
├── configs/           # Default configuration
├── docs/              # Documentation
└── plugins/           # Plugin directory (V0.7)
```

---

## Roadmap

| Version | Features |
|---------|----------|
| V0.1 | CLI, LLM, Agent Loop, Tools, Permissions ✓ |
| V0.2 | Planning, Verification, Memory, Git |
| V0.3 | Security hardening, Sandbox |
| V0.4 | Developer tools (Flutter, Rust, Node, Unity) |
| V0.5 | Advanced memory, sessions |
| V0.6 | Web, Docker, SSH tools |
| V0.7 | Plugin system |
| V0.8 | MCP compatibility |
| V1.0 | Stable production release |

---

## License

MIT — see [LICENSE](LICENSE)
