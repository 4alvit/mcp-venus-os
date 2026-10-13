# OpenSSF Best Practices evidence

This is an evidence index for the OpenSSF Best Practices Passing and Silver self-assessment. It is not an assertion that a badge has been awarded or that every criterion is satisfied. The public badge service is the authority for an awarded status.

## Project and participation

An MCP interface for Venus OS telemetry and explicitly gated MQTT, D-Bus and SSH control.

The project is developed publicly in [Git](https://github.com/4alvit/mcp-venus-os) under the [MIT license](../LICENSE). Its source, issue tracker and pull requests are available without a paid account. [Contribution instructions](../CONTRIBUTING.md) describe reporting, changes, coding conventions, tests and review. The [security policy](../SECURITY.md) provides a confidential vulnerability-reporting path, support scope, response targets and deployment boundaries.

## User and interface documentation

- [`README.md`](../README.md)
- [`docs/CAPABILITIES.md`](../docs/CAPABILITIES.md)
- [`docs/hardware-write-contracts.md`](../docs/hardware-write-contracts.md)
- [`RELEASING.md`](../RELEASING.md)

## Source, testing and analysis

- [`src/mcp_venus_os`](../src/mcp_venus_os)

- [Test suite](../tests) and [CI workflows](../.github/workflows)
- [Local CI entry point](../scripts/ci.sh)
- [CodeQL analysis](../.github/workflows/codeql.yml)
- [Dependency update configuration](../.github/dependabot.yml)

The local gate runs Ruff, mypy, pytest and coverage checks. Tests cover safety denies, hardware write contracts, MQTT reconnects, D-Bus, SSH tool boundaries and server startup. Broker integration tests require their documented local fixtures. Do not point unit tests at a live controller.

CI results are evidence for the tested revision and environment, not proof of safe production or hardware operation. Check the current default-branch runs and unresolved security findings before answering the analysis criteria. Fuzzing, coverage completeness and independent penetration testing must be supported by actual runs; ordinary unit tests must not be presented as those activities.

## Changes and releases

Use `RELEASING.md`, `docs/release-packaging.md` and the release workflow. For each published version explain user-visible changes, security fixes and migration/restart requirements. Never infer hardware validation from mocked CI alone. The [release policy](../.release-policy.json) records automation behavior. A new release must identify its source revision and explain notable changes; security fixes must identify relevant advisories when known.

## Criteria still requiring verification

Before submitting or updating the questionnaire, verify the actual project-specific record: responses to bug and enhancement reports, vulnerability reports in every supported channel, release-note history, unresolved scanner findings, dependency status and required review settings. The primary maintainer must personally confirm knowledge of secure design and common implementation vulnerabilities. A confirmation about another repository does not establish these answers here.

Assess transport encryption, credential storage and privilege limits against the implementation and deployment documented in [SECURITY.md](../SECURITY.md). Do not mark a requirement satisfied solely because a policy says it should be. Record justified non-applicability only where the actual architecture supports it. No paid certification, blanket compliance guarantee or third-party audit is claimed.


### Release-note structure

Source release notes use ATX headings: `## [version]`, `### Upgrade`, and
`### Security`. A heading at the same or a higher level ends its section.
Setext (underlined) headings within the selected release are rejected because
this deliberately limited parser does not implement all CommonMark structure.
Fenced examples and HTML comments cannot supply the required guidance; normal
blank-separated thematic breaks remain supported. The published release body
preserves the original source text after validation.

## Current application and Silver evidence

The [public application](https://www.bestpractices.dev/projects/15439) is the
authority for badge progress; the README badge follows that application.
[Governance and roles](../GOVERNANCE.md), [conduct](../CODE_OF_CONDUCT.md),
[the one-year roadmap](../ROADMAP.md), [security assurance](security-assurance.md),
and [quality and regression evidence](quality-evidence.md) are independently
reviewable. They do not assert that Silver has been awarded.

On 12 October 2026, the primary maintainer confirmed secure-design/common-
vulnerability knowledge for this project and no outside-GitHub bug, suggestion
or vulnerability reports during the preceding 12 months. The GitHub issue
inventory reviewed that day contained no ordinary issues. These project-specific
statements are recorded as owner attestations, not inferred from another repo.
The primary maintainer also confirmed that repository access continuity is
not arranged: `access_continuity` remains **Unmet**. Passing was awarded by the
public application. [The quality page](quality-evidence.md) now links the reviewed
regression inventory, complete-source coverage and measured repeatability of
Python distributions and full multi-platform runnable OCI archives. Signed
prereleases have been verified, but the currently advertised stable release still
requires signed publication and the normal release acceptance; `signed_releases`
remains **Unmet** until then. A Silver badge has not been awarded.

## Provider authentication and security-fix credit

GitHub hosts the project site, repository and downloads. Its published
[account-security explanation](https://github.blog/news-insights/product-news/new-improvements-and-best-practices-for-account-security-and-recoverability/)
states that account passwords use bcrypt. The project does not operate a
separate user-password database. This is provider documentation, not access to
GitHub internal systems.

The owner reports no external vulnerability reports in the preceding twelve
months. Internally discovered security corrections retain contributor attribution
in their public commits and pull requests; no additional external reporter is
implied. SECURITY.md requires credit with the reporter’s consent for future
reports.
