# Security Policy

## Supported Versions

Security fixes are applied to the latest released version on the default branch.

## Reporting a Vulnerability

Please **do not** open a public issue for security problems.

1. Open a private report through this repository's **Security → Advisories → Report a vulnerability** tab (GitHub Private Vulnerability Reporting).
2. Include: affected version/commit, reproduction steps, impact, and any suggested fix.
3. You can expect an acknowledgement within 72 hours and a remediation timeline within 7 days.

Please give us a reasonable window to ship a fix before any public disclosure.

## Scope

- Vulnerabilities in this repository's own source code and release artifacts.
- Misconfiguration that would expose user data, credentials, or model endpoints.
- Dependency vulnerabilities that are exploitable through this project's code paths.

## Out of Scope

- Issues in third-party services or upstream dependencies that do not affect this project's usage.
- Findings from automated scanners submitted without a working proof of concept.
- Social engineering, physical access, and denial-of-service against shared infrastructure.
