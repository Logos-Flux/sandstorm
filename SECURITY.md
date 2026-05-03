# Security Policy

## Supported versions

During the alpha (`0.x`) series, only the latest tagged release on `main` receives security fixes.

## Reporting a vulnerability

Email **lf@logosflux.io** with details. **Do not open public GitHub issues for vulnerabilities.**

You can expect:

- Acknowledgement within 7 days.
- Coordinated disclosure once a fix is available.

## Scope

In scope:

- Bugs that allow unauthenticated access to MCP tools.
- Path traversal escaping the workspace root.
- OAuth or bearer-token forgery.
- Remote code execution outside the documented `terminal_exec` capability.

Out of scope:

- Anything that requires a valid bearer token. The bearer is intentionally root-equivalent on the workspace; this is the documented threat model. See [`server/README.md`](server/README.md).
