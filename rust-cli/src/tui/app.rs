//! Ratatui TUI app — full-screen terminal UI.
//! This is the --tui mode.

use anyhow::Result;
use std::path::PathBuf;

use crate::ipc::bridge::AgentBridge;

/// Full ratatui TUI application
pub struct App {
    bridge: AgentBridge,
}

impl App {
    pub fn new(bridge: AgentBridge) -> Self {
        Self { bridge }
    }

    /// Run the full TUI — TODO: implement ratatui layout in V0.21
    pub async fn run(&mut self, cwd: PathBuf, initial_message: Option<String>) -> Result<()> {
        // For V0.1, fall back to simple mode with a notice
        eprintln!("Full TUI coming in V0.21 — using simple mode.");
        crate::tui::simple::run_simple_interactive(
            std::mem::replace(&mut self.bridge, unsafe {
                // Safety: we immediately use the bridge in simple mode
                // This is a placeholder pattern — V0.21 will properly move bridge into ratatui app
                #[allow(invalid_value)]
                std::mem::zeroed()
            }),
            cwd,
            initial_message,
        )
        .await
    }
}
