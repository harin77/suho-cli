//! Output capture — limits, truncates, and redacts output from tools.

/// Patterns used for secret redaction
const SECRET_PATTERNS: &[(&str, &str)] = &[
    // OpenAI / Anthropic API keys
    (r"sk-[A-Za-z0-9]{32,}", "[REDACTED_API_KEY]"),
    // Generic Bearer tokens
    (r"Bearer [A-Za-z0-9\-._~+/]+=*", "[REDACTED_BEARER_TOKEN]"),
    // AWS credentials
    (r"AKIA[A-Z0-9]{16}", "[REDACTED_AWS_KEY]"),
    // Private key headers
    (r"-----BEGIN [A-Z]+ PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
    // Password patterns
    (r"password[=:]\s*[^\s]+", "[REDACTED_PASSWORD]"),
    (r"passwd[=:]\s*[^\s]+", "[REDACTED_PASSWORD]"),
    // Generic token patterns
    (r"token[=:]\s*[^\s]{16,}", "[REDACTED_TOKEN]"),
    // GH tokens
    (r"gh[pors]_[A-Za-z0-9]{36}", "[REDACTED_GH_TOKEN]"),
];

pub struct OutputCapture {
    max_bytes: usize,
}

impl OutputCapture {
    pub fn new(max_bytes: usize) -> Self {
        Self { max_bytes }
    }

    /// Process raw stdout/stderr bytes.
    /// Returns: (stdout_str, stderr_str, was_truncated, secrets_redacted_count)
    pub fn process(
        &self,
        stdout_raw: &[u8],
        stderr_raw: &[u8],
    ) -> (String, String, bool, u32) {
        let mut secrets_redacted = 0u32;
        let mut truncated = false;

        let stdout = String::from_utf8_lossy(stdout_raw).to_string();
        let stderr = String::from_utf8_lossy(stderr_raw).to_string();

        // Truncate if needed (keep head + tail)
        let (stdout, trunc1) = self.truncate(&stdout);
        let (stderr, trunc2) = self.truncate(&stderr);
        if trunc1 || trunc2 {
            truncated = true;
        }

        // Redact secrets
        let (stdout, n1) = self.redact_secrets(stdout);
        let (stderr, n2) = self.redact_secrets(stderr);
        secrets_redacted += n1 + n2;

        (stdout, stderr, truncated, secrets_redacted)
    }

    /// Truncate output to max_bytes, keeping head + tail with a notice
    fn truncate(&self, s: &str) -> (String, bool) {
        if s.len() <= self.max_bytes {
            return (s.to_string(), false);
        }

        let head_bytes = self.max_bytes / 2;
        let tail_bytes = self.max_bytes / 2;

        let head = &s[..head_bytes.min(s.len())];
        let tail_start = s.len().saturating_sub(tail_bytes);
        let tail = &s[tail_start..];

        let omitted = s.len() - head_bytes - tail_bytes;
        let result = format!(
            "{}\n\n[... {} bytes omitted ...]\n\n{}",
            head, omitted, tail
        );

        (result, true)
    }

    /// Redact secret patterns from output
    fn redact_secrets(&self, s: String) -> (String, u32) {
        let mut result = s;
        let mut count = 0u32;

        for (pattern, replacement) in SECRET_PATTERNS {
            // Simple string-based detection (regex would be better but adds dependency)
            // For now: line-by-line heuristics
            let mut lines = result.lines().map(|l| l.to_string()).collect::<Vec<_>>();
            let mut changed = false;

            for line in lines.iter_mut() {
                let lower = line.to_lowercase();
                let needs_redaction = lower.contains("api_key")
                    || lower.contains("secret")
                    || lower.contains("password")
                    || lower.contains("token")
                    || lower.contains("bearer")
                    || line.starts_with("sk-")
                    || line.starts_with("AKIA")
                    || line.starts_with("gh")
                    || line.contains("-----BEGIN")
                    || line.contains("PRIVATE KEY");

                if needs_redaction && line.len() > 8 {
                    // Check if line contains a value that looks like a secret
                    if let Some(eq_pos) = line.find('=').or_else(|| line.find(':')) {
                        let value_part = &line[eq_pos + 1..].trim().to_string();
                        if value_part.len() > 8 && !value_part.starts_with('[') {
                            *line = format!("{}=[REDACTED]", &line[..eq_pos]);
                            count += 1;
                            changed = true;
                        }
                    }
                }
            }

            if changed {
                result = lines.join("\n");
            }
        }

        (result, count)
    }
}
