# Project governance

MCP Venus OS uses a maintainer-led model. The GitHub repository owner,
[4alvit](https://github.com/4alvit), is the current accountable maintainer.
Contributors propose changes through public issues and pull requests. The
maintainer decides scope, compatibility policy and release acceptance after
reviewing the evidence and unresolved objections. For a disputed design,
record the alternatives and rationale in the issue or pull request before
merging. Security reports follow the private process in [SECURITY.md](SECURITY.md).

## Roles and responsibilities

- **Maintainer:** triage issues, review changes, manage repository permissions,
  assess security reports, approve releases and maintain the roadmap.
- **Contributor:** explain the problem, supply tests and documentation, disclose
  validation limits, and resolve review feedback. Anyone may contribute.
- **Reviewer:** examine behavior, safety boundaries, tests and compatibility;
  state concerns with reproducible evidence. Automated reviewers supplement
  human judgment and do not become project maintainers.
- **Release operator:** run the documented checks, record exact source and
  artifact identities, and follow [RELEASING.md](RELEASING.md). This role may be
  performed by the maintainer. A successful build does not establish hardware
  acceptance.
- **Deployment operator:** control credentials, network access, firmware and
  reviewed hardware contracts for their installation. Repository contributors
  do not gain permission to operate another person's equipment.

Substantial changes should be discussed publicly before implementation. A
security-sensitive issue may remain private until coordinated disclosure.
Contributions are accepted under the repository's MIT license. Contributors
must have the right to submit their work; a DCO sign-off is encouraged but is
not currently a mandatory historical condition.

## Continuity status

**The OpenSSF Silver `access_continuity` requirement is not yet met.** As of
2026-10-12 the owner confirms that a succession/access-recovery mechanism has
not been established. No second maintainer or recovery custodian is claimed.
Bots, protected workflows and this document do not provide human succession.

Before marking this criterion met, establish and verify a legal and practical
arrangement that permits another person to create/close issues, accept changes
and release versions within one week of confirmation that any one individual
can no longer support the project. A suitable delegated-access arrangement or
a securely held recovery/estate plan can satisfy this; publish a redacted
verification statement without exposing keys, passwords or recovery codes.

The current bus factor is not asserted to be two. Adding a capable human
maintainer and verifying recovery remain roadmap work, not completed evidence.
