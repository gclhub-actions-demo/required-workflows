# Central required PR workflows

Trusted, centrally governed CI for `gclhub-actions-demo`. **Staged delivery only:
all integration PRs remain unmerged and both ruleset templates are disabled.**
Nothing in this repository automatically changes organization settings.

## Contract

Each application commits `.github/app-ci.json`. For the monorepo:

```json
{
  "version": 1,
  "projects": [
    {"id": "java", "path": "apps/java-app"},
    {"id": "node", "path": "apps/nodejs-api"},
    {"id": "python", "path": "apps/python-service"},
    {"id": "dotnet", "path": "apps/dotnet-api"}
  ],
  "extensions": {
    "preflight": ".github/ci/preflight.sh",
    "postflight": ".github/ci/postflight.sh"
  }
}
```

`extensions` and either phase are optional. Everything else is required.
`schema/app-ci.schema.json` rejects unknown fields at every level. Extension
values are regular, non-symlink repository-relative `.sh` files, not inline
commands or YAML. They run with `bash --noprofile --norc -euo pipefail`, a ten-minute
process timeout, and a fifteen-minute job timeout. Missing scripts or failures block.
No runtime, runner, command, disable, test-selection, or coverage overrides exist.

`policy/repositories.json` is authoritative, not repository autodetection:

| Repository | Exact required projects |
|---|---|
| `github-actions-demo` | `java`: `apps/java-app`; `node`: `apps/nodejs-api`; `python`: `apps/python-service`; `dotnet`: `apps/dotnet-api` |
| `java-app-demo` | `java`: `.` |
| `python-app` | `python`: `apps/python-service` |

Omitted, duplicated, extra, moved, missing, or symlinked projects fail. Every
configured project runs on every PR, including documentation-only PRs.

## Trusted execution and isolation

`.github/workflows/required-pr.yml` is intended to be selected by an
**organization ruleset workflow rule**, not by a status-check name and not by a
PR-owned caller. The rule selects this repository's ID, workflow path, and an
approved immutable commit SHA. A same-named check in an app is not a substitute.

Each job explicitly checks out `gclhub-actions-demo/required-workflows` at
`${{ github.workflow_sha }}`, the revision of the running workflow, into
`central/`. It does not fetch helpers from mutable `main`, from the app's local
actions, or from the application's PR revision. There are no reusable workflow
calls whose caller context could change the helper revision. The sole local
composite action is inside that trusted central checkout. External actions are
pinned to full SHAs.

Application code is checked out at `${{ github.sha }}` (the PR merge revision),
into `app/`, with `persist-credentials: false`. All tokens are read-only and no
secrets are passed. There is no `pull_request_target`, deployment, cache, artifact
transfer, or persistent runner. Every policy, preflight, individual baseline,
postflight, and gate job gets a fresh `ubuntu-24.04` hosted runner. Extensions
cannot transfer a modified checkout, installed packages, environment, cache, or
generated output to a baseline. Postflight must inspect a clean source checkout;
it cannot assume baseline build outputs exist.

Toolchains are centrally provisioned: Temurin Java 17, Node 22, Python 3.11,
and .NET SDK 8. The .NET baseline writes a local `global.json` selecting the exact
SDK 8 version emitted by setup-dotnet, avoiding a hosted runner's newer
preinstalled SDK silently taking precedence. App SDK downgrades are rejected.
The Python helper runs in isolated mode (`python -I`) outside
the app's import path; Python subprocesses use the already selected absolute
`sys.executable`. The final gate never checks out or executes application code.

**Trust boundary:** app-owned build files, dependency hooks, tests, source,
compiler plugins, and reports are still executable/untrusted inputs. Fixed
profiles, skip/configuration guards, fresh outputs, and nonzero report checks
prevent ordinary disabling, omissions, and zero-test/coverage false positives;
they are not tamper-proof attestations against arbitrary malicious build code.
Application code can forge reports or alter tools on its own runner. Central
helpers are present on that runner and are not an OS-level security boundary.
Do not grant secrets, write permissions, persistent runners, or privileged
network access based solely on a successful run. Central owners must review
policy changes; app admins must not automatically receive central write access.

## Baselines

| Profile | Fixed stages and required evidence |
|---|---|
| Java 17 | Maven `clean verify checkstyle:check` with skip/failure-ignore disabled and strict warning-level Checkstyle. Zero Checkstyle violations, nonzero Surefire XML tests, JaCoCo XML with existing **70% LINE per PACKAGE**. Standalone Java also requires nonzero Failsafe integration XML and aggregate JaCoCo coverage. |
| Node 22 | `npm ci --ignore-scripts`, central ESLint rules, `npm run build`, direct Jest with central test/coverage config. Requires emitted JavaScript, nonzero JUnit XML, Istanbul JSON and summary. Existing **70% branches/functions/lines/statements** global minima retained. |
| Python 3.11 | requirements installation, isolated flake8 (100 columns, E203/W503 ignored), pytest with central discovery/coverage config, wheel and sdist build. Nonzero JUnit XML and measured Cobertura coverage. Standalone Python retains **80%** and branch coverage; monorepo has **no invented percentage**. |
| .NET 8 | Explicit solution restore, `dotnet format --verify-no-changes`, Release build, explicit test project with TRX and XPlat Code Coverage. Requires executed successful tests and measured Cobertura coverage; **no invented percentage**. |

Maven guards require expected plugins and minimum existing plugin versions,
Java 17 compiler properties, and reject skip, failure-ignore, exclusion, and
narrowing test selectors. Node guards require expected lint/build scripts and
strict, emitting TypeScript configuration; centrally owned ESLint/Jest config
prevents app config replacing the baseline with a no-op. Python uses central
pytest/coverage configuration and isolated flake8. .NET requires a real enabled
test project, test SDK/collector, .NET 8 targets, and no new source-removal rules.
The existing main project's `Tests/**` exclusion remains allowed.
JaCoCo packages with no executable instructions (for example repository
interfaces) have no LINE counter and are explicitly reported as N/A. Executable
packages missing LINE data fail, and package LINE totals must match report
totals; measured packages still require the unchanged 70% minimum.

The final gate uses `always()`: policy and all matrix baselines must succeed.
Configured extension jobs must succeed. Only an **absent** extension is expected
to be skipped; a skipped baseline or configured extension is a failure.

## Validation and application preview

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7
```

`validate-central.yml` runs policy/schema/gate/evidence negative tests plus
Actions syntax lint. Tests cover missing projects/scripts/reports, forbidden
overrides, unsafe paths/symlinks, duplicate JSON keys, empty tests/coverage,
threshold failures, and skipped/cancelled/failed dependency rejection.

`preview-apps.yml` exercises the **same baseline and hook scripts** against the
reviewed immutable app integration commits in `policy/fixtures.json`, without a
ruleset or settings changes. It covers all six project profiles and both hooks
in all three integration fixtures on fresh hosted runners. Fixtures must cover
exactly the governed repositories. Preview checks out central code from the
central PR merge revision and app fixtures at exact commit SHAs; it does not
accept caller-supplied workflow inputs, mutable branches, or secrets. Preview
fixtures intentionally include both hooks, while the production contract also
supports their absence. Update fixture SHAs through reviewed central PRs.

Preview demonstrates script/toolchain compatibility, not the live ruleset's
cross-repository event context. A later authorized ruleset smoke test must verify
`github.workflow_sha` helper checkout and PR merge-ref semantics before active
enforcement; failure must remain blocking, never fall back to `main`.

## Later deployment (requires separate explicit approval)

The current organization plan is Enterprise, but the inspected token cannot read
organization rulesets (`admin:org` scope/appropriate organization permissions are
needed). The source repository is public to support the three public target
repositories. The user approved **`@gclhub` as the initial central CODEOWNER**;
`.github/CODEOWNERS` covers every file, including itself. No team is fabricated
or created. CODEOWNERS alone does not enforce approvals until the separately
approved central protection ruleset is active.

After review, separately authorize these steps:

1. Verify initial owner `@gclhub` retains central write access, default org
   permissions, and app-admin separation. Future team ownership requires a
   separately approved membership/access decision and CODEOWNERS PR.
2. Approve/merge central and app integration PRs, inspect all baseline previews,
   and select the exact approved central commit containing workflow and helpers.
3. Render local **disabled** artifacts using the actual approved SHA:

   ```sh
   python3 scripts/render_rulesets.py \
     --central-sha APPROVED_40_CHARACTER_COMMIT_SHA \
     --output /tmp/required-workflow-deployment
   ```

4. Ensure this PR's `.github/CODEOWNERS` is on the approved central revision.
   Review/apply `central-main.json` with the organization
   rulesets API, then explicitly enable it after owner review is effective.
   The template requires PRs, a central code-owner approval, last-push approval,
   conversation resolution, and blocks force-push/deletion with no bypass actors.
   With a single initial owner, that owner cannot approve their own PRs; arrange
   a second explicitly approved central reviewer/owner before owner-authored
   policy changes, rather than adding an admin bypass.
5. Inspect current organization rulesets with an authorized token to avoid
   overwriting existing policy. Review/apply `application-main.json` via
   `POST /orgs/gclhub-actions-demo/rulesets` (or update the intended existing ID).
   Rendered JSON remains `enforcement: disabled`; do not activate by accident.
   It targets exactly `github-actions-demo`, `java-app-demo`, and `python-app`,
   excludes `.github`, and targets only `refs/heads/main`. It requires PRs,
   blocks force-push/deletion, has an empty bypass list, and selects workflow
   repository ID `1437306918` with **`sha`**, not a mutable branch reference.
6. With separate approval, use evaluate mode for event/context and workflow
   smoke tests, inspect runs/insights and missing/failed project scenarios, then
   explicitly activate. Evaluate mode is not merge enforcement. Existing open
   PRs need a new commit, branch update, or close/reopen to trigger the rule.

Do not substitute a required status-check name for the workflow identity rule.
Do not target all branches or add bypasses as a workaround for failures.
Rollback means an explicitly approved ruleset update to a previous approved
central SHA or enforcement mode; retain review/audit records.

Ruleset event filters (`branches`, `paths`, `types`) are ignored by GitHub.
Branch targeting therefore lives in the ruleset, not workflow filters.
The workflow uses default `pull_request` activity types and does not use
cancel-in-progress concurrency. Merge queue is **not configured or supported
by this initial deployment**; before enabling it, add and verify `merge_group`
event, configuration, and checkout semantics. CodeQL init/analyze are not
allowed inside ruleset workflows; this framework intentionally contains neither.

GitHub does not start ruleset workflows for events created with `GITHUB_TOKEN`.
Automation that opens or updates PRs must use a separately approved GitHub App
or user credential that produces eligible events; do not grant bypass permission
or add credentials here as a workaround. An already blocked bot-created PR needs
an eligible new commit, branch update, or close/reopen event. Required workflow
enforcement must remain blocking when no eligible workflow run exists.

References:
[ruleset troubleshooting](https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/troubleshooting-rules),
[organization rulesets REST API](https://docs.github.com/en/rest/orgs/rules#create-an-organization-repository-ruleset),
[GitHub contexts](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#github-context).
