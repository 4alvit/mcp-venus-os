# Contributing

An MCP interface for Venus OS telemetry and explicitly gated MQTT, D-Bus and SSH control.

## Questions, bugs and proposals

Use [GitHub Issues](https://github.com/4alvit/mcp-venus-os/issues) for questions, bug reports and feature proposals. Search existing issues first. Describe the affected version/commit, expected and actual behavior, minimal reproduction and relevant environment. Remove tokens, private endpoints, household identifiers and personal data from examples. Security vulnerabilities use the confidential process in [SECURITY.md](SECURITY.md).

Anyone may propose a change through a pull request. Discuss compatibility or architectural changes in an issue before a large implementation. Maintainers aim to acknowledge actionable reports within 14 days; security reports follow the security policy. No paid support or response-time guarantee is implied.

## Development and validation

Clone the repository, create a branch from `main`, and use the Python version and dependencies declared by the project and CI. Run from the repository root:

```sh
bash scripts/ci.sh --install
bash scripts/ci.sh
```

The local gate runs Ruff, mypy, pytest and coverage checks. Tests cover safety denies, hardware write contracts, MQTT reconnects, D-Bus, SSH tool boundaries and server startup. Broker integration tests require their documented local fixtures. Do not point unit tests at a live controller.

For a bug fix, add a regression test that fails before the fix and passes afterward. For new functionality, test normal behavior, invalid input and relevant authorization/error paths. Preserve existing checks; do not lower coverage gates or ignore findings merely to obtain a green build. Python code follows the configured formatter/linter where present and normal PEP 8 conventions otherwise. Keep shell, YAML and generated examples compatible with their declared tools.

## Review and compatibility

Keep pull requests focused and explain the problem, resulting behavior, compatibility impact and exact validation performed. Update the user-facing documentation when changing configuration, interfaces or operational behavior. Call out tests not run and their prerequisites. Maintainers review changes through GitHub pull requests and required CI; automated review is supplemental. Contributions are provided under the repository's [MIT license](LICENSE); a contributor must have the right to submit the work.

Use `RELEASING.md`, `docs/release-packaging.md` and the release workflow. For each published version explain user-visible changes, security fixes and migration/restart requirements. Never infer hardware validation from mocked CI alone.

## Source and interfaces

- [`src/mcp_venus_os`](src/mcp_venus_os)
- [`README.md`](README.md)
- [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md)
- [`docs/hardware-write-contracts.md`](docs/hardware-write-contracts.md)
- [`RELEASING.md`](RELEASING.md)

See the [OpenSSF evidence index](docs/openssf-evidence.md) for the current assessment scope and outstanding verification.
