#!/usr/bin/env python3
"""agentctl: deterministic orchestration for Snowflake's issue-to-PR agent workflow.

Every decision that gates progress (who may delegate, when an agent starts, whether a
PR passed review, when to remediate, when to stop) is made here, in plain code, never by
an agent. Claude only edits code and returns a structured report.

Standard library only (runs on GitHub-hosted runners and macOS's /usr/bin/python3 3.9).
See docs/AGENT_WORKFLOW.md for the full design.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

L_READY = "agent-ready"  # delegated by a maintainer; queued
L_WORKING = "agent-working"  # an implementation or remediation run is active
L_VALIDATING = "agent-validating"  # PR open; CI and AI review running
L_FIX = "auto-fix"  # remediation queued (CI, AI review, or human feedback)
L_REVIEW = "agent-review"  # validated; waiting for human approval
L_APPROVED = "agent-approved"  # human approved the current head; auto-merge pending
L_HUMAN = "needs-human"  # agent stopped; a human must act
L_BLOCKED = "blocked"  # waiting on dependencies
L_HUMAN_ONLY = "human-only"  # never delegate

STATE_LABELS = [L_READY, L_WORKING, L_VALIDATING, L_FIX, L_REVIEW, L_APPROVED]
PRIORITY_LABELS = {"priority:high": "High", "priority:medium": "Medium", "priority:low": "Low"}
PRIORITY_RANK = {"priority:high": 0, "priority:medium": 1, "priority:low": 2}
TYPE_LABELS = {
    "enhancement": "Feature",
    "module": "New tool",
    "bug": "Bug",
    "refactor": "Refactor",
    "testing": "Testing",
    "docs": "Documentation",
    "documentation": "Documentation",
    "tech-debt": "Tech debt",
}

# Every label the workflow relies on. `bootstrap` creates missing ones and leaves
# existing labels (bug, enhancement, docs, module, ...) untouched.
LABELS = {
    L_READY: ("0E8A16", "Delegated to an agent: queued for implementation"),
    L_WORKING: ("FBCA04", "An agent is implementing or fixing this now"),
    L_VALIDATING: ("C5DEF5", "Agent PR open: CI and AI review running"),
    L_FIX: ("D93F0B", "Agent remediation queued (CI, AI review or your feedback)"),
    L_REVIEW: ("5319E7", "Validated agent PR is waiting for your approval"),
    L_APPROVED: ("2DA44E", "You approved the agent PR: auto-merge pending"),
    L_HUMAN: ("B60205", "Agent stopped: a human decision or fix is needed"),
    L_BLOCKED: ("6A737D", "Waiting on another issue (Depends on #N)"),
    L_HUMAN_ONLY: ("0B3D91", "Never delegate this to an agent"),
    "priority:high": ("B60205", "Do first"),
    "priority:medium": ("FBCA04", "Normal priority"),
    "priority:low": ("C2E0C6", "When there's time"),
    "refactor": ("BFD4F2", "Restructure code without changing behavior"),
    "testing": ("BFDADC", "Tests and test infrastructure"),
    "tech-debt": ("D4C5F9", "Cleanup that pays down technical debt"),
    "enhancement": ("5AB0F0", "New feature or improvement"),
    "bug": ("E8A25A", "Something isn't working"),
    "docs": ("6FD3C1", "Documentation"),
}

STATUSES = [
    "Backlog",
    "Ready",
    "Queued",
    "In Progress",
    "Validation",
    "In Review",
    "Changes Requested",
    "Blocked",
    "Approved",
    "Done",
]
# Statuses only the automation sets; an issue in one of these with no agent label is reset to Ready.
AGENT_MANAGED_STATUSES = {"Queued", "In Progress", "Validation", "Changes Requested", "In Review", "Approved"}

BRANCH_PREFIX = "agent/issue-"
REVIEW_CONTEXT = "agent/review"
CONTEXT_DIR = ".agent-context"

# Paths an agent PR may not touch. Changes here need a human-authored PR.
PROTECTED_PATHS = [
    ".github/**",
    ".claude/**",
    "CLAUDE.md",
    "AGENTS.md",
    "Makefile",
    "Brewfile",
    ".swiftlint.yml",
    ".swiftformat",
    ".editorconfig",
    ".gitignore",
    "Config/**",
    "Snowflake/Snowflake.entitlements",
    "scripts/**",
    "SECURITY.md",
    "LICENSE",
    "CODEOWNERS",
]
SUPPRESSION_RE = re.compile(r"(swiftlint:disable|swiftformat:disable|XCTSkip|\.disabled\(|@available\(\*,\s*unavailable)")
TEST_DECL_RE = re.compile(r"^\s*(?:@Test\b|(?:override\s+)?func\s+test\w*\s*\()", re.M)

USAGE_LIMIT_RE = re.compile(
    r"(usage limit|rate[ _-]?limit|limit reached|limit will reset|resets at|exceeded your|"
    r"quota|\b429\b|too many requests|credit balance|out of (?:extra )?usage)",
    re.I,
)

MARKER_RE = re.compile(r"<!-- agentctl (\{.*?\}) -->", re.S)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def now():
    return datetime.now(timezone.utc)


def parse_time(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def log(msg):
    print(msg, flush=True)


def notice(msg):
    print("::notice::" + msg.replace("\n", " "), flush=True)


def warn(msg):
    print("::warning::" + msg.replace("\n", " "), flush=True)


def set_output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    value = str(value)
    if not path:
        log("output %s=%s" % (name, value))
        return
    with open(path, "a") as f:
        if "\n" in value:
            delim = "EOF_" + hashlib.sha1(value.encode()).hexdigest()
            f.write("%s<<%s\n%s\n%s\n" % (name, delim, value, delim))
        else:
            f.write("%s=%s\n" % (name, value))


def summary(md):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(md + "\n")


def marker(kind, **data):
    payload = dict(data)
    payload["kind"] = kind
    return "<!-- agentctl %s -->" % json.dumps(payload, separators=(",", ":"), sort_keys=True)


def b64(obj):
    return base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()


def unb64(s):
    try:
        return json.loads(base64.b64decode(s.encode()).decode())
    except Exception:
        return None


def truncate(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[: limit - 40] + "\n\n…(truncated)…\n"


def label_names(item):
    return {l["name"] if isinstance(l, dict) else l for l in item.get("labels", [])}


def issue_for_branch(ref):
    m = re.match(r"^agent/issue-(\d+)$", ref or "")
    return int(m.group(1)) if m else None


def is_protected(path):
    for pat in PROTECTED_PATHS:
        if pat.endswith("/**"):
            if path.startswith(pat[:-2]):
                return True
        elif path == pat:
            return True
    return False


def parse_dependencies(body):
    """Issue numbers this issue depends on, from the form's Dependencies section or
    'Depends on #12' / 'Blocked by #12' lines."""
    body = body or ""
    texts = []
    m = re.search(r"(?ims)^###\s*Dependencies\s*$(.*?)(?=^###\s|\Z)", body)
    if m:
        texts.append(m.group(1))
    texts += re.findall(r"(?im)^\s*(?:[-*]\s*)?(?:depends on|blocked by)\b\s*:?(.*)$", body)
    deps = set()
    for t in texts:
        for n in re.findall(r"(?<![\w/])#(\d+)\b", t):
            deps.add(int(n))
    return sorted(deps)


def form_priority(body):
    """'priority:high' etc. from the issue form's Priority dropdown, or None."""
    m = re.search(r"(?ims)^###\s*Priority\s*$\s*(High|Medium|Low)\b", body or "")
    return "priority:" + m.group(1).lower() if m else None


def desired_status(labels, state, current):
    if state == "closed":
        return "Done"
    if L_APPROVED in labels:
        return "Approved"
    if L_HUMAN in labels or L_BLOCKED in labels:
        return "Blocked"
    if L_WORKING in labels:
        return "In Progress"
    if L_FIX in labels:
        return "Changes Requested"
    if L_REVIEW in labels:
        return "In Review"
    if L_VALIDATING in labels:
        return "Validation"
    if L_READY in labels:
        return "Queued"
    if current in AGENT_MANAGED_STATUSES:
        return "Ready"
    return current or "Backlog"


def priority_key(issue):
    labels = label_names(issue)
    rank = min([PRIORITY_RANK[l] for l in labels if l in PRIORITY_RANK] or [1])
    return (rank, issue["number"])


def classify_execution(text):
    """'usage_limit' if the Claude run stopped on a subscription or rate limit.

    Only the final error result is inspected, so code that merely mentions rate limits
    (say, a feature implementing one) can't be mistaken for a limit."""
    text = text or ""
    try:
        msgs = json.loads(text)
    except ValueError:
        msgs = None
    if isinstance(msgs, list) and msgs:
        results = [m for m in msgs if isinstance(m, dict) and m.get("type") == "result"]
        if results:
            r = results[-1]
            if r.get("is_error") or str(r.get("subtype", "")).startswith("error"):
                return "usage_limit" if USAGE_LIMIT_RE.search(json.dumps(r)) else None
            return None
        blob = json.dumps(msgs[-3:])
    else:
        blob = text[-3000:]
    return "usage_limit" if USAGE_LIMIT_RE.search(blob) else None


def review_verdict(result, blocking_severities):
    """Deterministic gate over the reviewer's structured output.
    Returns (state, description, blocking_findings)."""
    if not isinstance(result, dict) or "verdict" not in result:
        return "error", "AI review returned no structured result", []
    findings = result.get("findings") or []
    blocking = [f for f in findings if str(f.get("severity", "")).lower() in blocking_severities]
    unmet = [c for c in (result.get("acceptance_criteria") or []) if c.get("met") is False]
    verdict = result.get("verdict")
    if verdict == "needs_human":
        return "failure", "Reviewer needs a human decision", blocking
    if blocking or unmet or verdict != "approve":
        parts = []
        if blocking:
            parts.append("%d blocking finding(s)" % len(blocking))
        if unmet:
            parts.append("%d unmet acceptance criteria" % len(unmet))
        if not parts:
            parts.append("changes requested")
        return "failure", ", ".join(parts), blocking + [
            {"severity": "high", "title": "Unmet acceptance criterion: " + str(c.get("criterion", ""))[:200]} for c in unmet
        ]
    return "success", "AI review passed (%d non-blocking note(s))" % len(findings), []


def failure_signature(names):
    return hashlib.sha256("\n".join(sorted(set(names))).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class Config:
    def __init__(self, env=None):
        e = env if env is not None else os.environ
        self.repo = e.get("GITHUB_REPOSITORY", "")
        self.owner = self.repo.split("/")[0] if self.repo else ""
        self.api = e.get("GITHUB_API_URL", "https://api.github.com")
        self.server = e.get("GITHUB_SERVER_URL", "https://github.com")
        self.run_id = e.get("GITHUB_RUN_ID", "")
        self.run_url = "%s/%s/actions/runs/%s" % (self.server, self.repo, self.run_id) if self.run_id else ""
        self.token = e.get("GH_TOKEN") or e.get("GITHUB_TOKEN", "")
        self.app_token = e.get("APP_TOKEN", "")
        self.project_token = e.get("PROJECT_TOKEN", "")
        self.bot_login = e.get("AGENT_BOT_LOGIN", "").strip()
        self.paused = e.get("AGENTS_PAUSED", "").strip().lower() in ("1", "true", "yes", "on")
        self.max_concurrent = int(e.get("AGENT_MAX_CONCURRENT") or 2)
        self.max_impl_attempts = int(e.get("AGENT_MAX_IMPL_ATTEMPTS") or 2)
        self.max_remediations = int(e.get("AGENT_MAX_REMEDIATIONS") or 3)
        self.max_human_rounds = int(e.get("AGENT_MAX_HUMAN_ROUNDS") or 5)
        self.cooldown = timedelta(minutes=int(e.get("AGENT_COOLDOWN_MINUTES") or 60))
        self.stale_after = timedelta(minutes=int(e.get("AGENT_STALE_MINUTES") or 20))
        self.project_number = e.get("AGENT_PROJECT_NUMBER", "").strip()
        self.project_owner = e.get("AGENT_PROJECT_OWNER", "").strip() or self.owner
        self.required_checks = [c.strip() for c in (e.get("AGENT_REQUIRED_CHECKS") or "Lint,Test,Build,Policy").split(",") if c.strip()]
        self.review_human_prs = e.get("AGENT_REVIEW_HUMAN_PRS", "").strip().lower() == "true"
        self.max_turns = int(e.get("AGENT_MAX_TURNS") or 80)
        self.review_max_turns = int(e.get("AGENT_REVIEW_MAX_TURNS") or 30)
        self.model = e.get("AGENT_MODEL", "").strip()
        self.review_model = e.get("AGENT_REVIEW_MODEL", "").strip() or self.model
        self.blocking = {s.strip().lower() for s in (e.get("AGENT_REVIEW_BLOCKING") or "critical,high").split(",") if s.strip()}

    @property
    def trusted_bots(self):
        bots = {"github-actions[bot]"}
        if self.bot_login:
            bots.add(self.bot_login)
        return bots


# ---------------------------------------------------------------------------
# GitHub API (urllib; no third-party dependencies)
# ---------------------------------------------------------------------------


class GitHubError(Exception):
    def __init__(self, status, message):
        super().__init__("GitHub API %s: %s" % (status, message))
        self.status = status
        self.message = message


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GitHub:
    def __init__(self, token, cfg):
        self.token = token
        self.cfg = cfg
        self.repo_path = "/repos/" + cfg.repo
        self._perm_cache = {}

    def request(self, method, path, body=None, params=None, accept="application/vnd.github+json"):
        url = path if path.startswith("http") else self.cfg.api + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", accept)
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "agentctl")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    raw = resp.read()
                    link = resp.headers.get("Link", "")
                    if not raw:
                        return None, link
                    ctype = resp.headers.get("Content-Type", "")
                    return (json.loads(raw) if "json" in ctype else raw.decode("utf-8", "replace")), link
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
                if e.code in (502, 503, 504) or (e.code == 403 and "secondary rate limit" in text.lower()):
                    time.sleep(2 ** attempt * 3)
                    continue
                try:
                    msg = json.loads(text).get("message", text)
                except Exception:
                    msg = text
                raise GitHubError(e.code, msg)
            except urllib.error.URLError:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt * 3)
        raise GitHubError(0, "retries exhausted")

    def r(self, path):
        return self.repo_path + path

    def paginate(self, path, limit=1000, **params):
        params.setdefault("per_page", 100)
        url = self.cfg.api + path + "?" + urllib.parse.urlencode(params)
        out = []
        while url and len(out) < limit:
            data, link = self.request("GET", url)
            if isinstance(data, dict):  # e.g. check-runs, workflow runs
                key = next((k for k, v in data.items() if isinstance(v, list)), None)
                data = data.get(key, []) if key else []
            out.extend(data or [])
            m = re.search(r'<([^>]+)>;\s*rel="next"', link or "")
            url = m.group(1) if m else None
        return out

    def graphql(self, query, variables=None):
        data, _ = self.request("POST", self.cfg.api.rstrip("/") + "/graphql", {"query": query, "variables": variables or {}})
        if data.get("errors"):
            raise GitHubError(200, "; ".join(e.get("message", "?") for e in data["errors"]))
        return data["data"]

    # --- repo helpers -------------------------------------------------------

    def issue(self, n):
        return self.request("GET", self.r("/issues/%d" % n))[0]

    def pull(self, n):
        return self.request("GET", self.r("/pulls/%d" % n))[0]

    def comments(self, n):
        return self.paginate(self.r("/issues/%d/comments" % n))

    def comment(self, n, body):
        log("comment on #%d" % n)
        return self.request("POST", self.r("/issues/%d/comments" % n), {"body": body})[0]

    def add_labels(self, n, labels):
        labels = [l for l in labels if l]
        if labels:
            self.request("POST", self.r("/issues/%d/labels" % n), {"labels": labels})

    def remove_label(self, n, label):
        try:
            self.request("DELETE", self.r("/issues/%d/labels/%s" % (n, urllib.parse.quote(label, safe=""))))
        except GitHubError as e:
            if e.status != 404:
                raise

    def set_state_labels(self, n, current, add=(), remove=()):
        """Move an issue between agent states with the fewest API calls."""
        current = set(current)
        for l in remove:
            if l in current:
                self.remove_label(n, l)
        missing = [l for l in add if l not in current]
        self.add_labels(n, missing)
        log("#%d labels: +%s -%s" % (n, ",".join(add) or "-", ",".join(l for l in remove if l in current) or "-"))

    def permission(self, login):
        if login in self._perm_cache:
            return self._perm_cache[login]
        try:
            data = self.request("GET", self.r("/collaborators/%s/permission" % urllib.parse.quote(login)))[0]
            perm = data.get("permission", "none")
        except GitHubError:
            perm = "none"
        self._perm_cache[login] = perm
        return perm

    def is_trusted_human(self, login):
        if not login or login.endswith("[bot]"):
            return False
        return self.permission(login) in ("admin", "maintain", "write")

    def markers(self, n, kinds=None, comments=None):
        out = []
        for c in comments if comments is not None else self.comments(n):
            if (c.get("user") or {}).get("login") not in self.cfg.trusted_bots:
                continue
            for raw in MARKER_RE.findall(c.get("body") or ""):
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                if kinds and m.get("kind") not in kinds:
                    continue
                m["_at"] = parse_time(c["created_at"])
                m["_comment_id"] = c["id"]
                out.append(m)
        return out

    def branch_exists(self, branch):
        try:
            self.request("GET", self.r("/branches/%s" % urllib.parse.quote(branch, safe="")))
            return True
        except GitHubError as e:
            if e.status == 404:
                return False
            raise

    def open_agent_pr(self, issue_n):
        prs = self.paginate(self.r("/pulls"), state="open", head="%s:%s%d" % (self.cfg.owner, BRANCH_PREFIX, issue_n))
        return prs[0] if prs else None

    def dispatch_workflow(self, workflow, ref, inputs):
        self.request("POST", self.r("/actions/workflows/%s/dispatches" % workflow), {"ref": ref, "inputs": inputs})
        log("dispatched %s %s" % (workflow, json.dumps(inputs)))

    def active_runs(self, workflow):
        runs = []
        for status in ("queued", "in_progress", "waiting", "pending", "requested"):
            try:
                runs += self.paginate(self.r("/actions/workflows/%s/runs" % workflow), limit=200, status=status)
            except GitHubError as e:
                if e.status != 404:  # workflow not on the default branch yet
                    raise
        return runs

    def set_status(self, sha, state, description, target_url=""):
        body = {"state": state, "context": REVIEW_CONTEXT, "description": description[:139]}
        if target_url:
            body["target_url"] = target_url
        self.request("POST", self.r("/statuses/%s" % sha), body)
        log("status %s on %s: %s" % (state, sha[:7], description))

    def job_log_tail(self, job_id, lines=150):
        """Download an Actions job log without forwarding our token to the storage redirect."""
        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(self.cfg.api + self.r("/actions/jobs/%d/logs" % job_id))
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("Accept", "application/vnd.github+json")
        try:
            opener.open(req, timeout=60)
            return ""
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.code in (301, 302, 303, 307) else None
            if not loc:
                return ""
        try:
            with urllib.request.urlopen(loc, timeout=60) as resp:
                text = resp.read().decode("utf-8", "replace")
        except Exception:
            return ""
        all_lines = [re.sub(r"^\S+Z ", "", l) for l in text.splitlines()]
        errors = [l for l in all_lines if re.search(r"(error|failed|failure|✘|violation)", l, re.I)][-60:]
        return "\n".join(["# error-looking lines"] + errors + ["", "# last %d lines" % lines] + all_lines[-lines:])


# ---------------------------------------------------------------------------
# PR state: checks, review status, approvals
# ---------------------------------------------------------------------------


def pr_check_state(gh, cfg, sha):
    """{name: 'success'|'failure'|'pending'|'missing'} for required checks + agent/review,
    plus check-run ids for failed ones."""
    runs = gh.paginate(gh.r("/commits/%s/check-runs" % sha), limit=300)
    latest = {}
    for run in runs:
        # Only trust check runs created by GitHub Actions (not by any app with checks:write).
        if (run.get("app") or {}).get("slug") != "github-actions":
            continue
        name = run["name"]
        if name not in latest or run["id"] > latest[name]["id"]:
            latest[name] = run
    state, failed_ids = {}, {}
    for name in cfg.required_checks:
        run = latest.get(name)
        if not run:
            state[name] = "missing"
        elif run["status"] != "completed":
            state[name] = "pending"
        elif run["conclusion"] in ("success", "neutral", "skipped"):
            state[name] = "success"
        else:
            state[name] = "failure"
            failed_ids[name] = run["id"]
    combined = gh.request("GET", gh.r("/commits/%s/status" % sha))[0] or {}
    review = next((s for s in combined.get("statuses", []) if s["context"] == REVIEW_CONTEXT), None)
    if review and (review.get("creator") or {}).get("login") != "github-actions[bot]":
        review = None  # ignore statuses not posted by our workflow
    if not review:
        state[REVIEW_CONTEXT] = "missing"
    else:
        state[REVIEW_CONTEXT] = {"success": "success", "pending": "pending"}.get(review["state"], "failure")
    return state, failed_ids, review


def human_reviews(gh, pr_number):
    """Latest decisive review per trusted human."""
    latest = {}
    for rv in gh.paginate(gh.r("/pulls/%d/reviews" % pr_number)):
        login = (rv.get("user") or {}).get("login", "")
        if rv["state"] not in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            continue
        if not gh.is_trusted_human(login):
            continue
        latest[login] = rv
    return list(latest.values())


def latest_review_record(gh, cfg, pr_number, comments=None):
    recs = gh.markers(pr_number, kinds={"review"}, comments=comments)
    return recs[-1] if recs else None


# ---------------------------------------------------------------------------
# Reconciler (agent-control workflow)
# ---------------------------------------------------------------------------


class Reconciler:
    def __init__(self, cfg, dry_run=False):
        self.cfg = cfg
        self.gh = GitHub(cfg.token, cfg)
        self.app = GitHub(cfg.app_token, cfg) if cfg.app_token else None
        self.dry = dry_run
        self.default_branch = None
        self.report = []

    def note(self, msg):
        log(msg)
        self.report.append("- " + msg)

    def run(self):
        repo = self.gh.request("GET", self.gh.repo_path)[0]
        self.default_branch = repo["default_branch"]
        if not self.app:
            warn("APP_TOKEN missing: PR updates, ready-for-review and auto-merge are skipped this run.")
        issues = [i for i in self.gh.paginate(self.gh.r("/issues"), state="open") if "pull_request" not in i]
        by_num = {i["number"]: i for i in issues}

        for issue in issues:
            want = form_priority(issue.get("body"))
            if want and not (label_names(issue) & set(PRIORITY_LABELS)) and not self.dry:
                self.gh.add_labels(issue["number"], [want])
                issue["labels"].append({"name": want})

        project = None
        if self.cfg.project_token and self.cfg.project_number:
            try:
                project = Project(self.cfg)
                self.apply_project_triggers(project, by_num)
            except Exception as e:  # project sync must never block delivery
                warn("Project read failed: %s" % e)
                project = None

        for pr in self.gh.paginate(self.gh.r("/pulls"), state="open"):
            same_repo = (pr["head"]["repo"] or {}).get("full_name") == self.cfg.repo
            n = issue_for_branch(pr["head"]["ref"]) if same_repo else None
            try:
                if n and by_num.get(n):
                    self.gate(pr, by_num[n])
                elif not n and same_repo and not self.cfg.review_human_prs:
                    self.mark_human_pr(pr)
            except GitHubError as e:
                warn("PR #%d: %s" % (pr["number"], e))

        if self.cfg.paused:
            notice("AGENTS_PAUSED is set: no new agent runs are dispatched.")
        else:
            self.recover_stale(by_num)
            self.dispatch(by_num)

        if project:
            try:
                issues = [i for i in self.gh.paginate(self.gh.r("/issues"), state="open") if "pull_request" not in i]
                project.sync(issues, self.gh, self.note)
            except Exception as e:
                warn("Project sync failed: %s" % e)
        if self.report:
            summary("### Agent reconcile\n" + "\n".join(self.report))

    # --- project → label trigger (move a card to Queued to delegate) -------

    def apply_project_triggers(self, project, by_num):
        for n, status in project.issue_statuses().items():
            issue = by_num.get(n)
            if not issue or status != "Queued":
                continue
            labels = label_names(issue)
            if labels & set(STATE_LABELS + [L_HUMAN, L_HUMAN_ONLY]):
                continue
            self.note("#%d moved to Queued on the project board: delegating" % n)
            self.gh.add_labels(n, [L_READY])
            issue["labels"].append({"name": L_READY})

    # --- PR gate -----------------------------------------------------------

    def gate(self, pr, issue):
        gh, cfg = self.gh, self.cfg
        n, prn = issue["number"], pr["number"]
        labels = label_names(issue)
        if labels & {L_WORKING, L_FIX, L_HUMAN, L_HUMAN_ONLY}:
            return  # an agent is on it, a fix is queued, or a human owns the next step
        pr = gh.pull(prn)  # fresh: mergeable_state, auto_merge, draft
        sha = pr["head"]["sha"]
        comments = gh.comments(prn)
        marks = gh.markers(prn, comments=comments)

        # 1. Human feedback: a trusted "Request changes" review on the current head.
        reviews = human_reviews(gh, prn)
        handled = {m.get("review_id") for m in marks if m["kind"] == "remediation-request"}
        for rv in reviews:
            if rv["state"] == "CHANGES_REQUESTED" and rv["id"] not in handled:
                self.request_remediation(issue, pr, "human", sha, marks, review_id=rv["id"])
                return

        state, failed_ids, review = pr_check_state(gh, cfg, sha)
        failing = sorted(k for k, v in state.items() if v == "failure")
        pending = sorted(k for k, v in state.items() if v in ("pending", "missing"))

        if "Policy" in failing:
            self.needs_human(issue, "policy-%s" % sha, "The **Policy** check failed on %s: the agent changed protected files, removed tests or added lint suppressions. A human must review this PR." % pr["html_url"], marks)
            return

        ci_failing = [f for f in failing if f != REVIEW_CONTEXT]
        if ci_failing:
            self.request_remediation(issue, pr, "ci", sha, marks, sig=failure_signature(ci_failing), failing=ci_failing)
            return
        if REVIEW_CONTEXT in failing and review and review["state"] == "error":
            # The review itself didn't complete: retry it rather than "fixing" the code.
            if "usage limit" in (review.get("description") or "").lower():
                self.retry_review_after_cooldown(pr, review)
                return
            retries = [m for m in marks if m["kind"] == "review-retry" and m.get("sha") == sha]
            if len(retries) >= 2:
                self.needs_human(issue, "review-error-%s" % sha, "The AI review failed to complete twice on `%s` (%s)." % (sha[:7], review.get("target_url") or "see Actions"), marks)
            elif not self.dry:
                self.gh.dispatch_workflow("agent-review.yml", self.default_branch, {"pr": str(prn)})
                self.gh.comment(prn, "Re-running the AI review (the last run errored).\n\n" + marker("review-retry", sha=sha))
            return
        if REVIEW_CONTEXT in failing:
            rec = latest_review_record(gh, cfg, prn, comments)
            findings = (unb64(rec.get("blocking", "")) if rec and rec.get("sha") == sha else None) or []
            names = ["review:" + str(f.get("title", ""))[:120] for f in findings] or ["review"]
            self.request_remediation(issue, pr, "review", sha, marks, sig=failure_signature(names), failing=["AI review"])
            return

        if REVIEW_CONTEXT in pending and state[REVIEW_CONTEXT] == "missing":
            self.ensure_review(pr, marks)
        if pending:
            self.relabel(issue, L_VALIDATING)
            return

        # All required checks and the AI review passed for this exact head SHA.
        ms = pr.get("mergeable_state")
        if ms == "dirty":
            self.request_remediation(issue, pr, "conflict", sha, marks, sig="conflict-" + sha)
            return
        if ms == "behind":
            if self.app and not self.dry:
                self.note("PR #%d is behind %s: updating the branch (CI and review re-run)" % (prn, self.default_branch))
                try:
                    self.app.request("PUT", gh.r("/pulls/%d/update-branch" % prn), {"expected_head_sha": sha})
                except GitHubError as e:
                    if e.status == 422 and "conflict" in e.message.lower():
                        self.request_remediation(issue, pr, "conflict", sha, marks, sig="conflict-" + sha)
                    else:
                        warn("update-branch #%d: %s" % (prn, e.message))
            self.relabel(issue, L_VALIDATING)
            return

        approved = [rv for rv in reviews if rv["state"] == "APPROVED" and rv.get("commit_id") == sha]
        if self.app and not self.dry:
            if pr.get("draft"):
                self.app.graphql("mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){clientMutationId}}", {"id": pr["node_id"]})
                self.note("PR #%d marked ready for review" % prn)
            if not pr.get("auto_merge"):
                try:
                    self.app.graphql(
                        "mutation($id:ID!,$sha:GitObjectID!){enablePullRequestAutoMerge(input:{pullRequestId:$id,mergeMethod:SQUASH,expectedHeadOid:$sha}){clientMutationId}}",
                        {"id": pr["node_id"], "sha": sha},
                    )
                    self.note("PR #%d: auto-merge (squash) enabled; it merges once you approve" % prn)
                except GitHubError as e:
                    if approved and "clean status" in e.message.lower():
                        # Everything (including your approval of this SHA) is already satisfied.
                        self.app.graphql(
                            "mutation($id:ID!,$sha:GitObjectID!){mergePullRequest(input:{pullRequestId:$id,mergeMethod:SQUASH,expectedHeadOid:$sha}){clientMutationId}}",
                            {"id": pr["node_id"], "sha": sha},
                        )
                        self.note("PR #%d merged (approved, all checks green on %s)" % (prn, sha[:7]))
                        return
                    warn("auto-merge #%d: %s" % (prn, e.message))
        if approved:
            self.relabel(issue, L_APPROVED)
        else:
            self.relabel(issue, L_REVIEW)
            if not any(m["kind"] == "ready" and m.get("sha") == sha for m in marks) and not self.dry:
                owner = self.cfg.owner
                gh.comment(
                    prn,
                    "✅ CI and the independent AI review passed on `%s`. @%s, this PR is ready for your approval; it merges automatically (squash) when you approve.\n\n%s"
                    % (sha[:7], owner, marker("ready", sha=sha)),
                )

    def mark_human_pr(self, pr):
        """Non-agent PRs (yours, Dependabot's) don't get an AI review unless AGENT_REVIEW_HUMAN_PRS
        is set; give them the required agent/review status so they aren't blocked. Your approval
        is still required for them."""
        sha = pr["head"]["sha"]
        combined = self.gh.request("GET", self.gh.r("/commits/%s/status" % sha))[0] or {}
        if any(st["context"] == REVIEW_CONTEXT for st in combined.get("statuses", [])):
            return
        if not self.dry:
            self.gh.set_status(sha, "success", "Not required for human-authored PRs", self.cfg.run_url)

    def relabel(self, issue, target):
        labels = label_names(issue)
        remove = [l for l in (L_VALIDATING, L_REVIEW, L_APPROVED) if l != target]
        if target in labels and not (labels & set(remove)):
            return
        if not self.dry:
            self.gh.set_state_labels(issue["number"], labels, add=[target], remove=remove)
        issue["labels"] = [{"name": l} for l in (labels - set(remove)) | {target}]

    def ensure_review(self, pr, marks):
        """Re-run a review that never posted a status (e.g. the run was skipped or cancelled)."""
        updated = parse_time(pr["updated_at"])
        if now() - updated < timedelta(minutes=15):
            return
        recent = [m for m in marks if m["kind"] == "review-retry" and m.get("sha") == pr["head"]["sha"]]
        if len(recent) >= 2 or self.dry:
            return
        self.gh.dispatch_workflow("agent-review.yml", self.default_branch, {"pr": str(pr["number"])})
        self.gh.comment(pr["number"], "Re-running the AI review (no result was recorded for this commit).\n\n" + marker("review-retry", sha=pr["head"]["sha"]))

    def retry_review_after_cooldown(self, pr, review):
        updated = parse_time(review["updated_at"])
        if now() - updated < self.cfg.cooldown or self.dry:
            return
        self.note("PR #%d: retrying the AI review after a usage-limit pause" % pr["number"])
        self.gh.set_status(pr["head"]["sha"], "pending", "Retrying AI review after usage limit", self.cfg.run_url)
        self.gh.dispatch_workflow("agent-review.yml", self.default_branch, {"pr": str(pr["number"])})

    def request_remediation(self, issue, pr, reason, sha, marks, sig="", failing=None, review_id=None, comment_id=None):
        n, prn = issue["number"], pr["number"]
        resets = [m["_at"] for m in self.gh.markers(n, kinds={"reset"})]
        since = max(resets) if resets else None
        reqs = [m for m in marks if m["kind"] == "remediation-request" and (since is None or m["_at"] > since)]
        if reason in ("ci", "review", "conflict") and any(m.get("sha") == sha and m.get("reason") == reason for m in reqs):
            # Already tried on this exact commit and the fix produced no new commit.
            self.needs_human(issue, "stuck-%s" % sha, "Remediation for `%s` on %s finished without producing a new commit. Stopping here." % (sha[:7], pr["html_url"]), marks)
            return
        auto = [m for m in reqs if m.get("reason") in ("ci", "review", "conflict")]
        human = [m for m in reqs if m.get("reason") == "human"]
        if reason in ("ci", "review", "conflict"):
            if len(auto) >= self.cfg.max_remediations:
                self.needs_human(issue, "limit-%s" % sha, "Reached the limit of %d automatic remediation attempts on %s (still failing: %s)." % (self.cfg.max_remediations, pr["html_url"], ", ".join(failing or [reason])), marks)
                return
            if sig and auto and auto[-1].get("sig") == sig:
                self.needs_human(issue, "repeat-%s" % sig, "The same failure (%s) came back after the last remediation on %s; another identical attempt is unlikely to help." % (", ".join(failing or [reason]), pr["html_url"]), marks)
                return
        elif len(human) >= self.cfg.max_human_rounds:
            self.needs_human(issue, "human-limit-%s" % sha, "Reached %d rounds of feedback-driven changes on %s." % (self.cfg.max_human_rounds, pr["html_url"]), marks)
            return
        if self.dry:
            self.note("[dry-run] would request %s remediation for PR #%d" % (reason, prn))
            return
        attempt = len(auto) + 1 if reason != "human" else len(human) + 1
        what = {
            "ci": "CI failed (%s)" % ", ".join(failing or []),
            "review": "the AI review requested changes",
            "conflict": "the branch conflicts with %s" % self.default_branch,
            "human": "a maintainer requested changes",
        }[reason]
        limit = self.cfg.max_remediations if reason != "human" else self.cfg.max_human_rounds
        self.gh.comment(
            prn,
            "🔧 Queued remediation %d/%d: %s on `%s`.\n\n%s"
            % (attempt, limit, what, sha[:7], marker("remediation-request", reason=reason, sha=sha, sig=sig, review_id=review_id, comment_id=comment_id)),
        )
        self.gh.set_state_labels(n, label_names(issue), add=[L_FIX], remove=[L_VALIDATING, L_REVIEW, L_APPROVED])
        issue["labels"] = [{"name": l} for l in (label_names(issue) - {L_VALIDATING, L_REVIEW, L_APPROVED}) | {L_FIX}]
        self.note("PR #%d: remediation queued (%s)" % (prn, reason))

    def needs_human(self, issue, key, message, marks=None):
        n = issue["number"]
        existing = marks if marks is not None else []
        existing = existing + self.gh.markers(n, kinds={"needs-human"})
        if any(m.get("key") == key for m in existing if m["kind"] == "needs-human"):
            return
        if self.dry:
            self.note("[dry-run] #%d needs a human: %s" % (n, message))
            return
        self.gh.comment(
            n,
            "🛑 **Needs a human.** %s\n\nWhen you've decided, comment `/agent retry` (start over, attempt counters reset) or `@claude <instructions>` to continue with guidance.\n\n%s"
            % (message, marker("needs-human", key=key)),
        )
        labels = label_names(issue)
        self.gh.set_state_labels(n, labels, add=[L_HUMAN], remove=[L_READY, L_WORKING, L_FIX, L_VALIDATING, L_REVIEW, L_APPROVED])
        issue["labels"] = [{"name": l} for l in (labels - set(STATE_LABELS)) | {L_HUMAN}]
        self.note("#%d → needs-human: %s" % (n, message))

    # --- stale run recovery --------------------------------------------------

    def active_issue_runs(self):
        active = {}
        for run in self.gh.active_runs("agent-implement.yml"):
            m = re.search(r"#(\d+)", run.get("display_title") or run.get("name") or "")
            if m:
                active[int(m.group(1))] = run
        return active

    def recover_stale(self, by_num):
        self._active = self.active_issue_runs()
        for n, issue in by_num.items():
            if L_WORKING not in label_names(issue) or n in self._active:
                continue
            starts = self.gh.markers(n, kinds={"run-start"})
            last = starts[-1]["_at"] if starts else parse_time(issue["updated_at"])
            if now() - last < self.cfg.stale_after:
                continue
            self.note("#%d is labeled agent-working but no run is active: treating the run as interrupted" % n)
            if self.dry:
                continue
            mode = starts[-1].get("mode") if starts else "implement"
            if mode == "remediate":
                self.gh.set_state_labels(n, label_names(issue), add=[L_VALIDATING], remove=[L_WORKING])
            else:
                self.gh.set_state_labels(n, label_names(issue), add=[L_READY], remove=[L_WORKING])
                issue["labels"] = [{"name": l} for l in (label_names(issue) - {L_WORKING}) | {L_READY}]
            self.gh.comment(n, "⚠️ The last agent run ended without reporting back (cancelled, timed out or the runner was lost). It will be retried if attempts remain.\n\n" + marker("interrupted"))

    # --- dispatcher ------------------------------------------------------------

    def usage_paused_until(self):
        since = (now() - self.cfg.cooldown).strftime("%Y-%m-%dT%H:%M:%SZ")
        latest = None
        for c in self.gh.paginate(self.gh.r("/issues/comments"), limit=500, since=since, sort="created", direction="desc"):
            if (c.get("user") or {}).get("login") not in self.cfg.trusted_bots:
                continue
            if '"kind":"usage-limit"' in (c.get("body") or ""):
                t = parse_time(c["created_at"])
                latest = t if latest is None or t > latest else latest
        return latest + self.cfg.cooldown if latest else None

    def dispatch(self, by_num):
        cfg, gh = self.cfg, self.gh
        active = getattr(self, "_active", None) or self.active_issue_runs()
        working = {n for n, i in by_num.items() if L_WORKING in label_names(i)} | set(active)
        slots = cfg.max_concurrent - len(working)
        remediations = sorted([i for i in by_num.values() if L_FIX in label_names(i) and L_WORKING not in label_names(i)], key=priority_key)
        ready = sorted(
            [i for i in by_num.values() if L_READY in label_names(i) and not (label_names(i) & {L_WORKING, L_FIX, L_VALIDATING, L_REVIEW, L_APPROVED})],
            key=priority_key,
        )
        if not remediations and not ready:
            return
        paused_until = self.usage_paused_until()
        if paused_until and paused_until > now():
            self.note("Claude usage limit hit recently: dispatch paused until %s UTC (AGENT_COOLDOWN_MINUTES)" % paused_until.strftime("%H:%M"))
            return
        self.note("Agent slots: %d of %d free; %d remediation(s) and %d issue(s) queued" % (max(slots, 0), cfg.max_concurrent, len(remediations), len(ready)))

        for issue in remediations:
            if slots <= 0:
                break
            if self.start_remediation(issue):
                slots -= 1
        for issue in ready:
            if slots <= 0:
                break
            if self.start_implementation(issue, by_num):
                slots -= 1

    def labeler_is_trusted(self, n, label):
        events = self.gh.paginate(self.gh.r("/issues/%d/events" % n), limit=1000)
        actor = None
        for ev in events:
            if ev.get("event") == "labeled" and (ev.get("label") or {}).get("name") == label:
                actor = (ev.get("actor") or {}).get("login")
        if actor in self.cfg.trusted_bots:
            return True, actor
        return self.gh.is_trusted_human(actor), actor

    def start_implementation(self, issue, by_num):
        gh, cfg = self.gh, self.cfg
        n = issue["number"]
        labels = label_names(issue)
        if L_HUMAN_ONLY in labels:
            gh.remove_label(n, L_READY)
            gh.comment(n, "This issue is labeled `human-only`, so it was not delegated. Remove that label first if an agent should take it.")
            return False
        if L_HUMAN in labels:
            return False  # waiting for a human; /agent retry clears this
        trusted, actor = self.labeler_is_trusted(n, L_READY)
        if not trusted:
            gh.remove_label(n, L_READY)
            gh.comment(n, "`agent-ready` was applied by @%s, who doesn't have write access, so no agent was started." % (actor or "unknown"))
            self.note("#%d: ignored agent-ready from untrusted @%s" % (n, actor))
            return False

        deps = parse_dependencies(issue.get("body"))
        try:
            native = gh.paginate(gh.r("/issues/%d/dependencies/blocked_by" % n), limit=100)
            deps = sorted(set(deps) | {d["number"] for d in native})
        except GitHubError:
            pass
        open_deps = []
        for d in deps:
            if d == n:
                continue
            dep = by_num.get(d)
            if dep is None:
                try:
                    dep = gh.issue(d)
                except GitHubError:
                    continue
            if dep.get("state") == "open":
                open_deps.append(d)
        marks = gh.markers(n)
        if open_deps:
            if L_BLOCKED not in labels:
                gh.add_labels(n, [L_BLOCKED])
                gh.comment(n, "⏸️ Waiting on %s. This starts automatically once they're closed.\n\n%s" % (", ".join("#%d" % d for d in open_deps), marker("deps", deps=open_deps)))
                self.note("#%d blocked on %s" % (n, open_deps))
            return False
        if L_BLOCKED in labels and any(m["kind"] == "deps" for m in marks):
            gh.remove_label(n, L_BLOCKED)  # only auto-clear blocks we added

        resets = [m["_at"] for m in marks if m["kind"] == "reset"]
        since = max(resets) if resets else None
        recent = [m for m in marks if since is None or m["_at"] > since]
        limits = [m for m in recent if m["kind"] == "usage-limit"]
        if limits and now() - limits[-1]["_at"] < cfg.cooldown:
            return False
        attempts = [m for m in recent if m["kind"] == "run-start" and m.get("mode") == "implement"]
        if len(attempts) >= cfg.max_impl_attempts:
            self.needs_human(issue, "impl-limit-%d" % len(attempts), "Reached the limit of %d implementation attempts." % cfg.max_impl_attempts, marks)
            return False

        if self.dry:
            self.note("[dry-run] would start implementation for #%d" % n)
            return True
        gh.set_state_labels(n, label_names(issue), add=[L_WORKING], remove=[L_READY, L_BLOCKED])
        gh.comment(
            n,
            "🤖 Agent started (attempt %d/%d). Branch: `%s%d`.\n\n%s"
            % (len(attempts) + 1, cfg.max_impl_attempts, BRANCH_PREFIX, n, marker("run-start", mode="implement")),
        )
        gh.dispatch_workflow("agent-implement.yml", self.default_branch, {"issue": str(n), "mode": "implement", "request": "0"})
        self.note("#%d: implementation started" % n)
        return True

    def start_remediation(self, issue):
        gh = self.gh
        n = issue["number"]
        pr = gh.open_agent_pr(n)
        if not pr:
            gh.remove_label(n, L_FIX)
            self.note("#%d had auto-fix but no open agent PR: cleared" % n)
            return False
        marks = gh.markers(pr["number"])
        started = {m.get("request") for m in gh.markers(n, kinds={"run-start"})}
        reqs = [m for m in marks if m["kind"] == "remediation-request" and m["_comment_id"] not in started]
        if not reqs:
            if self.dry:
                return False
            # auto-fix added by hand: remediate whatever is failing on the current head.
            body = gh.comment(pr["number"], "🔧 Remediation requested via the `auto-fix` label.\n\n" + marker("remediation-request", reason="manual", sha=pr["head"]["sha"], sig=""))
            req_id = body["id"]
        else:
            req = reqs[-1]
            if req.get("sha") != pr["head"]["sha"] and req.get("reason") != "human":
                gh.set_state_labels(n, label_names(issue), add=[L_VALIDATING], remove=[L_FIX])
                self.note("#%d: remediation request is for an old commit; re-validating instead" % n)
                return False
            req_id = req["_comment_id"]
        if self.dry:
            self.note("[dry-run] would start remediation for #%d" % n)
            return True
        gh.set_state_labels(n, label_names(issue), add=[L_WORKING], remove=[L_FIX])
        gh.comment(n, "🤖 Remediation started on %s.\n\n%s" % (pr["html_url"], marker("run-start", mode="remediate", request=req_id)))
        gh.dispatch_workflow("agent-implement.yml", self.default_branch, {"issue": str(n), "mode": "remediate", "request": str(req_id)})
        self.note("#%d: remediation started" % n)
        return True


# ---------------------------------------------------------------------------
# GitHub Projects (v2) sync — needs a classic PAT with `project` scope (PROJECT_TOKEN)
# ---------------------------------------------------------------------------


class Project:
    def __init__(self, cfg):
        self.cfg = cfg
        self.gh = GitHub(cfg.project_token, cfg)
        q = """query($login:String!,$num:Int!){ user(login:$login){ projectV2(number:$num){ id
              fields(first:50){ nodes{ ... on ProjectV2FieldCommon{ id name dataType }
                                       ... on ProjectV2SingleSelectField{ options{ id name } } } } } } }"""
        data = self.gh.graphql(q, {"login": cfg.project_owner, "num": int(cfg.project_number)})
        proj = (data.get("user") or {}).get("projectV2")
        if not proj:
            raise GitHubError(404, "project %s/%s not found" % (cfg.project_owner, cfg.project_number))
        self.id = proj["id"]
        self.fields = {f["name"]: f for f in proj["fields"]["nodes"] if f}
        self._items = None

    def items(self):
        if self._items is not None:
            return self._items
        out, cursor = {}, None
        q = """query($id:ID!,$after:String){ node(id:$id){ ... on ProjectV2{ items(first:100, after:$after){
                 pageInfo{ hasNextPage endCursor }
                 nodes{ id content{ ... on Issue{ number repository{ nameWithOwner } } }
                        fieldValues(first:20){ nodes{ ... on ProjectV2ItemFieldSingleSelectValue{ name field{ ... on ProjectV2FieldCommon{ name } } } } } } } } } }"""
        while True:
            data = self.gh.graphql(q, {"id": self.id, "after": cursor})
            page = data["node"]["items"]
            for node in page["nodes"]:
                c = node.get("content") or {}
                if c.get("repository", {}).get("nameWithOwner") != self.cfg.repo:
                    continue
                values = {v["field"]["name"]: v["name"] for v in node["fieldValues"]["nodes"] if v and v.get("field")}
                out[c["number"]] = {"id": node["id"], "values": values}
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        self._items = out
        return out

    def issue_statuses(self):
        return {n: it["values"].get("Status") for n, it in self.items().items()}

    def set_select(self, item_id, field_name, option_name):
        field = self.fields.get(field_name)
        if not field or "options" not in field:
            return False
        opt = next((o for o in field["options"] if o["name"] == option_name), None)
        if not opt:
            return False
        self.gh.graphql(
            "mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){clientMutationId}}",
            {"p": self.id, "i": item_id, "f": field["id"], "o": opt["id"]},
        )
        return True

    def sync(self, open_issues, repo_gh, note):
        items = self.items()
        # Closed issues still on the board → Done (the built-in "Item closed" workflow also does this).
        for n, it in items.items():
            if it["values"].get("Status") not in (None, "Done") and n not in {i["number"] for i in open_issues}:
                try:
                    issue = repo_gh.issue(n)
                except GitHubError:
                    continue
                if issue.get("state") == "closed":
                    self.set_select(it["id"], "Status", "Done")
        for issue in open_issues:
            n = issue["number"]
            it = items.get(n)
            if not it:
                data = self.gh.graphql(
                    "mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}",
                    {"p": self.id, "c": issue["node_id"]},
                )
                it = {"id": data["addProjectV2ItemById"]["item"]["id"], "values": {}}
                items[n] = it
                note("#%d added to the project" % n)
            labels = label_names(issue)
            want = {"Status": desired_status(labels, issue["state"], it["values"].get("Status"))}
            pr = [PRIORITY_LABELS[l] for l in labels if l in PRIORITY_LABELS]
            if pr:
                want["Priority"] = pr[0]
            ty = [TYPE_LABELS[l] for l in labels if l in TYPE_LABELS]
            if ty:
                want["Type"] = ty[0]
            if labels & set(STATE_LABELS + [L_HUMAN]):
                want["Agent"] = "Claude"
            elif L_HUMAN_ONLY in labels:
                want["Agent"] = "Human"
            for field, value in want.items():
                if it["values"].get(field) != value and self.set_select(it["id"], field, value):
                    if field == "Status":
                        note("#%d: Status %s → %s" % (n, it["values"].get("Status") or "(none)", value))
                    it["values"][field] = value


# ---------------------------------------------------------------------------
# Commands from trusted comments: /agent retry | cancel | status, @claude <feedback>
# ---------------------------------------------------------------------------


def cmd_command(cfg, args):
    gh = GitHub(cfg.token, cfg)
    event = json.load(open(os.environ["GITHUB_EVENT_PATH"]))
    comment = event["comment"]
    issue_obj = event["issue"]
    login = comment["user"]["login"]
    body = comment.get("body") or ""
    if not gh.is_trusted_human(login):
        log("ignoring comment from @%s (no write access)" % login)
        return 0
    first = body.strip().splitlines()[0].strip().lower() if body.strip() else ""
    is_pr = "pull_request" in issue_obj
    number = issue_obj["number"]
    issue_n, pr = number, None
    if is_pr:
        pr = gh.pull(number)
        same_repo = (pr["head"]["repo"] or {}).get("full_name") == cfg.repo
        issue_n = issue_for_branch(pr["head"]["ref"]) if same_repo else None
        if not issue_n:
            log("comment on a non-agent PR; nothing to do")
            return 0
    else:
        pr = gh.open_agent_pr(number)
    issue = gh.issue(issue_n)
    labels = label_names(issue)

    def react(content):
        try:
            gh.request("POST", gh.r("/issues/comments/%d/reactions" % comment["id"]), {"content": content})
        except GitHubError:
            pass

    if first.startswith("/agent retry"):
        react("rocket")
        gh.comment(issue_n, "↩️ Retry requested by @%s: attempt counters reset.\n\n%s" % (login, marker("reset", by=login)))
        if pr:
            gh.set_state_labels(issue_n, labels, add=[L_VALIDATING], remove=[L_HUMAN, L_FIX, L_REVIEW, L_APPROVED, L_READY])
        else:
            gh.set_state_labels(issue_n, labels, add=[L_READY], remove=[L_HUMAN, L_VALIDATING, L_FIX])
    elif first.startswith("/agent cancel"):
        react("-1")
        for run in gh.active_runs("agent-implement.yml"):
            if re.search(r"#%d\b" % issue_n, run.get("display_title") or ""):
                try:
                    gh.request("POST", gh.r("/actions/runs/%d/cancel" % run["id"]))
                except GitHubError as e:
                    warn("cancel run %s: %s" % (run["id"], e))
        gh.set_state_labels(issue_n, labels, remove=STATE_LABELS + [L_BLOCKED])
        gh.comment(issue_n, "⏹️ Cancelled by @%s. Active agent runs were stopped and the issue left the agent queue. Any open PR stays open; add `agent-ready` or comment `/agent retry` to resume.\n\n%s" % (login, marker("cancel", by=login)))
    elif first.startswith("/agent status"):
        marks = gh.markers(issue_n)
        lines = ["**Agent status for #%d**" % issue_n, "", "- Labels: %s" % (", ".join(sorted(labels)) or "none")]
        if pr:
            lines.append("- PR: %s (head `%s`)" % (pr["html_url"], pr["head"]["sha"][:7]))
        lines.append("- Implementation runs: %d; remediation runs: %d" % (
            len([m for m in marks if m["kind"] == "run-start" and m.get("mode") == "implement"]),
            len([m for m in marks if m["kind"] == "run-start" and m.get("mode") == "remediate"]),
        ))
        lines.append("- Agents paused: %s" % ("yes" if cfg.paused else "no"))
        gh.comment(number, "\n".join(lines))
    elif re.search(r"(?<![\w-])@claude\b", body, re.I):
        react("eyes")
        if pr:
            Reconciler(cfg).request_remediation(issue, pr, "human", pr["head"]["sha"], gh.markers(pr["number"]), comment_id=comment["id"])
            gh.remove_label(issue_n, L_HUMAN)
        else:
            # Clarification on an issue: the next run reads every trusted comment.
            gh.set_state_labels(issue_n, labels, add=[L_READY], remove=[L_HUMAN])
            gh.comment(issue_n, "Thanks @%s, queued with your guidance.\n\n%s" % (login, marker("feedback", comment_id=comment["id"])))
    else:
        log("no command found")
        return 0
    # Let the reconciler act now instead of at the next schedule.
    repo = gh.request("GET", gh.repo_path)[0]
    gh.dispatch_workflow("agent-control.yml", repo["default_branch"], {})
    return 0


# ---------------------------------------------------------------------------
# Implementation job: prepare → (Claude) → finish → publish
# ---------------------------------------------------------------------------

IMPLEMENT_TOOLS = [
    "Read", "Edit", "MultiEdit", "Write", "Glob", "Grep", "LS", "TodoWrite", "Task",
    "Bash(make build)", "Bash(make test)", "Bash(make lint)", "Bash(make format)", "Bash(make generate)",
    "Bash(make screenshots:*)",
    "Bash(swift build:*)", "Bash(swift test:*)", "Bash(xcodegen generate)",
    "Bash(swiftlint:*)", "Bash(swiftformat:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git add:*)",
    "Bash(git commit:*)", "Bash(git rm:*)", "Bash(git mv:*)", "Bash(git restore:*)", "Bash(git merge:*)",
    "Bash(git checkout -- :*)", "Bash(git branch --show-current)", "Bash(git rev-parse:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)", "Bash(grep:*)", "Bash(find:*)",
    "Bash(mkdir:*)",
]
REVIEW_TOOLS = [
    "Read", "Glob", "Grep", "LS", "TodoWrite", "Task",
    "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git status:*)", "Bash(git merge-base:*)",
    "Bash(ls:*)", "Bash(wc:*)", "Bash(cat:*)",
]
ALWAYS_DENY = [
    "WebFetch", "WebSearch", "Bash(curl:*)", "Bash(wget:*)", "Bash(git push:*)", "Bash(git remote:*)",
    "Bash(git config:*)", "Bash(git reset --hard:*)", "Bash(git rebase:*)", "Bash(gh:*)", "Bash(sudo:*)",
    "Bash(rm -rf:*)", "Bash(env:*)", "Bash(printenv:*)", "Bash(ssh:*)", "Bash(scp:*)", "Bash(nc:*)",
]


def claude_args(cfg, schema_file, tools, deny, max_turns, model, permission_mode):
    schema = json.dumps(json.load(open(os.path.join(HERE, "schemas", schema_file))), separators=(",", ":"))
    parts = ["--max-turns", str(max_turns), "--permission-mode", permission_mode, "--json-schema", schema]
    parts += ["--allowedTools"] + tools
    parts += ["--disallowedTools"] + deny
    if model:
        parts += ["--model", model]
    return " ".join(shlex.quote(p) for p in parts)


def render_prompt(name, **values):
    text = open(os.path.join(HERE, "prompts", name)).read()
    for k, v in values.items():
        text = text.replace("{{%s}}" % k, str(v))
    return text


def trusted_thread(gh, cfg, n, exclude_bots=True):
    out = []
    for c in gh.comments(n):
        login = (c.get("user") or {}).get("login", "")
        if login in cfg.trusted_bots:
            if exclude_bots:
                continue
        elif not gh.is_trusted_human(login):
            continue  # untrusted text never reaches the agent
        body = MARKER_RE.sub("", c.get("body") or "").strip()
        out.append("**@%s** (%s):\n\n%s" % (login, c["created_at"], body))
    return out


def cmd_prepare_implement(cfg, args):
    gh = GitHub(cfg.token, cfg)
    n, mode = int(args.issue), args.mode
    out = args.out
    os.makedirs(out, exist_ok=True)
    set_output("proceed", "false")
    if cfg.paused:
        notice("AGENTS_PAUSED is set; not starting.")
        return 0
    issue = gh.issue(n)
    if issue["state"] != "open" or "pull_request" in issue:
        notice("#%d is not an open issue" % n)
        return 0
    labels = label_names(issue)
    if L_HUMAN_ONLY in labels:
        notice("#%d is human-only" % n)
        return 0
    if L_WORKING not in labels:
        # Manual workflow_dispatch: the person dispatching has write access by definition.
        gh.set_state_labels(n, labels, add=[L_WORKING], remove=[L_READY, L_FIX])
    repo = gh.request("GET", gh.repo_path)[0]
    base = repo["default_branch"]
    branch = "%s%d" % (BRANCH_PREFIX, n)
    exists = gh.branch_exists(branch)
    pr = gh.open_agent_pr(n)
    if mode == "remediate" and not pr:
        warn("No open agent PR for #%d; running a fresh implementation instead." % n)
        mode = "implement"

    bot = gh.request("GET", "/users/%s" % urllib.parse.quote(cfg.bot_login))[0] if cfg.bot_login else None

    ctx = ["# Task: issue #%d — %s" % (n, issue["title"]), "", "Labels: %s" % (", ".join(sorted(labels)) or "none"), "",
           "## Issue description (written by a maintainer)", "", issue.get("body") or "(empty)", ""]
    thread = trusted_thread(gh, cfg, n)
    if thread:
        ctx += ["## Discussion from maintainers (oldest first)", ""] + thread + [""]
    req = {}
    if mode == "remediate":
        prn = pr["number"]
        if args.request and args.request != "0":
            req = next((m for m in gh.markers(prn, kinds={"remediation-request"}) if str(m["_comment_id"]) == str(args.request)), {})
        reason = req.get("reason", "manual")
        sha = pr["head"]["sha"]
        ctx += ["## Pull request under remediation", "", "%s — `%s` (head `%s`)" % (pr["html_url"], pr["title"], sha[:7]),
                "", "Reason: **%s**" % reason, ""]
        if reason in ("ci", "manual"):
            state, failed_ids, _ = pr_check_state(gh, cfg, sha)
            for name, job_id in failed_ids.items():
                ctx += ["### Failing check: %s" % name, "", "```", truncate(gh.job_log_tail(job_id), 15000), "```", ""]
        if reason in ("review", "manual"):
            rec = latest_review_record(gh, cfg, prn)
            if rec:
                findings = unb64(rec.get("findings", "")) or []
                ctx += ["### Findings from the independent AI review (on `%s`)" % rec.get("sha", "?")[:7], "",
                        "```json", truncate(json.dumps(findings, indent=2), 20000), "```", ""]
        if reason == "human":
            if req.get("review_id"):
                rv = gh.request("GET", gh.r("/pulls/%d/reviews/%s" % (prn, req["review_id"])))[0]
                if gh.is_trusted_human(rv["user"]["login"]):
                    ctx += ["### Review from @%s (changes requested)" % rv["user"]["login"], "", rv.get("body") or "", ""]
                    for c in gh.paginate(gh.r("/pulls/%d/reviews/%s/comments" % (prn, req["review_id"]))):
                        ctx += ["- `%s` line %s: %s" % (c.get("path"), c.get("line") or c.get("original_line"), c.get("body"))]
                    ctx.append("")
            if req.get("comment_id"):
                c = gh.request("GET", gh.r("/issues/comments/%s" % req["comment_id"]))[0]
                if gh.is_trusted_human(c["user"]["login"]):
                    ctx += ["### Instructions from @%s" % c["user"]["login"], "", c.get("body") or "", ""]
        if reason == "conflict":
            ctx += ["The branch conflicts with `%s`. The workflow has started `git merge origin/%s`; resolve every conflict, keep both sides' intent, then commit the merge." % (base, base), ""]
        pr_thread = trusted_thread(gh, cfg, prn)
        if pr_thread:
            ctx += ["## PR conversation from maintainers", ""] + pr_thread[-10:] + [""]

    with open(os.path.join(out, "context.md"), "w") as f:
        f.write("\n".join(ctx))
    prompt_name = "remediate.md" if mode == "remediate" else "implement.md"
    prompt = render_prompt(prompt_name, ISSUE=n, BRANCH=branch, BASE=base, REPO=cfg.repo, CONTEXT_FILE=CONTEXT_DIR + "/context.md")
    with open(os.path.join(out, "prompt.md"), "w") as f:
        f.write(prompt)
    meta = {
        "issue": n, "mode": mode, "branch": branch, "base": base, "branch_exists": exists,
        "pr": pr["number"] if pr else None, "pr_head": pr["head"]["sha"] if pr else None,
        "reason": req.get("reason") if mode == "remediate" else None, "request": args.request,
        "bot_name": cfg.bot_login or "github-actions[bot]",
        "bot_email": "%d+%s@users.noreply.github.com" % (bot["id"], cfg.bot_login) if bot else "41898282+github-actions[bot]@users.noreply.github.com",
    }
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    set_output("claude_args", claude_args(cfg, "implement.json", IMPLEMENT_TOOLS, ALWAYS_DENY, cfg.max_turns, cfg.model, "acceptEdits"))
    set_output("branch", branch)
    set_output("checkout_ref", branch if exists else base)
    set_output("base", base)
    set_output("mode", mode)
    set_output("merge_base", "true" if mode == "remediate" and req.get("reason") == "conflict" else "false")
    set_output("proceed", "true")
    return 0


def git(*args, cwd=None, check=True):
    res = subprocess.run(["git"] + list(args), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if check and res.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), res.stderr.strip()))
    return res.stdout.strip()


def cmd_finish_implement(cfg, args):
    """Runs on the macOS job right after Claude: classify the outcome and bundle new commits."""
    meta = json.load(open(os.path.join(args.dir, "meta.json")))
    structured = os.environ.get("STRUCTURED_OUTPUT", "").strip()
    result = {}
    if structured:
        try:
            result = json.loads(structured)
        except ValueError:
            result = {}
    exec_text = ""
    if args.execution_file and os.path.exists(args.execution_file):
        exec_text = open(args.execution_file, errors="replace").read()
    outcome = result.get("status") if result.get("status") in ("completed", "needs_human") else None
    if not outcome:
        outcome = classify_execution(exec_text) or "failed"

    # Never commit an unresolved merge: abort it and report failure instead.
    if git("diff", "--name-only", "--diff-filter=U") or os.path.exists(os.path.join(git("rev-parse", "--git-dir"), "MERGE_HEAD")):
        git("merge", "--abort", check=False)
        if outcome == "completed":
            outcome = "failed"
            result["summary"] = "Merge conflicts were left unresolved."
    # Commit anything Claude left uncommitted so nothing is silently lost.
    if git("status", "--porcelain"):
        git("add", "-A")
        git("commit", "-m", "Include uncommitted changes from agent run\n\nRefs #%d" % meta["issue"], check=False)
    base_ref = "origin/" + (meta["branch"] if meta["branch_exists"] else meta["base"])
    ahead = int(git("rev-list", "--count", "%s..HEAD" % base_ref) or 0)
    if ahead:
        git("bundle", "create", os.path.join(args.dir, "agent.bundle"), "HEAD", "^" + base_ref)
    if outcome == "completed" and not ahead:
        outcome = "no_changes"
    result.update({"outcome": outcome, "commits": ahead, "head": git("rev-parse", "HEAD")})
    with open(os.path.join(args.dir, "result.json"), "w") as f:
        json.dump(result, f, indent=2)
    log("outcome=%s commits=%d" % (outcome, ahead))
    return 0


def policy_violations(repo_dir, base, head):
    """Deterministic guardrails for agent PRs. Returns a list of human-readable problems."""
    problems = []
    names = git("diff", "--name-status", "--no-renames", "%s...%s" % (base, head), cwd=repo_dir).splitlines()
    for line in names:
        parts = line.split("\t")
        if len(parts) >= 2 and is_protected(parts[-1]):
            problems.append("Changes protected path `%s` (needs a human-authored PR)" % parts[-1])
    diff = git("diff", "--unified=0", "%s...%s" % (base, head), "--", "*.swift", cwd=repo_dir)
    for l in diff.splitlines():
        if l.startswith("+") and not l.startswith("+++") and SUPPRESSION_RE.search(l):
            problems.append("Adds a lint/test suppression: `%s`" % l[1:].strip()[:120])

    def count_tests(rev):
        total = 0
        files = git("ls-tree", "-r", "--name-only", rev, cwd=repo_dir).splitlines()
        for path in files:
            if "/Tests/" in "/" + path and path.endswith(".swift"):
                total += len(TEST_DECL_RE.findall(git("show", "%s:%s" % (rev, path), cwd=repo_dir, check=False)))
        return total

    mb = git("merge-base", base, head, cwd=repo_dir)
    before, after = count_tests(mb), count_tests(head)
    if after < before:
        problems.append("Removes tests: %d test declarations before, %d after" % (before, after))
    return problems


def cmd_policy(cfg, args):
    head_ref = os.environ.get("HEAD_REF", "")
    if not issue_for_branch(head_ref):
        log("Not an agent branch (%s): policy checks don't apply." % (head_ref or "push"))
        return 0
    problems = policy_violations(args.repo_dir, args.base, args.head)
    if problems:
        for p in problems:
            print("::error::" + p)
        summary("### Agent policy violations\n" + "\n".join("- " + p for p in problems))
        return 1
    log("Agent policy: OK")
    return 0


def render_pr_body(meta, result, cfg):
    def bullets(items, fmt):
        items = items or []
        return "\n".join(fmt(i) for i in items) if items else "_None_"

    val = bullets(result.get("validation"), lambda v: "| `%s` | %s | %s |" % (v.get("command", ""), v.get("result", ""), (v.get("notes") or "").replace("\n", " ")[:200]))
    return """## Summary

{summary}

Closes #{issue}

## Requirements addressed

{reqs}

## Implementation details

{impl}

## Tests added or modified

{tests}

## Validation (agent's local run)

| Command | Result | Notes |
|---|---|---|
{val}

CI (`Lint`, `Test`, `Build`, `Policy`) and the independent AI review (`agent/review`) are the authoritative gates; the table above is the implementing agent's own report.

## Breaking changes

{breaking}

## Risks and limitations

{risks}

## Screenshots / artifacts

{shots}

## Deployment or migration

{deploy}

---
<sub>Opened by the implementation agent for #{issue} · [run]({run}) · Approve to merge (squash); request changes or comment `@claude …` to send it back.</sub>
""".format(
        summary=result.get("summary") or "_No summary provided._",
        issue=meta["issue"],
        reqs=bullets(result.get("requirements"), lambda r: "- **%s** — %s" % (r.get("requirement", ""), r.get("how", ""))),
        impl=result.get("implementation_notes") or "_See commits._",
        tests=bullets(result.get("tests"), lambda t: "- %s" % t),
        val=val if result.get("validation") else "| _not reported_ | | |",
        breaking=result.get("breaking_changes") or "None",
        risks=result.get("risks") or "None identified",
        shots="UI changed: see the `screenshots` artifact on the CI run." if result.get("ui_changed") else "No UI changes.",
        deploy=result.get("deployment_notes") or "None",
        run=cfg.run_url,
    )


def cmd_publish_implement(cfg, args):
    """Ubuntu job holding the GitHub App token: push, open or update the PR, report."""
    gh = GitHub(cfg.token, cfg)
    app = GitHub(cfg.app_token, cfg)
    meta = json.load(open(os.path.join(args.dir, "meta.json")))
    rpath = os.path.join(args.dir, "result.json")
    result = json.load(open(rpath)) if os.path.exists(rpath) else {"outcome": "failed"}
    n, mode, branch, base = meta["issue"], meta["mode"], meta["branch"], meta["base"]
    outcome = result.get("outcome", "failed")
    issue = gh.issue(n)
    labels = label_names(issue)
    run_link = "[run](%s)" % cfg.run_url
    bundle = os.path.join(args.dir, "agent.bundle")
    repo_dir = args.repo_dir

    def finish(add, remove, message):
        gh.set_state_labels(n, labels, add=add, remove=remove)
        if message:
            gh.comment(n, message)
        gh.dispatch_workflow("agent-control.yml", base, {})

    if outcome == "usage_limit":
        add = [L_FIX] if mode == "remediate" else [L_READY]
        finish(add, [L_WORKING], "⏳ Paused: the Claude subscription usage limit was reached (%s). This is queued again automatically after `AGENT_COOLDOWN_MINUTES` (default 60). No API billing is used.\n\n%s" % (run_link, marker("usage-limit")))
        if mode == "remediate" and meta.get("pr"):
            # Re-post the request so the dispatcher runs it again after the cooldown.
            orig = next((m for m in gh.markers(meta["pr"], kinds={"remediation-request"}) if str(m["_comment_id"]) == str(meta.get("request"))), None)
            if orig:
                fields = {k: v for k, v in orig.items() if not k.startswith("_") and k != "kind"}
                gh.comment(meta["pr"], "Re-queued remediation after the usage-limit pause.\n\n" + marker("remediation-request", **fields))
        return 0

    pushed_sha = None
    if os.path.exists(bundle):
        if meta["branch_exists"]:
            git("fetch", "--quiet", "origin", "+refs/heads/%s:refs/remotes/origin/%s" % (branch, branch), cwd=repo_dir)
        git("fetch", "--quiet", bundle, "HEAD:refs/agent/new", cwd=repo_dir)
        problems = policy_violations(repo_dir, "origin/" + base, "refs/agent/new")
        if problems:
            finish([L_HUMAN], [L_WORKING], "🛑 **Needs a human.** The agent's changes were not pushed because they break the agent policy:\n\n%s\n\n%s · %s"
                   % ("\n".join("- " + p for p in problems), run_link, marker("needs-human", key="policy-push-%s" % result.get("head", ""))))
            return 0
        auth = base64.b64encode(("x-access-token:" + cfg.app_token).encode()).decode()
        push = subprocess.run(
            ["git", "-c", "http.extraheader=AUTHORIZATION: basic " + auth, "push", "origin", "refs/agent/new:refs/heads/" + branch],
            cwd=repo_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        )
        if push.returncode != 0:
            err = push.stderr.replace(cfg.app_token, "***")
            finish([L_HUMAN], [L_WORKING], "🛑 **Needs a human.** Pushing `%s` failed (someone else may have pushed, or the change touches workflow files):\n\n```\n%s\n```\n%s\n\n%s"
                   % (branch, truncate(err, 3000), run_link, marker("needs-human", key="push-%s" % result.get("head", ""))))
            return 0
        pushed_sha = git("rev-parse", "refs/agent/new", cwd=repo_dir)

    if mode == "remediate":
        prn = meta["pr"]
        if outcome == "completed" and pushed_sha:
            app.comment(prn, "🔧 **Remediation pushed** (`%s`). %s\n\n%s\n\nCI and the AI review re-run on the new commit; any earlier approval no longer applies.\n\n%s"
                        % (pushed_sha[:7], run_link, result.get("summary") or "", marker("remediation-result", outcome=outcome, sha=pushed_sha)))
            finish([L_VALIDATING], [L_WORKING], None)
        elif outcome == "needs_human":
            finish([L_HUMAN], [L_WORKING], "🛑 **Needs a human** (during remediation of #%d's PR). %s\n\n> %s\n\n%s" % (n, run_link, (result.get("question") or result.get("summary") or "").replace("\n", "\n> "), marker("needs-human", key="remediate-%s" % cfg.run_id)))
        else:
            finish([L_HUMAN], [L_WORKING], "🛑 **Needs a human.** Remediation ended with `%s` and no usable commit. %s\n\n%s" % (outcome, run_link, marker("needs-human", key="remediate-%s" % cfg.run_id)))
        return 0

    # mode == implement
    if outcome == "needs_human":
        msg = "🛑 **Needs a human.** The agent stopped to ask:\n\n> %s\n\n" % (result.get("question") or result.get("summary") or "(no detail)").replace("\n", "\n> ")
        if pushed_sha:
            msg += "Partial work is on branch `%s`.\n\n" % branch
        msg += "Reply with `@claude <answer>` to continue, or edit the issue and comment `/agent retry`. %s\n\n%s" % (run_link, marker("needs-human", key="impl-%s" % cfg.run_id))
        finish([L_HUMAN], [L_WORKING], msg)
        return 0
    if outcome != "completed" or not pushed_sha:
        resets = [m["_at"] for m in gh.markers(n, kinds={"reset"})]
        since = max(resets) if resets else None
        attempts = len([m for m in gh.markers(n, kinds={"run-start"}) if m.get("mode") == "implement" and (since is None or m["_at"] > since)])
        if attempts < cfg.max_impl_attempts:
            finish([L_READY], [L_WORKING], "⚠️ The agent run ended with `%s` (%s). Re-queued (attempt %d of %d used).\n\n%s" % (outcome, run_link, attempts, cfg.max_impl_attempts, marker("run-failed", outcome=outcome)))
        else:
            finish([L_HUMAN], [L_WORKING], "🛑 **Needs a human.** The agent run ended with `%s` and no attempts remain (%d). %s\n\n%s" % (outcome, cfg.max_impl_attempts, run_link, marker("needs-human", key="impl-limit-%s" % cfg.run_id)))
        return 0

    title = (result.get("pr_title") or issue["title"]).strip()[:120]
    body = render_pr_body(meta, result, cfg)
    pr = gh.open_agent_pr(n)
    if pr:
        app.request("PATCH", app.r("/pulls/%d" % pr["number"]), {"title": title, "body": body})
    else:
        pr = app.request("POST", app.r("/pulls"), {"title": title, "head": branch, "base": base, "body": body, "draft": True, "maintainer_can_modify": True})[0]
    copy = [l for l in labels if l in TYPE_LABELS or l in PRIORITY_LABELS]
    if copy:
        app.add_labels(pr["number"], copy)
    finish([L_VALIDATING], [L_WORKING], "📬 Draft PR %s is open (`%s`). CI and the independent AI review run next; it's marked ready for your review when both pass. %s\n\n%s"
           % (pr["html_url"], pushed_sha[:7], run_link, marker("pr-opened", pr=pr["number"], sha=pushed_sha)))
    return 0


# ---------------------------------------------------------------------------
# Review job: prepare → (Claude, read-only) → publish status on the exact SHA
# ---------------------------------------------------------------------------


def patch_id(repo_dir, base, head):
    mb = git("merge-base", base, head, cwd=repo_dir)
    diff = subprocess.run(["git", "diff", mb, head], cwd=repo_dir, stdout=subprocess.PIPE).stdout
    if not diff.strip():
        return "empty"
    pid = subprocess.run(["git", "patch-id", "--stable"], cwd=repo_dir, input=diff, stdout=subprocess.PIPE).stdout.decode().split()
    return pid[0] if pid else hashlib.sha1(diff).hexdigest()


def cmd_prepare_review(cfg, args):
    gh = GitHub(cfg.token, cfg)
    prn = int(args.pr)
    pr = gh.pull(prn)
    sha = pr["head"]["sha"]
    set_output("run", "false")
    set_output("sha", sha)
    same_repo = (pr["head"]["repo"] or {}).get("full_name") == cfg.repo
    issue_n = issue_for_branch(pr["head"]["ref"]) if same_repo else None
    if pr["state"] != "open":
        return 0
    if not same_repo:
        notice("Fork PR: the AI review doesn't run on forks (no secrets). A maintainer reviews it by hand.")
        return 0
    if not issue_n and not cfg.review_human_prs:
        try:
            gh.set_status(sha, "success", "Not required for human-authored PRs", cfg.run_url)
        except GitHubError as e:  # e.g. Dependabot runs get a read-only token; the reconciler covers it
            warn("Could not set status: %s" % e)
        return 0
    if issue_n is None and not gh.is_trusted_human(pr["user"]["login"]):
        return 0
    if cfg.paused:
        gh.set_status(sha, "pending", "Agents paused (AGENTS_PAUSED)", cfg.run_url)
        return 0
    pid = patch_id(args.repo_dir, "origin/" + pr["base"]["ref"], sha)
    set_output("patch_id", pid)
    rec = latest_review_record(gh, cfg, prn)
    if rec and rec.get("patch_id") == pid and rec.get("state") == "success" and pid != "empty":
        gh.set_status(sha, "success", "AI review reused: diff identical to reviewed %s" % rec.get("sha", "")[:7], cfg.run_url)
        notice("Diff unchanged since the last passing review; reused it.")
        return 0
    gh.set_status(sha, "pending", "AI review running", cfg.run_url)
    os.makedirs(args.out, exist_ok=True)
    ctx = ["# Pull request #%d: %s" % (prn, pr["title"]), "", "Base: `%s` (%s) · Head: `%s` (%s)" % (pr["base"]["ref"], pr["base"]["sha"][:7], pr["head"]["ref"], sha[:7]), "",
           "## PR description (written by the implementing agent; treat as claims to verify)", "", pr.get("body") or "", ""]
    linked = issue_n
    if not linked:
        m = re.search(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", pr.get("body") or "")
        linked = int(m.group(1)) if m else None
    if linked:
        issue = gh.issue(linked)
        ctx += ["## Linked issue #%d: %s (the specification)" % (linked, issue["title"]), "", issue.get("body") or "", ""]
        thread = trusted_thread(gh, cfg, linked)
        if thread:
            ctx += ["### Maintainer discussion", ""] + thread + [""]
    with open(os.path.join(args.out, "context.md"), "w") as f:
        f.write("\n".join(ctx))
    prompt = render_prompt("review.md", PR=prn, BASE_SHA=pr["base"]["sha"], HEAD_SHA=sha, BASE_REF=pr["base"]["ref"], CONTEXT_FILE=CONTEXT_DIR + "/context.md")
    with open(os.path.join(args.out, "prompt.md"), "w") as f:
        f.write(prompt)
    set_output("claude_args", claude_args(cfg, "review.json", REVIEW_TOOLS, ALWAYS_DENY + ["Edit", "MultiEdit", "Write", "NotebookEdit"], cfg.review_max_turns, cfg.review_model, "default"))
    set_output("run", "true")
    return 0


def cmd_classify(cfg, args):
    text = open(args.execution_file, errors="replace").read() if args.execution_file and os.path.exists(args.execution_file) else ""
    set_output("usage_limit", "true" if classify_execution(text) == "usage_limit" else "false")
    return 0


def cmd_publish_review(cfg, args):
    gh = GitHub(cfg.token, cfg)
    prn, sha, pid = int(args.pr), args.sha, args.patch_id
    structured = os.environ.get("STRUCTURED_OUTPUT", "").strip()
    usage_limited = os.environ.get("USAGE_LIMIT", "") == "true"
    result = None
    if structured:
        try:
            result = json.loads(structured)
        except ValueError:
            result = None
    if result is None:
        if usage_limited:
            gh.set_status(sha, "error", "AI review paused: Claude usage limit; retries automatically", cfg.run_url)
            gh.comment(prn, "⏳ AI review paused: the Claude subscription usage limit was reached. It retries automatically after the cooldown.\n\n" + marker("usage-limit"))
        else:
            gh.set_status(sha, "error", "AI review run failed; see run log", cfg.run_url)
        return 0
    state, desc, blocking = review_verdict(result, cfg.blocking)
    gh.set_status(sha, state if state != "error" else "error", desc, cfg.run_url)
    findings = result.get("findings") or []
    sev_order = ["critical", "high", "medium", "low", "nit"]
    findings.sort(key=lambda f: sev_order.index(f.get("severity")) if f.get("severity") in sev_order else 9)
    icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "nit": "⚪"}
    rows = ["| | Severity | Where | Finding |", "|---|---|---|---|"]
    for f in findings[:50]:
        where = "`%s:%s`" % (f.get("file", "?"), f.get("line", "")) if f.get("file") else ""
        rows.append("| %s | %s | %s | **%s** — %s%s |" % (
            icon.get(f.get("severity"), ""), f.get("severity", ""), where,
            (f.get("title") or "").replace("|", "\\|"), (f.get("detail") or "").replace("\n", " ").replace("|", "\\|")[:600],
            (" _Fix:_ " + f["suggestion"].replace("\n", " ").replace("|", "\\|")[:300]) if f.get("suggestion") else ""))
    ac = result.get("acceptance_criteria") or []
    ac_lines = ["- %s %s — %s" % ("✅" if c.get("met") else "❌", c.get("criterion", ""), (c.get("evidence") or "").replace("\n", " ")[:300]) for c in ac]
    body = "\n".join([
        "## 🔍 Independent AI review — %s" % ("✅ passed" if state == "success" else "❌ changes needed"),
        "", "Commit `%s` · verdict `%s` · %s · [run](%s)" % (sha[:7], result.get("verdict"), desc, cfg.run_url), "",
        result.get("summary") or "", "",
        "### Acceptance criteria", "", "\n".join(ac_lines) or "_None listed in the issue._", "",
        "### Findings", "", "\n".join(rows) if findings else "_No findings._", "",
        "<sub>Blocking severities: %s. This review gates the `agent/review` status; it never replaces your approval.</sub>" % ", ".join(sorted(cfg.blocking)),
    ])

    def slim(items, n):
        return [{k: (str(v)[:500] if isinstance(v, str) else v) for k, v in f.items()} for f in items[:n]]

    mark = marker("review", sha=sha, patch_id=pid, state=state, findings=b64(slim(findings, 25)), blocking=b64(slim(blocking, 15)))
    body = truncate(body, 64000 - len(mark) - 10) + "\n\n" + mark
    existing = [c for c in gh.comments(prn) if (c.get("user") or {}).get("login") in cfg.trusted_bots and '"kind":"review"' in (c.get("body") or "")]
    if existing:
        gh.request("PATCH", gh.r("/issues/comments/%d" % existing[-1]["id"]), {"body": body})
    else:
        gh.comment(prn, body)
    summary(body)
    return 0


# ---------------------------------------------------------------------------
# Bootstrap: labels and the GitHub Project (run once by a maintainer)
# ---------------------------------------------------------------------------


def cmd_bootstrap(cfg, args):
    gh = GitHub(cfg.token, cfg)
    existing = {l["name"] for l in gh.paginate(gh.r("/labels"))}
    for name, (color, desc) in LABELS.items():
        if name in existing:
            continue
        gh.request("POST", gh.r("/labels"), {"name": name, "color": color, "description": desc})
        log("created label %s" % name)
    if args.labels_only:
        return 0
    pg = GitHub(cfg.project_token or cfg.token, cfg)
    user = pg.graphql("query($l:String!){user(login:$l){id}}", {"l": cfg.project_owner})["user"]
    if args.project_number:
        num = int(args.project_number)
    else:
        data = pg.graphql("mutation($o:ID!,$t:String!){createProjectV2(input:{ownerId:$o,title:$t}){projectV2{number url id}}}", {"o": user["id"], "t": args.title})
        num = data["createProjectV2"]["projectV2"]["number"]
        log("created project %s" % data["createProjectV2"]["projectV2"]["url"])
    q = """query($l:String!,$n:Int!){user(login:$l){projectV2(number:$n){id url fields(first:50){nodes{
           ... on ProjectV2FieldCommon{id name dataType} ... on ProjectV2SingleSelectField{options{id name color description}}}}}}}"""
    proj = pg.graphql(q, {"l": cfg.project_owner, "n": num})["user"]["projectV2"]
    fields = {f["name"]: f for f in proj["fields"]["nodes"] if f}

    def opts(names, colors):
        return [{"name": n, "color": c, "description": ""} for n, c in zip(names, colors)]

    selects = {
        "Status": opts(STATUSES, ["GRAY", "BLUE", "PURPLE", "YELLOW", "ORANGE", "PINK", "RED", "RED", "GREEN", "GREEN"]),
        "Priority": opts(["High", "Medium", "Low"], ["RED", "YELLOW", "GRAY"]),
        "Type": opts(["Feature", "New tool", "Bug", "Refactor", "Testing", "Documentation", "Tech debt"], ["BLUE", "PURPLE", "RED", "GRAY", "GREEN", "YELLOW", "ORANGE"]),
        "Agent": opts(["Claude", "Human", "Codex"], ["ORANGE", "BLUE", "GRAY"]),
        "Effort": opts(["XS", "S", "M", "L", "XL"], ["GRAY", "GREEN", "YELLOW", "ORANGE", "RED"]),
    }
    for name, options in selects.items():
        f = fields.get(name)
        if f and f.get("options") is not None:
            have = [o["name"] for o in f["options"]]
            if have == [o["name"] for o in options]:
                continue
            keep = {o["name"]: o for o in f["options"]}
            merged = [dict(o, id=keep[o["name"]]["id"]) if o["name"] in keep else o for o in options]
            pg.graphql("mutation($f:ID!,$o:[ProjectV2SingleSelectFieldOptionInput!]){updateProjectV2Field(input:{fieldId:$f,singleSelectOptions:$o}){clientMutationId}}",
                       {"f": f["id"], "o": [{k: v for k, v in o.items() if k in ("name", "color", "description")} for o in merged]})
            log("updated field %s" % name)
        elif not f:
            pg.graphql("mutation($p:ID!,$n:String!,$o:[ProjectV2SingleSelectFieldOptionInput!]){createProjectV2Field(input:{projectId:$p,dataType:SINGLE_SELECT,name:$n,singleSelectOptions:$o}){clientMutationId}}",
                       {"p": proj["id"], "n": name, "o": options})
            log("created field %s" % name)
    if "Iteration" not in fields:
        try:
            start = now().date()
            start = start - timedelta(days=start.weekday())
            pg.graphql("mutation($p:ID!,$s:Date!){createProjectV2Field(input:{projectId:$p,dataType:ITERATION,name:\"Iteration\",iterationConfiguration:{startDate:$s,duration:14,iterations:[]}}){clientMutationId}}",
                       {"p": proj["id"], "s": start.isoformat()})
            log("created field Iteration (2-week)")
        except GitHubError as e:
            warn("Could not create the Iteration field via API (%s); add it in the project settings." % e.message)
    try:
        repo_id = gh.request("GET", gh.repo_path)[0]["node_id"]
        pg.graphql("mutation($p:ID!,$r:ID!){linkProjectV2ToRepository(input:{projectId:$p,repositoryId:$r}){clientMutationId}}", {"p": proj["id"], "r": repo_id})
    except GitHubError as e:
        warn("link project to repo: %s" % e.message)
    print(json.dumps({"project_number": num, "url": proj["url"]}))
    return 0


# ---------------------------------------------------------------------------


def main(argv=None):
    p = argparse.ArgumentParser(prog="agentctl")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reconcile")
    r.add_argument("--dry-run", action="store_true")
    sub.add_parser("command")
    s = sub.add_parser("prepare-implement")
    s.add_argument("--issue", required=True)
    s.add_argument("--mode", default="implement", choices=["implement", "remediate"])
    s.add_argument("--request", default="0")
    s.add_argument("--out", required=True)
    s = sub.add_parser("finish-implement")
    s.add_argument("--dir", required=True)
    s.add_argument("--execution-file", default="")
    s = sub.add_parser("publish-implement")
    s.add_argument("--dir", required=True)
    s.add_argument("--repo-dir", default=".")
    s = sub.add_parser("policy")
    s.add_argument("--repo-dir", default=".")
    s.add_argument("--base", required=True)
    s.add_argument("--head", required=True)
    s = sub.add_parser("prepare-review")
    s.add_argument("--pr", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--repo-dir", default=".")
    s = sub.add_parser("publish-review")
    s.add_argument("--pr", required=True)
    s.add_argument("--sha", required=True)
    s.add_argument("--patch-id", default="")
    s = sub.add_parser("classify")
    s.add_argument("--execution-file", default="")
    s = sub.add_parser("bootstrap")
    s.add_argument("--labels-only", action="store_true")
    s.add_argument("--project-number", default="")
    s.add_argument("--title", default="Snowflake Development")
    a = p.parse_args(argv)
    cfg = Config()
    if a.cmd == "reconcile":
        Reconciler(cfg, dry_run=a.dry_run).run()
        return 0
    return {
        "command": cmd_command,
        "prepare-implement": cmd_prepare_implement,
        "finish-implement": cmd_finish_implement,
        "publish-implement": cmd_publish_implement,
        "policy": cmd_policy,
        "prepare-review": cmd_prepare_review,
        "publish-review": cmd_publish_review,
        "classify": cmd_classify,
        "bootstrap": cmd_bootstrap,
    }[a.cmd](cfg, a)


if __name__ == "__main__":
    sys.exit(main())
