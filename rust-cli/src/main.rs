use anyhow::Result;
use tracing_subscriber::{fmt, EnvFilter};

mod cli;
mod config;
mod error;
mod executor;
mod ipc;
mod security;
mod tui;

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize structured logging (to stderr, not stdout — stdout is for IPC)
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    fmt::Subscriber::builder()
        .with_env_filter(filter)
        .with_writer(std::io::stderr)
        .with_target(false)
        .compact()
        .init();

    cli::run().await
}
