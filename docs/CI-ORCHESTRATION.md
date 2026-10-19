# CI orchestration

Quality gate owns pull request and merge queue validation. The release pipeline
owns default branch and nightly checks for applications; validation-only projects
run those events through Quality gate. Callable validators do not launch duplicate
runs. Superseded PR runs are cancelled, and validation jobs have explicit timeouts.

The required CI configuration contracts check CodeQL pin compatibility, validation
triggers, timeouts, and complete gate dependencies. Dependency Review, where present,
blocks the same gate for pull requests and reports other events as not applicable.
CodeQL action updates are grouped where Dependabot Actions updates are configured.

Auto-merge verifies strict branch protection for CI gate, requests native GitHub
auto-merge, and exits. GitHub waits for CI, external checks and required reviews.
External check contexts retain their required status and are bound to their source GitHub App. Removing automerge
or converting a PR to draft disables an existing request. The metadata-only workflow
runs from the trusted base without executing PR code. BOT_PAT remains the merger token;
Dependabot approval uses GITHUB_TOKEN and human PR approval uses the bot's BOT_PAT.

## Scorecard completeness

The hosted publishing job preserves the original JSON and SARIF from one scan.
The analysis job checks that JSON before uploading its unchanged SARIF to GitHub.
The contract accepts Scorecard **v5.6.0**, commit
`61e84743356275f6ffca23b1b2f2cb945e19eb96`, and requires all 18 checks, including
Contributors and Signed-Releases. Low scores are valid findings; missing checks,
runtime errors and a different repository, commit or scanner version stop upload.
Only two exact upstream inconclusive results are accepted: Packaging's
`packaging workflow not detected` and Signed-Releases' `no releases found`.
Both require integer score `-1` and no explicit error. The singular
`no release found` is a Signed-Releases runtime error and is rejected.

The action is pinned to a commit, but its metadata selects a container tag.
An upstream container update can therefore stop the version guard. Before changing
the expected version, review the corresponding upstream
[error constructors](https://github.com/ossf/scorecard/blob/61e84743356275f6ffca23b1b2f2cb945e19eb96/checker/check_result.go),
[JSON serialization](https://github.com/ossf/scorecard/blob/61e84743356275f6ffca23b1b2f2cb945e19eb96/pkg/scorecard/json.go),
[Packaging evaluation](https://github.com/ossf/scorecard/blob/61e84743356275f6ffca23b1b2f2cb945e19eb96/checks/evaluation/packaging.go),
and [Signed-Releases evaluation](https://github.com/ossf/scorecard/blob/61e84743356275f6ffca23b1b2f2cb945e19eb96/checks/evaluation/signed_releases.go).
Update the reduced report fixture from an actual scan, run
`pytest tests/test_validate_scorecard_json.py`, and verify the next main-branch
Scorecard run. The fixture retains check names, scores and reasons from run
`39259762912`, with repository identity replaced by test values.
