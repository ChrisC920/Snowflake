# Agent workflow

Snowflake can implement GitHub issues on its own. You write an issue, add the `agent-ready` label, and get back a pull request that is tested and independently reviewed. Approving it is the only manual step, and approval merges it.

Everything runs on GitHub Actions and the official [Claude Code Action](https://github.com/anthropics/claude-code-action). The agents use your Claude subscription (`CLAUDE_CODE_OAUTH_TOKEN`). There is no API key, no third-party service and no server to run.

- [How it works](#how-it-works)
- [Daily use](#daily-use)
- [Commands and controls](#commands-and-controls)
- [Parallelism and limits](#parallelism-and-limits)
- [Approval and merging](#approval-and-merging)
- [Security model](#security-model)
- [Costs](#costs)
- [One-time setup](#one-time-setup)
- [Configuration reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)
- [Verification plan](#verification-plan)
- [Extending: Codex and other agents](#extending-codex-and-other-agents)

## How it works

```
 you: issue + acceptance criteria ──► label agent-ready (or move card to Queued)
                                            │
   Agent Control (reconciler, every event + every 15 min, ubuntu)
     · checks who applied the label (write access only)
     · holds the issue if "Depends on #N" is still open
     · starts it when one of AGENT_MAX_CONCURRENT slots is free
                                            │
   Agent Implement (one run per issue; concurrency group agent-issue-N)
     prepare  (ubuntu)  task context from the issue + maintainer comments only
     implement (macOS)  Claude: plan → code → tests → make lint/test → commit (read-only token)
     publish  (ubuntu)  policy check → push agent/issue-N → draft PR "Closes #N" (GitHub App)
                                            │
          ┌─────────────────────────────────┴─────────────────────────────┐
   CI (Lint, Test, Build, Policy)                         Agent Review (separate Claude session,
   deterministic, macOS + ubuntu                          read-only) → status agent/review on head SHA
          └─────────────────────────────────┬─────────────────────────────┘
   Agent Control gate
     red  → remediation (bounded: 3 tries, no identical repeats) → back to CI + review
     green and behind main → update branch → re-validate
     green → mark ready, enable auto-merge (squash), ping you
                                            │
   you: Approve ──► GitHub merges (branch protection checks your approval is on the current SHA)
                 ──► "Closes #N" closes the issue, branch deleted, project card → Done
```

### Files

| File | Role |
|---|---|
| `.github/workflows/agent-control.yml` | Reconciler: delegation, queueing, gate, remediation, branch updates, project sync, `/agent` commands |
| `.github/workflows/agent-implement.yml` | One issue's implementation or remediation run |
| `.github/workflows/agent-review.yml` | Independent AI review → `agent/review` commit status |
| `.github/workflows/ci.yml` | Lint, Test, Build (existing), plus **Policy** and **Agent tooling** |
| `.github/agent/agentctl.py` | All decision logic, in deterministic Python (stdlib only, unit-tested) |
| `.github/agent/prompts/*.md`, `schemas/*.json` | Agent instructions and the structured results they must return |
| `.github/ISSUE_TEMPLATE/*.yml` | Issue forms with acceptance criteria, dependencies, validation and priority |
| `CLAUDE.md` / `AGENTS.md` | Persistent instructions for every agent |

### State: labels on the issue, mirrored on the project board

The issue's labels are the source of truth. Each Project **Status** is derived from them, so you never maintain two records.

| Label | Status | Meaning |
|---|---|---|
| none | Backlog / Ready | Yours. Nothing happens until you delegate. |
| `agent-ready` | Queued | Delegated; waiting for a free agent slot. |
| `blocked` | Blocked | Waiting on `Depends on #N`; starts automatically when those close. |
| `agent-working` | In Progress | An agent is implementing or fixing right now. |
| `agent-validating` | Validation | Draft PR open; CI and AI review running. |
| `auto-fix` | Changes Requested | A remediation is queued (CI, AI review, conflict or your feedback). |
| `agent-review` | In Review | CI and AI review are green on the current commit. **Your turn.** |
| `agent-approved` | Approved | You approved the current commit; auto-merge is finishing. |
| `needs-human` | Blocked | The agent stopped and explained why in a comment. |
| closed | Done | Merged; the issue was closed by `Closes #N`. |

`human-only` keeps an issue away from agents. `priority:high|medium|low` orders the queue, and the issue form's Priority field sets it.

## Daily use

1. Open the project board.
2. Create an issue with one of the forms (Feature, Bug, New tool, Refactor, Testing, Documentation, Tech debt). Write **acceptance criteria** the reviewer can check. Pick a priority. Add `Depends on #N` if the work has to wait for another issue.
3. Add **`agent-ready`**, or drag the card to **Queued**. The board-to-label sync runs within 15 minutes.
4. Delegate more independent issues while that runs. They queue and start as slots free up.
5. Watch the board. The issue gets a comment at each step: agent started, PR opened, remediation queued, ready for approval, needs a human.
6. When a PR is **In Review**, read the AI review comment and the diff, then **Approve**. It merges itself.
7. If it isn't right, **Request changes** with comments, or comment `@claude <what to change>`. The agent fixes it on the same PR, and CI and review run again.

You don't start agents, create branches or worktrees, run tests, open PRs, re-request reviews or press merge.

### Writing issues agents do well on

- One outcome per issue. Split large features and link them with `Depends on #N`.
- Make acceptance criteria observable: "Tile shows 'Off' after the timer ends", not "works well".
- Name the files or patterns to follow in **Architectural context**.
- Say what must not change in **Constraints**.
- Use `human-only` for work involving signing, releases, CI, security policy or anything under the [protected paths](../CLAUDE.md#working-as-an-autonomous-agent).

## Commands and controls

Comment on the issue or its agent PR. Only people with write access are obeyed; everyone else is ignored.

| Command | Effect |
|---|---|
| `@claude <instructions>` | On an agent PR: queue a fix with your instructions. On an issue: answer the agent's question and re-queue it. |
| Review → **Request changes** | Same as `@claude`, using your review comments. |
| `/agent retry` | Clear `needs-human`, reset the attempt counters and try again. |
| `/agent cancel` | Stop the active run and remove the issue from the queue. The PR stays open. |
| `/agent status` | Reply with labels, PR, run counts and the pause state. |
| Remove `agent-ready` | Dequeue an issue that hasn't started. |
| Add `human-only` | Never delegate this issue. |

**Emergency stop:** `gh variable set AGENTS_PAUSED --body true`. Nothing new starts and the review status stays pending. Running jobs finish; cancel them in the Actions tab if needed. Resume with `gh variable set AGENTS_PAUSED --body false`. To disable everything, disable the four `Agent *` workflows in the Actions tab or run `gh workflow disable "Agent Control"`.

**Manual run:** Actions → Agent Implement → Run workflow (issue number, mode).

## Parallelism and limits

Every issue is an independent unit:

- Its own run, macOS runner and branch (`agent/issue-N`).
- Its own concurrency group (`agent-issue-N`), so a second run of the same issue waits and never overlaps.
- A deterministic branch name and a lookup of the open PR, so repeated delegation reuses both instead of creating duplicates.

Agents can't overwrite each other: each pushes only its own branch, and the push is never forced.

How many run at once is set by **`AGENT_MAX_CONCURRENT`** (default **2**). The reconciler counts `agent-working` issues plus active runs, and starts the highest-priority queued work (remediations first) only while a slot is free. Change it any time:

```bash
gh variable set AGENT_MAX_CONCURRENT --body 3
```

Two ceilings sit above this setting:

- **GitHub:** this public repo is on GitHub Free, which allows at most **5 concurrent macOS jobs** across the repo ([Actions limits](https://docs.github.com/en/actions/reference/limits)). Each agent run takes one macOS job, and each PR's CI takes up to four (Lint, Test, Build, Screenshots). Above about 2 agents, CI starts queueing behind them. GitHub queues the extra jobs rather than failing them.
- **Claude:** your subscription's usage limits (rolling 5-hour windows plus weekly caps) are shared across every concurrent agent. When a run hits the limit, the agent posts "Paused: usage limit" and the issue is re-queued. **All** dispatching pauses for `AGENT_COOLDOWN_MINUTES` (default 60). Nothing falls back to the API, because no API key exists anywhere in this setup.

Retries are bounded everywhere:

| Limit | Default | Variable |
|---|---|---|
| Implementation attempts per issue | 2 | `AGENT_MAX_IMPL_ATTEMPTS` |
| Automatic remediations per PR (CI, review, conflict) | 3 | `AGENT_MAX_REMEDIATIONS` |
| Feedback rounds from you per PR | 5 | `AGENT_MAX_HUMAN_ROUNDS` |
| Identical failure after a fix | stop immediately | — |
| Agent turns: implement / review | 80 / 30 | `AGENT_MAX_TURNS`, `AGENT_REVIEW_MAX_TURNS` |
| Job timeout: implement / review | 100 / 30 min | workflow files |

Hitting any limit sets `needs-human` with an explanation. Runs that die without reporting (cancelled, runner lost) are detected after `AGENT_STALE_MINUTES` (default 20) and retried within the attempt limit.

## Approval and merging

Branch protection on `main` does the enforcing; the automation only prepares the PR.

- Required checks: **Lint, Test, Build, Policy, agent/review**, all on the PR's current head commit.
- Branches must be up to date with `main`. When another PR merges first, the reconciler updates the branch, and CI and review re-run before merge.
- **1 approval** required, stale approvals dismissed on new commits, and the most recent push must be approved by someone other than the pusher. A remediation after your approval therefore always needs a fresh approval.
- Auto-merge (squash) is enabled by the agent's GitHub App only after CI and review are green. GitHub merges the moment your approval lands, using `expectedHeadOid` so a commit pushed in between can't be merged unseen.
- The branch is deleted on merge, `Closes #N` closes the issue, and the board moves it to **Done**.

The agent's GitHub App can't approve PRs. It can't push to `main` (PRs are required), modify workflows (no Workflows permission), or post the `agent/review` status (no Statuses permission). The AI review is a required check, never a substitute for your approval.

> Trade-off: because the approval must come after the latest push, a PR updated after you approved (another PR merged first) needs another approval. To relax that, turn off **Require approval of the most recent reviewable push** in branch protection. Stale approvals are still dismissed when the code changes.

## Security model

| Risk | Control |
|---|---|
| Strangers triggering agents (public repo) | `agent-ready` counts only if applied by a write-access user (checked against the label event). Commands require write access. The official action also refuses runs from non-write actors and from bots other than `AGENT_BOT_LOGIN`. |
| Prompt injection through issues and comments | Only the issue body and comments from write-access users reach the agent. Prompts mark that text as data. The agent has a narrow tool allowlist (`--permission-mode acceptEdits`): no network tools, `gh`, `git push`, `env` or `curl`. |
| Credential theft by code the agent runs | The implement job holds only the OAuth token and a **read-only** `GITHUB_TOKEN`. `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` strips Anthropic, cloud and Actions secrets from every command Claude runs. No production credentials exist in this repo's CI. |
| Agent writes to the repo | Only the `publish` job (no Claude, no PR code executed) holds the App token. It runs the policy check, then pushes only `agent/issue-N`, never with force. |
| Agent weakening validation | The **Policy** check runs from the *base* commit's code. It fails agent PRs that touch protected paths (workflows, CLAUDE.md, Makefile, lint configs, signing, `scripts/`), remove tests, or add lint or test suppressions. The App has no Workflows permission, so GitHub itself rejects workflow edits. |
| Self-review | The reviewer is a separate session on a separate runner. It has read-only tools and gets the issue as the specification and the PR description as claims to verify. The pass/fail gate is deterministic code over its structured output. |
| Forged results | `agent/review` is honored only when posted by `github-actions[bot]`, and checks only when created by GitHub Actions. |
| Workflow injection | No `pull_request_target`. Untrusted strings (branch names, bodies) reach shell only through `env:`. Every third-party action is pinned to a commit SHA. Every job declares least-privilege `permissions:`. Orchestration code is always checked out from the default branch, never from a PR. |
| Runaway loops and cost | Bounded retries, signature-based repeat detection, a usage-limit cooldown, a global concurrency cap, per-job timeouts and an emergency stop. Events made by `GITHUB_TOKEN` don't trigger workflows, and the reconciler is idempotent. |
| Audit | Every transition is an issue or PR comment with a link to its run. All runs are in the Actions tab. |

Changes to authentication, secrets, workflows, permissions, branch protection or merge policy are protected paths. Make them yourself, in a human-authored PR.

**Public-repo note:** Actions logs and artifacts (task context, commit bundles; kept 7 days) are visible to anyone who can see the repo. They contain only what's already public: issue text and code. Never put secrets in issues.

**Pinned actions:** Dependabot (`.github/dependabot.yml`, weekly) opens PRs that bump the SHAs. Review the release notes of `anthropics/claude-code-action` before merging those, because they change the agent's behavior. Those PRs are human-reviewed; agents can't touch `.github/`.

## Costs

| Item | Cost |
|---|---|
| GitHub Actions | **$0.** Standard GitHub-hosted runners (including macOS) are free and unlimited for public repositories. If the repo is made private, macOS minutes bill at 10× and the free quota runs out quickly; reconsider `AGENT_MAX_CONCURRENT` and the 15-minute schedule then. |
| Claude | Comes out of your existing subscription's usage, with no API billing. A typical issue is one implementation (the largest share), one or two reviews, and zero to three remediations. Identical-diff re-reviews are skipped. A Max plan comfortably supports the default concurrency of 2; on Pro, use 1. |
| Artifacts and storage | Free for public repos; retained 7 days. |

Monitor Claude usage at claude.ai → **Settings → Usage**. Make sure **extra usage** (paid overage) is **off** if you never want charges beyond your plan. Monitor Actions at **Insights → Actions usage metrics**, or with `gh run list --workflow agent-implement.yml`.

## One-time setup

You do these steps yourself, because they involve credentials or account-level settings. Never paste tokens into chats or issues. `gh secret set` prompts for them.

1. **Claude token.** Run `claude setup-token` locally, then run `gh secret set CLAUDE_CODE_OAUTH_TOKEN` and paste the token at the hidden prompt.
2. **GitHub App** (the agent's identity). Open [this pre-filled form](https://github.com/settings/apps/new?name=snowflake-agent&description=Implements%20delegated%20Snowflake%20issues&url=https%3A%2F%2Fgithub.com%2FChrisC920%2FSnowflake&public=false&webhook_active=false&contents=write&pull_requests=write&issues=write). The name must be globally unique, so add a suffix if it's taken. Grant **only** these repository permissions: Contents (read and write), Pull requests (read and write), Issues (read and write). Metadata (read) is added automatically. Do **not** grant Workflows, Administration, Actions, Checks or Statuses. Then:
   - Create the app, click **Generate a private key**, and install the app on **only** `ChrisC920/Snowflake`.
   - `gh variable set AGENT_APP_CLIENT_ID --body <Client ID>`
   - `gh secret set AGENT_APP_PRIVATE_KEY < ~/Downloads/<app>.private-key.pem`, then delete the `.pem` file.
   - `gh variable set AGENT_BOT_LOGIN --body '<app-slug>[bot]'`
3. **Project sync** (optional but recommended). Create a [classic token with only the `project` scope](https://github.com/settings/tokens/new?scopes=project&description=Snowflake%20project%20sync), then run `gh secret set PROJECT_TOKEN`. Fine-grained tokens and GitHub Apps can't write to user-owned Projects. Set `gh variable set AGENT_PROJECT_NUMBER --body <n>`.
4. **Project board.** Created by `agentctl bootstrap`, with fields Status, Priority, Type, Agent, Effort and Iteration. In the project's **Workflows** settings, enable **Auto-add to project** (filter `is:issue`) and **Item closed → Done**. Create these views (the API can't create views):

   | View | Layout | Filter / group |
   |---|---|---|
   | Development board | Board | group by Status |
   | Prioritized backlog | Table | `status:Backlog,Ready` sort Priority |
   | Feature roadmap | Roadmap | `type:Feature,"New tool"` by Iteration |
   | Agent task queue | Table | `status:Queued,Blocked label:agent-ready` sort Priority |
   | Active development | Board | `status:"In Progress",Validation,"Changes Requested"` |
   | Awaiting approval | Table | `status:"In Review",Approved` |
   | Blocked | Table | `status:Blocked` |

5. **Repository settings and branch protection**, applied with `gh` and listed in [the setup PR](#verification-plan): allow auto-merge, allow update branch, required checks `Policy` and `agent/review`, and 1 approval with stale approvals dismissed and last-push approval required.

## Configuration reference

Repository variables (`gh variable set NAME --body VALUE`). Every one is optional except `AGENT_APP_CLIENT_ID` and `AGENT_BOT_LOGIN`.

| Variable | Default | Purpose |
|---|---|---|
| `AGENTS_PAUSED` | `false` | Emergency stop. |
| `AGENT_MAX_CONCURRENT` | `2` | Agent runs at once. |
| `AGENT_MAX_IMPL_ATTEMPTS` | `2` | Implementation attempts before `needs-human`. |
| `AGENT_MAX_REMEDIATIONS` | `3` | Automatic fix attempts per PR. |
| `AGENT_MAX_HUMAN_ROUNDS` | `5` | Fix rounds from your feedback per PR. |
| `AGENT_COOLDOWN_MINUTES` | `60` | Pause after a usage limit. |
| `AGENT_STALE_MINUTES` | `20` | When a silent run counts as interrupted. |
| `AGENT_MAX_TURNS` / `AGENT_REVIEW_MAX_TURNS` | `80` / `30` | Turn caps. |
| `AGENT_MODEL` / `AGENT_REVIEW_MODEL` | plan default | For example `claude-opus-5-5` for review and `claude-sonnet-5-5` for implementation. |
| `AGENT_REVIEW_BLOCKING` | `critical,high` | Severities that fail the review. |
| `AGENT_REVIEW_HUMAN_PRS` | `false` | Also AI-review your own PRs; otherwise their `agent/review` status is set to success. |
| `AGENT_REQUIRED_CHECKS` | `Lint,Test,Build,Policy` | Checks the gate waits for (keep in sync with branch protection). |
| `AGENT_PROJECT_NUMBER` / `AGENT_PROJECT_OWNER` | none / repo owner | Project to sync. |
| `AGENT_APP_CLIENT_ID` / `AGENT_BOT_LOGIN` | none | The GitHub App identity. |

Secrets: `CLAUDE_CODE_OAUTH_TOKEN`, `AGENT_APP_PRIVATE_KEY`, `PROJECT_TOKEN` (optional). There is no `ANTHROPIC_API_KEY`, and adding one isn't supported.

## Troubleshooting

| Symptom | Check |
|---|---|
| Labeled `agent-ready` but nothing happens | Actions → Agent Control: the latest run's summary shows slots, the queue and the reasons. Common causes: `AGENTS_PAUSED`, all slots busy, an open dependency (`blocked`), a usage-limit cooldown, or the label applied by someone without write access. |
| "Resource not accessible by integration" in publish | The GitHub App is missing Contents, Pull requests or Issues write, or isn't installed on the repo. |
| Push rejected in publish | Someone pushed to `agent/issue-N` meanwhile, or the change touched `.github/workflows` (the App can't). The issue is set to `needs-human` with the error. |
| PR stuck in Validation | Look at the PR's checks. If `agent/review` is missing, the reconciler re-dispatches it after 15 minutes. Fork PRs never get it; merge those as an admin after your own review. |
| `needs-human` after remediation | Read the comment. It names the limit, the repeated failure or the policy problem. Fix it or give guidance, then `/agent retry` or `@claude …`. |
| Approved but not merging | It's probably behind `main` (it updates and re-runs, then needs your re-approval) or a check is pending. Look at the PR's merge box. |
| Agent runs a lot slower than usual | Concurrent macOS jobs are capped at 5. Look at queued jobs in Actions. Lower `AGENT_MAX_CONCURRENT`. |
| Want to see what the agent did | The run log of Agent Implement shows Claude's steps. The commits on `agent/issue-N` are the result. |

Reconciler dry run locally: `GITHUB_REPOSITORY=ChrisC920/Snowflake GH_TOKEN=$(gh auth token) python3 .github/agent/agentctl.py reconcile --dry-run`. Unit tests: `python3 -m unittest discover -s .github/agent -p 'test_*.py'`.

## Verification plan

Run this once after setup, using throwaway issues labeled `testing` and `priority:low`. Each step lists what to observe. Close and delete the test branches afterwards.

1. **Delegation.** Create "Add a unit test asserting ModuleCatalog contains Keep Awake and Clipboard" and label it `agent-ready`. Expect: the issue gets **agent-working**, Agent Implement runs, a draft PR from `agent/issue-N` with `Closes #N` appears, the issue moves to **agent-validating**, and the PR gets CI plus an `agent/review` status.
2. **Parallelism.** Create two more small independent issues and label both. Expect two implement runs at once (concurrency 2), with the third queued in **Queued** until a slot frees.
3. **No duplicates.** Remove and re-add `agent-ready` on a running issue. Expect no second run and no second PR.
4. **Isolation.** Each run uses its own `agent/issue-N` branch, and the PRs list distinct branches.
5. **Gate.** When CI and review pass, the PR leaves draft, auto-merge is enabled, and you get the "ready for your approval" comment.
6. **Missing approval blocks merge.** Don't approve; the merge box shows the required review.
7. **Failure → remediation.** On an agent PR, comment `@claude make ModuleCatalogTests assert a module id that doesn't exist` (a deliberate failure). Expect Test to fail and a remediation to be queued and pushed. A second identical failure goes to `needs-human`, and the count never exceeds 3.
8. **Review findings → fix.** Request changes with a concrete comment. Expect a remediation commit and a re-review.
9. **Stale approval.** Approve, then push or trigger a remediation. Expect your approval dismissed, auto-merge waiting, and the issue back in Validation.
10. **Failed checks block merge.** With a red check, approving doesn't merge.
11. **Approve → merge.** Approve a green PR. Expect a squash merge, branch deletion, the issue closed and the card in Done.
12. **Dependencies.** Create B with `Depends on #A` and label it. Expect `blocked`; it starts after A closes.
13. **Unauthorized trigger.** From an account without write access (or have a friend try), comment `/agent retry` or `@claude`. Expect no reaction. A label from them isn't possible on a public repo.
14. **Usage limit.** You can't force this safely. The detection logic is unit-tested (`test_classify_execution`, `test_usage_limit_pauses_everything`). When it happens for real, expect a "Paused: usage limit" comment and no runs until the cooldown ends.
15. **Policy.** Create an issue asking to "update `.swiftlint.yml` to disable line_length" and delegate it. Expect `needs-human`, either because the agent refuses or because publish's policy check blocks the push.

## Extending: Codex and other agents

The orchestration is agent-agnostic. Only the `Run Claude` step in `agent-implement.yml` and `agent-review.yml` is Claude-specific. Its contract is a prompt file in, plus commits and a JSON result matching `schemas/*.json` out. To add OpenAI Codex as an implementer or a second reviewer:

- Add a step that runs Codex with the same prompt and writes the same JSON.
- Select it per issue with a label (for example `agent:codex`) read in `prepare-implement`.
- For a second opinion, post a separate status such as `agent/review-codex` and add it to the required checks.

`AGENTS.md` already points Codex at the shared rules in `CLAUDE.md`.
