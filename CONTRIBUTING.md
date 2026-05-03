# Contributing

## Status

Sandstorm is in **alpha**. APIs may change before 1.0. Issues and pull requests are welcome.

## Setup

See [`server/README.md`](server/README.md) for the full development setup. Quick start:

```bash
cd server
uv sync
uv run pytest
```

## Workflow

- Open an issue before starting non-trivial changes so the design can be discussed up front.
- Keep one logical change per pull request.
- Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, etc.).
- Write descriptive commit messages explaining the *why*, not just the *what*.

## Style

- `ruff check` and `ruff format` must pass.
- `pytest` must be green.
- Add tests for new behavior; update existing tests when behavior changes.

## Code of Conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting security issues

Do **not** file public GitHub issues for vulnerabilities. See [`SECURITY.md`](SECURITY.md) for the private disclosure process.
