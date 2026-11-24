"""Unit tests for agentctl. Run: python3 -m unittest discover -s .github/agent -p 'test_*.py'"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agentctl as A  # noqa: E402

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeGitHub(A.GitHub):
    """In-memory GitHub covering the endpoints the reconciler uses."""

    def __init__(self, cfg):
        super().__init__("token", cfg)
        self.issues = {}  # n -> issue dict (also PR issues)
        self.comments_by = {}  # n -> [comment]
        self.events = {}  # n -> [event]
        self.pulls = {}  # n -> pull dict
        self.perms = {"maintainer": "admin", "outsider": "read"}
        self.dispatches = []
        self.active = []  # active implement runs: display titles
        self.check_runs = {}  # sha -> [run]
        self.statuses = {}  # sha -> [status]
        self.reviews = {}  # pr -> [review]
        self.graphql_calls = []
        self.updates = []
        self._cid = 1000

    # helpers to build state
    def add_issue(self, n, labels=(), body="", state="open", labeled_by="maintainer"):
        self.issues[n] = {"number": n, "title": "Issue %d" % n, "body": body, "state": state, "labels": [{"name": l} for l in labels],
                          "updated_at": ts(T0 - timedelta(hours=1)), "node_id": "I_%d" % n}
        self.comments_by.setdefault(n, [])
        self.events[n] = [{"event": "labeled", "label": {"name": l}, "actor": {"login": labeled_by}} for l in labels]

    def add_pr(self, n, issue_n, sha="abc1234def", draft=True, mergeable_state="clean"):
        ref = "agent/issue-%d" % issue_n
        self.pulls[n] = {"number": n, "node_id": "PR_%d" % n, "title": "PR", "body": "Closes #%d" % issue_n, "state": "open", "draft": draft,
                         "head": {"ref": ref, "sha": sha, "repo": {"full_name": self.cfg.repo}}, "base": {"ref": "main", "sha": "base000"},
                         "html_url": "https://github.com/%s/pull/%d" % (self.cfg.repo, n), "mergeable_state": mergeable_state,
                         "auto_merge": None, "updated_at": ts(T0 - timedelta(hours=1)), "user": {"login": "agent-bot[bot]"}}
        self.comments_by.setdefault(n, [])

    def set_checks(self, sha, conclusions, review=None):
        self.check_runs[sha] = [{"id": i + 1, "name": k, "status": "completed" if v else "in_progress", "conclusion": v, "app": {"slug": "github-actions"}}
                                for i, (k, v) in enumerate(conclusions.items())]
        if review:
            self.statuses[sha] = [{"context": A.REVIEW_CONTEXT, "state": review, "description": "", "creator": {"login": "github-actions[bot]"},
                                   "updated_at": ts(T0 - timedelta(hours=2))}]

    def labels(self, n):
        return {l["name"] for l in self.issues[n]["labels"]}

    def _comment(self, n, body, login="github-actions[bot]", at=None):
        self._cid += 1
        c = {"id": self._cid, "body": body, "user": {"login": login}, "created_at": ts(at or T0)}
        self.comments_by.setdefault(n, []).append(c)
        return c

    # transport
    def graphql(self, query, variables=None):
        m = re.search(r"\{\s*(\w+)\s*\(", query)
        self.graphql_calls.append(m.group(1) if m else query)
        return {}

    def paginate(self, path, limit=1000, **params):
        data, _ = self.request("GET", path, params=params)
        return data if isinstance(data, list) else []

    def request(self, method, path, body=None, params=None, accept=None):
        path = path.replace(self.cfg.api, "")
        rp = "/repos/" + self.cfg.repo
        p = path[len(rp):] if path.startswith(rp) else path
        p = p.split("?")[0]
        m = lambda pat: re.fullmatch(pat, p)  # noqa: E731
        if method == "GET" and p == "":
            return {"default_branch": "main", "node_id": "R_1"}, ""
        if method == "GET" and p == "/issues":
            items = [i for i in self.issues.values() if i["state"] == "open"]
            for pr in self.pulls.values():
                items.append({"number": pr["number"], "pull_request": {}, "labels": [], "state": "open"})
            return items, ""
        if method == "GET" and p == "/pulls":
            prs = [pr for pr in self.pulls.values() if pr["state"] == "open"]
            if params and params.get("head"):
                ref = params["head"].split(":", 1)[1]
                prs = [pr for pr in prs if pr["head"]["ref"] == ref]
            return prs, ""
        if m(r"/pulls/(\d+)") and method == "GET":
            return self.pulls[int(m(r"/pulls/(\d+)").group(1))], ""
        if m(r"/pulls/(\d+)/update-branch"):
            self.updates.append(int(m(r"/pulls/(\d+)/update-branch").group(1)))
            return {}, ""
        if m(r"/pulls/(\d+)/reviews"):
            return self.reviews.get(int(m(r"/pulls/(\d+)/reviews").group(1)), []), ""
        if m(r"/issues/(\d+)") and method == "GET":
            n = int(m(r"/issues/(\d+)").group(1))
            if n not in self.issues:
                raise A.GitHubError(404, "Not Found")
            return self.issues[n], ""
        if m(r"/issues/(\d+)/comments"):
            n = int(m(r"/issues/(\d+)/comments").group(1))
            if method == "POST":
                return self._comment(n, body["body"]), ""
            return list(self.comments_by.get(n, [])), ""
        if m(r"/issues/comments") and method == "GET":
            return [c for cs in self.comments_by.values() for c in cs], ""
        if m(r"/issues/(\d+)/labels") and method == "POST":
            n = int(m(r"/issues/(\d+)/labels").group(1))
            for l in body["labels"]:
                if l not in self.labels(n):
                    self.issues[n]["labels"].append({"name": l})
                    self.events[n].append({"event": "labeled", "label": {"name": l}, "actor": {"login": "github-actions[bot]"}})
            return [], ""
        if m(r"/issues/(\d+)/labels/(.+)") and method == "DELETE":
            mm = m(r"/issues/(\d+)/labels/(.+)")
            n, l = int(mm.group(1)), A.urllib.parse.unquote(mm.group(2))
            self.issues[n]["labels"] = [x for x in self.issues[n]["labels"] if x["name"] != l]
            return None, ""
        if m(r"/issues/(\d+)/events"):
            return self.events.get(int(m(r"/issues/(\d+)/events").group(1)), []), ""
        if m(r"/issues/(\d+)/dependencies/blocked_by"):
            raise A.GitHubError(404, "Not Found")
        if m(r"/collaborators/([^/]+)/permission"):
            return {"permission": self.perms.get(m(r"/collaborators/([^/]+)/permission").group(1), "none")}, ""
        if m(r"/actions/workflows/([^/]+)/runs"):
            if params.get("status") == "in_progress":
                return [{"id": i, "display_title": t} for i, t in enumerate(self.active)], ""
            return [], ""
        if m(r"/actions/workflows/([^/]+)/dispatches"):
            self.dispatches.append((m(r"/actions/workflows/([^/]+)/dispatches").group(1), body["inputs"]))
            return None, ""
        if m(r"/commits/([^/]+)/check-runs"):
            return self.check_runs.get(m(r"/commits/([^/]+)/check-runs").group(1), []), ""
        if m(r"/commits/([^/]+)/status"):
            return {"statuses": self.statuses.get(m(r"/commits/([^/]+)/status").group(1), [])}, ""
        if m(r"/statuses/([^/]+)"):
            sha = m(r"/statuses/([^/]+)").group(1)
            self.statuses.setdefault(sha, []).append(dict(body, creator={"login": "github-actions[bot]"}))
            return {}, ""
        raise AssertionError("unhandled %s %s" % (method, path))


def make(env=None):
    base = {"GITHUB_REPOSITORY": "me/repo", "AGENT_BOT_LOGIN": "agent-bot[bot]", "AGENT_MAX_CONCURRENT": "2"}
    base.update(env or {})
    cfg = A.Config(base)
    gh = FakeGitHub(cfg)
    r = A.Reconciler(cfg)
    r.gh = gh
    r.app = gh
    r.default_branch = "main"
    return r, gh


class PureFunctionTests(unittest.TestCase):
    def test_dependencies_from_form_and_lines(self):
        body = "### Problem\nx\n\n### Dependencies\n\nDepends on #12 and #15\n\n### Constraints\nsee #99\n"
        self.assertEqual(A.parse_dependencies(body), [12, 15])
        self.assertEqual(A.parse_dependencies("Blocked by: #3, #4\nmentions #5"), [3, 4])
        self.assertEqual(A.parse_dependencies("### Dependencies\n\n_No response_\n"), [])
        self.assertEqual(A.parse_dependencies("Depends on other/repo#7"), [])

    def test_form_priority(self):
        self.assertEqual(A.form_priority("### Priority\n\nHigh\n"), "priority:high")
        self.assertIsNone(A.form_priority("### Priority\n\n_No response_\n"))

    def test_desired_status(self):
        self.assertEqual(A.desired_status({A.L_READY}, "open", None), "Queued")
        self.assertEqual(A.desired_status({A.L_READY, A.L_WORKING}, "open", None), "In Progress")
        self.assertEqual(A.desired_status({A.L_HUMAN, A.L_VALIDATING}, "open", None), "Blocked")
        self.assertEqual(A.desired_status({A.L_APPROVED}, "open", None), "Approved")
        self.assertEqual(A.desired_status(set(), "closed", "In Review"), "Done")
        self.assertEqual(A.desired_status(set(), "open", "In Progress"), "Ready")  # agent labels removed
        self.assertEqual(A.desired_status(set(), "open", "Backlog"), "Backlog")  # manual statuses untouched
        self.assertEqual(A.desired_status(set(), "open", None), "Backlog")

    def test_protected_paths(self):
        for p in [".github/workflows/ci.yml", ".github/agent/agentctl.py", "CLAUDE.md", "Makefile", "Config/Base.xcconfig", ".swiftlint.yml", "scripts/screenshots.sh"]:
            self.assertTrue(A.is_protected(p), p)
        for p in ["Snowflake/App/AppDelegate.swift", "Packages/SnowflakeKit/Sources/SnowflakeModules/X/X.swift", "CHANGELOG.md", "docs/BRAND.md", "MakefileExtra"]:
            self.assertFalse(A.is_protected(p), p)

    def test_review_verdict(self):
        ok = {"verdict": "approve", "findings": [{"severity": "low", "title": "nit"}], "acceptance_criteria": [{"criterion": "a", "met": True}]}
        self.assertEqual(A.review_verdict(ok, {"critical", "high"})[0], "success")
        high = dict(ok, findings=[{"severity": "high", "title": "bug"}])
        self.assertEqual(A.review_verdict(high, {"critical", "high"})[0], "failure")
        # The deterministic gate overrides an "approve" verdict that hides an unmet criterion.
        unmet = dict(ok, acceptance_criteria=[{"criterion": "a", "met": False}])
        state, desc, blocking = A.review_verdict(unmet, {"critical", "high"})
        self.assertEqual(state, "failure")
        self.assertIn("unmet", desc)
        self.assertEqual(A.review_verdict(None, {"high"})[0], "error")
        self.assertEqual(A.review_verdict(dict(ok, verdict="request_changes", findings=[]), {"high"})[0], "failure")

    def test_classify_execution(self):
        limit = json.dumps([{"type": "assistant"}, {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "Claude AI usage limit reached|1764000000"}])
        self.assertEqual(A.classify_execution(limit), "usage_limit")
        ok = json.dumps([{"type": "result", "subtype": "success", "is_error": False, "result": "Implemented a rate limiter; 429 handling added"}])
        self.assertIsNone(A.classify_execution(ok))
        other = json.dumps([{"type": "result", "subtype": "error_max_turns", "is_error": True, "result": ""}])
        self.assertIsNone(A.classify_execution(other))
        self.assertEqual(A.classify_execution("API Error: 429 rate_limit_error"), "usage_limit")
        self.assertIsNone(A.classify_execution(""))

    def test_execution_error(self):
        text = json.dumps([{"type": "result", "subtype": "success", "is_error": True, "result": "Invalid API key · Please run /login"}])
        self.assertEqual(A.execution_error(text), "Invalid API key · Please run /login")
        self.assertEqual(A.execution_error(json.dumps([{"type": "result", "is_error": False, "result": "ok"}])), "")
        self.assertEqual(A.execution_error("not json"), "")

    def test_pr_body_keeps_update_history(self):
        cfg = A.Config({"GITHUB_REPOSITORY": "me/repo"})
        meta = {"issue": 3, "reason": "review"}
        v1 = A.render_pr_body(meta, {"summary": "first"}, cfg)
        v2 = A.updated_pr_body(v1, meta, {"summary": "second"}, "aaaaaaa1", cfg)
        v3 = A.updated_pr_body(v2, meta, {"summary": "third"}, "bbbbbbb2", cfg)
        self.assertIn("third", v3.split(A.UPDATES_HEADING)[0])  # summary re-rendered from the latest report
        log = v3.split(A.UPDATES_HEADING)[1]
        self.assertLess(log.index("aaaaaaa"), log.index("bbbbbbb"))
        self.assertEqual(v3.count(A.UPDATES_HEADING), 1)
        self.assertIn("Closes #3", v3)
        self.assertTrue(v3.rstrip().endswith("</sub>"))

    def test_marker_roundtrip_and_trust(self):
        cfg = A.Config({"GITHUB_REPOSITORY": "me/repo", "AGENT_BOT_LOGIN": "agent-bot[bot]"})
        gh = FakeGitHub(cfg)
        gh.add_issue(1)
        gh._comment(1, "hi " + A.marker("run-start", mode="implement"))
        gh._comment(1, "forged " + A.marker("reset"), login="outsider")
        marks = gh.markers(1)
        self.assertEqual([m["kind"] for m in marks], ["run-start"])  # forged marker from a human ignored

    def test_claude_args_quote(self):
        cfg = A.Config({})
        args = A.claude_args(cfg, "review.json", ["Read", "Bash(git diff:*)"], ["WebFetch"], 10, "", "default")
        self.assertIn("--json-schema '", args)
        self.assertIn("'Bash(git diff:*)'", args)
        self.assertIn("--permission-mode default", args)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.write("Packages/K/Tests/KTests/ATests.swift", "import Testing\n@Test func a() {}\n@Test func b() {}\n")
        self.write("Sources/A.swift", "let a = 1\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.git("switch", "-qc", "agent/issue-1")

    def git(self, *args):
        subprocess.run(["git"] + list(args), cwd=self.dir, check=True, stdout=subprocess.PIPE)

    def write(self, path, text):
        full = os.path.join(self.dir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w").write(text)

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "change")
        return A.policy_violations(self.dir, "main", "HEAD")

    def test_clean_change_passes(self):
        self.write("Sources/A.swift", "let a = 2\n")
        self.write("Packages/K/Tests/KTests/ATests.swift", "import Testing\n@Test func a() {}\n@Test func b() {}\n@Test func c() {}\n")
        self.assertEqual(self.commit(), [])

    def test_protected_path_fails(self):
        self.write(".github/workflows/x.yml", "on: push\n")
        self.write("Makefile", "x:\n")
        problems = self.commit()
        self.assertEqual(len(problems), 2)

    def test_removed_tests_fail(self):
        self.write("Packages/K/Tests/KTests/ATests.swift", "import Testing\n@Test func a() {}\n")
        self.assertTrue(any("Removes tests" in p for p in self.commit()))

    def test_suppression_fails(self):
        self.write("Sources/A.swift", "// swiftlint:disable force_cast\nlet a = 2\n")
        self.assertTrue(any("suppression" in p for p in self.commit()))


class FinishImplementTests(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.dir = tempfile.mkdtemp()
        self.out = tempfile.mkdtemp()
        os.chdir(self.dir)
        for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
            subprocess.run(["git"] + args, check=True)
        open("a.txt", "w").write("1\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-qm", "base"], check=True)
        subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
        subprocess.run(["git", "switch", "-qc", "agent/issue-1"], check=True)
        json.dump({"issue": 1, "branch": "agent/issue-1", "base": "main", "branch_exists": False}, open(os.path.join(self.out, "meta.json"), "w"))

    def tearDown(self):
        os.chdir(self.cwd)
        os.environ.pop("STRUCTURED_OUTPUT", None)

    def run_finish(self, structured):
        os.environ["STRUCTURED_OUTPUT"] = json.dumps(structured)
        A.cmd_finish_implement(A.Config({}), type("Args", (), {"dir": self.out, "execution_file": ""})())
        return json.load(open(os.path.join(self.out, "result.json")))

    def test_completed_with_commit_bundles(self):
        open("a.txt", "w").write("2\n")
        subprocess.run(["git", "commit", "-qam", "change"], check=True)
        res = self.run_finish({"status": "completed", "summary": "x"})
        self.assertEqual((res["outcome"], res["commits"]), ("completed", 1))
        self.assertTrue(os.path.exists(os.path.join(self.out, "agent.bundle")))

    def test_completed_without_commits_is_no_changes(self):
        self.assertEqual(self.run_finish({"status": "completed", "summary": "x"})["outcome"], "no_changes")

    def test_uncommitted_work_is_committed(self):
        open("b.txt", "w").write("new\n")
        res = self.run_finish({"status": "completed", "summary": "x"})
        self.assertEqual((res["outcome"], res["commits"]), ("completed", 1))

    def test_unresolved_merge_is_never_committed(self):
        subprocess.run(["git", "switch", "-q", "main"], check=True)
        open("a.txt", "w").write("main\n")
        subprocess.run(["git", "commit", "-qam", "main change"], check=True)
        subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
        subprocess.run(["git", "switch", "-q", "agent/issue-1"], check=True)
        open("a.txt", "w").write("branch\n")
        subprocess.run(["git", "commit", "-qam", "branch change"], check=True)
        subprocess.run(["git", "merge", "origin/main"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        res = self.run_finish({"status": "completed", "summary": "x"})
        self.assertEqual(res["outcome"], "failed")
        self.assertNotIn("<<<<<<<", open("a.txt").read())


class CommandTests(unittest.TestCase):
    def run_command(self, gh, body, number=3, login="maintainer"):
        path = os.path.join(tempfile.mkdtemp(), "event.json")
        json.dump({"comment": {"id": 555, "body": body, "user": {"login": login}}, "issue": {"number": number}}, open(path, "w"))
        os.environ["GITHUB_EVENT_PATH"] = path
        orig = A.GitHub
        A.GitHub = lambda token, cfg: gh
        try:
            A.cmd_command(gh.cfg, None)
        finally:
            A.GitHub = orig

    def test_retry_clears_working_and_is_idempotent(self):
        _, gh = make()
        gh.add_issue(3, [A.L_WORKING, A.L_HUMAN])
        gh.active = ["Agent implement #3"]
        cancelled = []
        orig_request = gh.request

        def request(method, path, body=None, params=None, accept=None):
            if method == "POST" and path.endswith("/cancel"):
                cancelled.append(path)
                return None, ""
            if method == "POST" and "/reactions" in path:
                return {}, ""
            return orig_request(method, path, body, params, accept)

        gh.request = request
        self.run_command(gh, "/agent retry")
        self.run_command(gh, "/agent retry")  # duplicate delivery of the same comment
        self.assertEqual(gh.labels(3), {A.L_READY})
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(len(gh.markers(3, kinds={"reset"})), 1)

    def test_untrusted_commenter_ignored(self):
        _, gh = make()
        gh.add_issue(3, [A.L_HUMAN])
        self.run_command(gh, "/agent retry", login="outsider")
        self.assertEqual(gh.labels(3), {A.L_HUMAN})


class ReconcilerTests(unittest.TestCase):
    def test_dispatch_respects_concurrency_and_priority(self):
        r, gh = make()
        gh.add_issue(1, [A.L_READY, "priority:low"])
        gh.add_issue(2, [A.L_READY, "priority:high"])
        gh.add_issue(3, [A.L_READY])
        r.dispatch({n: gh.issues[n] for n in gh.issues})
        started = [int(i["issue"]) for w, i in gh.dispatches if w == "agent-implement.yml"]
        self.assertEqual(started, [2, 3])  # high first, then medium (default); limit 2
        self.assertIn(A.L_WORKING, gh.labels(2))
        self.assertNotIn(A.L_READY, gh.labels(2))
        self.assertIn(A.L_READY, gh.labels(1))  # still queued

    def test_no_slots_when_agents_busy(self):
        r, gh = make()
        gh.add_issue(1, [A.L_WORKING])
        gh.add_issue(2, [A.L_READY])
        gh.active = ["Agent implement #1", "Agent implement #9"]
        r.dispatch({n: gh.issues[n] for n in gh.issues})
        self.assertEqual(gh.dispatches, [])

    def test_repeated_delegation_does_not_duplicate(self):
        r, gh = make()
        gh.add_issue(1, [A.L_READY])
        r.dispatch({n: gh.issues[n] for n in gh.issues})
        gh.active = ["Agent implement #1"]
        gh.add_labels(1, [A.L_READY])  # maintainer re-applies the label while it runs
        r.dispatch({n: gh.issues[n] for n in gh.issues})
        self.assertEqual(len(gh.dispatches), 1)

    def test_untrusted_labeler_is_refused(self):
        r, gh = make()
        gh.add_issue(1, [A.L_READY], labeled_by="outsider")
        r.dispatch({n: gh.issues[n] for n in gh.issues})
        self.assertEqual(gh.dispatches, [])
        self.assertNotIn(A.L_READY, gh.labels(1))

    def test_dependencies_block_then_release(self):
        r, gh = make()
        gh.add_issue(5)
        gh.add_issue(6, [A.L_READY], body="### Dependencies\n\nDepends on #5\n")
        r.dispatch({n: gh.issues[n] for n in gh.issues if gh.issues[n]["state"] == "open"})
        self.assertEqual(gh.dispatches, [])
        self.assertIn(A.L_BLOCKED, gh.labels(6))
        gh.issues[5]["state"] = "closed"
        r.dispatch({6: gh.issues[6]})
        self.assertEqual([int(i["issue"]) for _, i in gh.dispatches], [6])
        self.assertNotIn(A.L_BLOCKED, gh.labels(6))

    def test_human_only_never_dispatched(self):
        r, gh = make()
        gh.add_issue(1, [A.L_READY, A.L_HUMAN_ONLY])
        r.dispatch({1: gh.issues[1]})
        self.assertEqual(gh.dispatches, [])

    def test_attempt_limit_escalates(self):
        r, gh = make({"AGENT_MAX_IMPL_ATTEMPTS": "2"})
        gh.add_issue(1, [A.L_READY])
        for _ in range(2):
            gh._comment(1, A.marker("run-start", mode="implement"), at=T0 - timedelta(days=1))
        r.dispatch({1: gh.issues[1]})
        self.assertEqual(gh.dispatches, [])
        self.assertIn(A.L_HUMAN, gh.labels(1))

    def test_usage_limit_pauses_everything(self):
        r, gh = make()
        gh.add_issue(1, [A.L_READY])
        gh.add_issue(2)
        gh._comment(2, A.marker("usage-limit"), at=A.now() - timedelta(minutes=5))
        r.dispatch({n: gh.issues[n] for n in gh.issues})
        self.assertEqual(gh.dispatches, [])

    # --- gate ---------------------------------------------------------------

    def gate_setup(self, checks, review="success", **pr):
        r, gh = make()
        gh.add_issue(1, [A.L_VALIDATING])
        gh.add_pr(10, 1, **pr)
        gh.set_checks("abc1234def", checks, review)
        return r, gh

    def test_gate_all_green_marks_ready_and_enables_auto_merge(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "success"})
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertIn("markPullRequestReadyForReview", gh.graphql_calls)
        self.assertIn("enablePullRequestAutoMerge", gh.graphql_calls)
        self.assertIn(A.L_REVIEW, gh.labels(1))
        self.assertNotIn(A.L_VALIDATING, gh.labels(1))

    def test_gate_pending_waits(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": None, "Build": "success", "Policy": "success"})
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertEqual(gh.graphql_calls, [])
        self.assertIn(A.L_VALIDATING, gh.labels(1))

    def test_gate_ci_failure_requests_bounded_remediation(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "failure", "Build": "success", "Policy": "success"})
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertIn(A.L_FIX, gh.labels(1))
        reqs = gh.markers(10, kinds={"remediation-request"})
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["reason"], "ci")
        self.assertEqual(gh.graphql_calls, [])  # never ready or auto-merge while red

    def test_gate_same_failure_twice_escalates(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "failure", "Build": "success", "Policy": "success"})
        sig = A.failure_signature(["Test"])
        gh._comment(10, A.marker("remediation-request", reason="ci", sha="old", sig=sig), at=T0 - timedelta(hours=3))
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertIn(A.L_HUMAN, gh.labels(1))
        self.assertEqual(len(gh.markers(10, kinds={"remediation-request"})), 1)

    def test_gate_remediation_limit(self):
        r, gh = self.gate_setup({"Lint": "failure", "Test": "success", "Build": "success", "Policy": "success"})
        for i in range(3):
            gh._comment(10, A.marker("remediation-request", reason="ci", sha="s%d" % i, sig="x%d" % i), at=T0 - timedelta(hours=5 - i))
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertIn(A.L_HUMAN, gh.labels(1))

    def test_gate_policy_failure_goes_to_human(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "failure"})
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertIn(A.L_HUMAN, gh.labels(1))
        self.assertEqual(gh.markers(10, kinds={"remediation-request"}), [])

    def test_gate_review_failure_requests_remediation(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "success"}, review="failure")
        r.gate(gh.pulls[10], gh.issues[1])
        reqs = gh.markers(10, kinds={"remediation-request"})
        self.assertEqual(reqs[0]["reason"], "review")

    def test_gate_ignores_review_status_from_other_creators(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "success"})
        gh.statuses["abc1234def"][0]["creator"] = {"login": "agent-bot[bot]"}  # forged by the agent's app
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertNotIn("enablePullRequestAutoMerge", gh.graphql_calls)

    def test_gate_accepts_review_status_without_creator(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "success"}, review="failure")
        gh.statuses["abc1234def"][0]["creator"] = None  # how GitHub records GITHUB_TOKEN statuses
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertEqual(gh.markers(10, kinds={"remediation-request"})[0]["reason"], "review")

    def test_gate_reruns_review_skipped_while_paused(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "success"}, review="pending")
        gh.statuses["abc1234def"][0]["description"] = "Agents paused (AGENTS_PAUSED)"
        r.gate(gh.pulls[10], gh.issues[1])
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertEqual([w for w, _ in gh.dispatches], ["agent-review.yml"])

    def test_gate_behind_updates_branch_first(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "success"}, mergeable_state="behind")
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertEqual(gh.updates, [10])
        self.assertNotIn("enablePullRequestAutoMerge", gh.graphql_calls)

    def test_gate_conflict_requests_remediation(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "success"}, mergeable_state="dirty")
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertEqual(gh.markers(10, kinds={"remediation-request"})[0]["reason"], "conflict")

    def test_approval_only_counts_for_current_head(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "success"}, draft=False)
        gh.pulls[10]["auto_merge"] = {"enabled_by": {}}
        gh.reviews[10] = [{"id": 1, "state": "APPROVED", "commit_id": "oldsha", "user": {"login": "maintainer"}}]
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertIn(A.L_REVIEW, gh.labels(1))
        self.assertNotIn(A.L_APPROVED, gh.labels(1))
        gh.reviews[10] = [{"id": 2, "state": "APPROVED", "commit_id": "abc1234def", "user": {"login": "maintainer"}}]
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertIn(A.L_APPROVED, gh.labels(1))

    def test_human_changes_requested_triggers_one_remediation(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "success"}, draft=False)
        gh.reviews[10] = [{"id": 77, "state": "CHANGES_REQUESTED", "commit_id": "abc1234def", "user": {"login": "maintainer"}}]
        r.gate(gh.pulls[10], gh.issues[1])
        reqs = gh.markers(10, kinds={"remediation-request"})
        self.assertEqual((len(reqs), reqs[0]["reason"], reqs[0]["review_id"]), (1, "human", 77))
        # Remove auto-fix as if the remediation ran; the same review must not trigger again.
        gh.remove_label(1, A.L_FIX)
        gh.add_labels(1, [A.L_VALIDATING])
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertEqual(len(gh.markers(10, kinds={"remediation-request"})), 1)

    def test_untrusted_review_is_ignored(self):
        r, gh = self.gate_setup({"Lint": "success", "Test": "success", "Build": "success", "Policy": "success"}, draft=False)
        gh.reviews[10] = [{"id": 5, "state": "CHANGES_REQUESTED", "commit_id": "abc1234def", "user": {"login": "outsider"}}]
        r.gate(gh.pulls[10], gh.issues[1])
        self.assertEqual(gh.markers(10, kinds={"remediation-request"}), [])

    def test_human_pr_gets_review_status_once(self):
        r, gh = make()
        gh.add_pr(20, 99, sha="dep0001")
        gh.pulls[20]["head"]["ref"] = "dependabot/github_actions/x"
        r.mark_human_pr(gh.pulls[20])
        r.mark_human_pr(gh.pulls[20])
        self.assertEqual([st["state"] for st in gh.statuses["dep0001"]], ["success"])

    def test_remediation_dispatch_uses_request(self):
        r, gh = make()
        gh.add_issue(1, [A.L_FIX])
        gh.add_pr(10, 1)
        c = gh._comment(10, A.marker("remediation-request", reason="ci", sha="abc1234def", sig="s"))
        r.dispatch({1: gh.issues[1]})
        self.assertEqual(gh.dispatches[0][1], {"issue": "1", "mode": "remediate", "request": str(c["id"])})
        self.assertIn(A.L_WORKING, gh.labels(1))

    def test_stale_working_is_requeued(self):
        r, gh = make()
        gh.add_issue(1, [A.L_WORKING])
        gh._comment(1, A.marker("run-start", mode="implement"), at=A.now() - timedelta(hours=2))
        r.recover_stale({1: gh.issues[1]})
        self.assertIn(A.L_READY, gh.labels(1))
        self.assertNotIn(A.L_WORKING, gh.labels(1))


if __name__ == "__main__":
    unittest.main()
