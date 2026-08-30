# SUHO Agent

**Terminal-first, autonomous AI agent ecosystem built for software engineers, Linux sysadmins, and AI developers.**

SUHO Agent understands your goal, creates structured execution plans, invokes built-in developer tools, runs shell commands, verifies code output, auto-corrects mistakes, and manages persistent memory — all directly from your terminal.

```text
╔══════════════════════════════════════════╗
║           SUHO Agent  v0.2.0             ║
╚══════════════════════════════════════════╝

Interactive mode — type your request. Ctrl+C to exit.
Working directory: D:\workspace\suho-cli

> /models
> Fix my Flutter build and run unit tests
```

---

## Quick Start — Windows Installation

### Option 1: Pre-Compiled Release (Fastest)

1. **Download**: Download `suho-v0.2.0-windows-x64.zip` from [GitHub Releases](https://github.com/harin77/suho-cli/releases/tag/v0.2.0).
2. **Extract**: Right-click `.zip` -> **Extract All...**.
3. **Install**: Double-click `install.bat` inside the extracted folder.
   - Installs `suho.exe` to `%USERPROFILE%\.suho\bin`
   - Adds install path to User `PATH`
   - Creates default configuration at `%USERPROFILE%\.config\suho\config.toml`
4. **Open Terminal**: Open a **NEW** PowerShell window and test:
   ```powershell
   # If running in current window without opening a new one, run this first:
   $env:Path += ";$env:USERPROFILE\.suho\bin"

   suho doctor
   suho chat
   ```

---

## Interactive CLI Guide

Enter interactive CLI mode by running:

```powershell
suho chat
# or simply:
suho
```

### Slash Commands in Interactive Mode

Inside `suho chat`, start commands with `/`:

| Command | Description |
|:---|:---|
| **`/models`** | Open interactive menu to select LLM provider (Ollama, OpenAI, Anthropic, Groq, DeepSeek, OpenRouter, Together, Gemini, LM Studio), enter API key, save to config, and list all available models |
| **`/help`** | Display detailed interactive help menu, supported providers, and CLI options |
| **`/tools`** | List all 30+ built-in developer tools and their availability status |
| **`/history`** | Show recent task execution history |
| **`/status`** | Show agent runtime health, active model, memory status, and uptime |
| **`/clear`** | Clear the terminal screen |
| **`/exit`** | Exit interactive session (or press `Ctrl+C`) |

---

## Supported LLM Providers

SUHO Agent supports 9+ cloud and local LLM providers out-of-the-box:

| Provider | Type | Default Model | Base URL / Notes |
|:---|:---|:---|:---|
| **Ollama** | Local (Free) | `llama3.2` | `http://localhost:11434` |
| **OpenAI** | Cloud | `gpt-4o-mini` | `https://api.openai.com/v1` |
| **Anthropic** | Cloud | `claude-3-5-sonnet-20241022` | Direct Messages API |
| **Groq** | Cloud | `llama-3.3-70b-versatile` | Ultra-fast inference (`https://api.groq.com/openai/v1`) |
| **DeepSeek** | Cloud | `deepseek-chat` | `https://api.deepseek.com/v1` |
| **OpenRouter** | Cloud Router | `auto` | `https://openrouter.ai/api/v1` |
| **Together AI** | Cloud | `meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo` | `https://api.together.xyz/v1` |
| **Google Gemini** | Cloud | `gemini-1.5-flash` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| **LM Studio** | Local (Free) | `local-model` | `http://localhost:1234/v1` |

### Setting up a Provider

Simply run `/models` inside `suho chat` to select your provider, type your API key (if required), and click save. The settings are saved automatically to `~/.config/suho/config.toml`.

---

## CLI Subcommands Overview

Run these commands directly from your terminal outside interactive mode:

```bash
# Execute task autonomously
suho run "Fix Flutter build and run tests"

# Preview planned actions without executing
suho run --dry-run "Clean build target"

# Autonomous mode (minimal prompts)
suho run --auto "Check Rust project with clippy"

# Generate structured execution plan only
suho plan "Implement user authentication module"

# Direct Q&A (no tool calls)
suho ask "Explain Rust ownership and borrowing"

# Run system diagnostics
suho doctor

# List long-term stored memories
suho memory list

# Search memories by keyword
suho memory search "database"

# Resume last incomplete session
suho resume
```

---

## Architecture & Security

SUHO Agent uses a strict **two-tier architecture**:

```text
USER -> Rust CLI/TUI -> [IPC] -> Python Agent Runtime
                                  ├── Context Manager
                                  ├── Planner (LLM)
                                  ├── LLM Router
                                  └── Memory (SQLite)
                               ↓
                          Policy Engine (5-Layer Advisory)
                               ↓
                    Rust Security Gate (FINAL AUTHORITY)
                               ↓
                           Executor
                      ┌─────┼──────┐
                  Files  Terminal  Git
                               ↓
                          Verification
```

1. **Rust CLI & SecurityGate (Binding Authority)**: Rust acts as the final gatekeeper. Even if the Python runtime requests tool execution, Rust independently verifies path safety, injection patterns, and session permissions before running commands.
2. **Python Agent Runtime (Reasoning & Tools)**: Handles LLM communications, prompt assembly, token budgeting, multi-step planning, and 30+ built-in developer tools (`filesystem.*`, `git.*`, `development.*`, `system.*`, `terminal.*`).

---

## Building from Source

### Prerequisites
- **Rust 1.80+**: `rustup`
- **Python 3.12+**: `uv` recommended

### Build Instructions

```powershell
# 1. Clone repository
git clone https://github.com/harin77/suho-cli.git
cd suho-cli

# 2. Install Python agent dependencies
cd python-agent
uv sync --extra dev
cd ..

# 3. Build Rust CLI release binary
cargo build --release --manifest-path rust-cli/Cargo.toml -j 1

# 4. Copy default config
mkdir -p ~/.config/suho
cp configs/default.toml ~/.config/suho/config.toml
```

---

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

## Credits & Acknowledgments

- **Core Maintainer & Lead Architect**: **Harin & SUHO AI Team** ([@harin77](https://github.com/harin77))
- **Built With**:
  - **Rust**: [`clap`](https://github.com/clap-rs/clap), [`tokio`](https://github.com/tokio-rs/tokio), [`ratatui`](https://github.com/ratatui-org/ratatui), [`serde`](https://github.com/serde-rs/serde)
  - **Python**: [`pydantic`](https://github.com/pydantic/pydantic), [`structlog`](https://github.com/hynek/structlog), [`httpx`](https://github.com/encode/httpx), [`aiosqlite`](https://github.com/omnilib/aiosqlite)
