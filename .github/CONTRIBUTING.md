# Contributing

Thanks for taking the time to contribute.

## Getting Started

1. Fork the repository and create a branch from the default branch.
2. Install dependencies using the method documented in the README (`uv`/`pip` for Python, `pnpm`/`npm` for Node).
3. Run the test suite before opening a pull request.

## Branch Names

Use a short, descriptive prefix:

- `feat/<short-name>` — new capability
- `fix/<short-name>` — bug fix
- `docs/<short-name>` — documentation only
- `chore/<short-name>` — tooling, deps, CI

## Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scope): add streaming adapter
fix(scope): handle empty tool result
docs: correct quickstart command
```

Keep commits focused. Do not mix formatting-only changes with behavior changes.

## Pull Requests

A pull request should:

- Explain the problem and the approach, not just the diff.
- Include tests for new behavior and a regression test for bug fixes.
- Keep the public API stable unless the change is explicitly a breaking change.
- Pass CI (lint, type check, tests) with no new warnings.

## Code Style

- Python: `ruff` for lint and format, `mypy` for types where configured.
- TypeScript: the repository's ESLint and Prettier configuration.
- Do not commit secrets, credentials, or local environment files.

## Reporting Bugs and Requesting Features

Use the issue templates. Include version, platform, and a minimal reproduction.

## Security

Do not report security issues in public issues. See `SECURITY.md`.
