import json

from jarvis.db.connection import get_conn
from jarvis.tasks import github as github_tasks


def test_render_summary_comment_contains_marker() -> None:
    body = github_tasks._render_summary_comment(
        repo="acme/repo",
        number=5,
        title="Improve webhook handling",
        base_ref="dev",
        head_ref="agent/webhook",
        commits=2,
        changed_files=3,
        additions=42,
        deletions=9,
        files=[
            {
                "filename": "src/jarvis/routes/api/webhooks.py",
                "status": "modified",
                "additions": 10,
                "deletions": 2,
            },
            {
                "filename": "src/jarvis/db/migrations/024_add_table.sql",
                "status": "added",
                "additions": 20,
                "deletions": 0,
            },
        ],
    )
    assert github_tasks.SUMMARY_MARKER in body
    assert "Jarvis PR Summary (Stage 1)" in body
    assert "Migrations touched: yes" in body


def test_github_pr_summary_skips_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_PR_SUMMARY_ENABLED", "0")
    result = github_tasks.github_pr_summary(
        owner="acme",
        repo="repo",
        pull_number=1,
        action="opened",
        base_ref="dev",
    )
    assert result["ok"] is True
    assert result["skipped"] == "github_pr_summary_disabled"


def test_github_pr_summary_success(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_PR_SUMMARY_ENABLED", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPO_ALLOWLIST", "acme/*")
    monkeypatch.setenv("GITHUB_API_BASE_URL", "https://api.github.com")
    github_tasks.get_settings.cache_clear()

    monkeypatch.setattr(
        github_tasks,
        "_fetch_pr_and_files",
        lambda **kwargs: (
            {
                "title": "Title",
                "head": {"ref": "agent/topic"},
                "commits": 1,
                "changed_files": 1,
                "additions": 4,
                "deletions": 1,
            },
            [{"filename": "README.md", "status": "modified", "additions": 4, "deletions": 1}],
        ),
    )
    monkeypatch.setattr(
        github_tasks,
        "_upsert_summary_comment",
        lambda **kwargs: {"action": "created", "comment_id": 123},
    )

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(github_tasks.httpx, "Client", DummyClient)
    result = github_tasks.github_pr_summary(
        owner="acme",
        repo="repo",
        pull_number=9,
        action="opened",
        base_ref="dev",
    )
    assert result["ok"] is True
    assert result["result"]["comment_id"] == 123


def test_github_pr_summary_records_bug_on_failure(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_PR_SUMMARY_ENABLED", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_API_BASE_URL", "https://api.github.com")
    github_tasks.get_settings.cache_clear()

    def boom(**kwargs):
        raise RuntimeError("github api failure")

    monkeypatch.setattr(github_tasks, "_fetch_pr_and_files", boom)

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(github_tasks.httpx, "Client", DummyClient)
    result = github_tasks.github_pr_summary(
        owner="acme",
        repo="repo",
        pull_number=3,
        action="opened",
        base_ref="dev",
    )
    assert result["ok"] is False
    assert str(result["bug_id"]).startswith("bug_")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT title, description FROM bug_reports WHERE id=?",
            (result["bug_id"],),
        ).fetchone()
    assert row is not None
    assert "GitHub PR summary automation failed" in str(row["title"])
    payload = json.loads(str(row["description"]))
    assert payload["pull_number"] == 3


def test_extract_chat_prompt_context_contains_request() -> None:
    prompt = github_tasks._render_prompt_context(
        owner="acme",
        repo="repo",
        number=7,
        pr={"title": "Fix auth", "base": {"ref": "dev"}, "head": {"ref": "fix/auth"}},
        files=[
            {
                "filename": "src/jarvis/auth/service.py",
                "status": "modified",
                "additions": 2,
                "deletions": 1,
            }
        ],
        recent_comments=[{"body": "please add tests", "user": {"login": "bob"}}],
        user_message="/jarvis review auth changes",
    )
    assert "Requester message:" in prompt
    assert "/jarvis review auth changes" in prompt
    assert "src/jarvis/auth/service.py" in prompt


def test_github_pr_chat_success(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_PR_SUMMARY_ENABLED", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_BOT_LOGIN", "jarvis")
    github_tasks.get_settings.cache_clear()

    monkeypatch.setattr(
        github_tasks,
        "_fetch_pr_and_files",
        lambda **kwargs: (
            {"title": "Title", "base": {"ref": "dev"}, "head": {"ref": "agent/topic"}},
            [{"filename": "README.md", "status": "modified", "additions": 4, "deletions": 1}],
        ),
    )
    monkeypatch.setattr(
        github_tasks,
        "_fetch_issue_comments",
        lambda **kwargs: [{"body": "looks good", "user": {"login": "alice"}}],
    )

    async def fake_generate(prompt: str, chat_mode: str) -> str:
        assert chat_mode == "review"
        return "Response text"

    monkeypatch.setattr(github_tasks, "_generate_chat_reply_for_mode", fake_generate)
    monkeypatch.setattr(
        github_tasks,
        "_post_issue_comment",
        lambda **kwargs: {"comment_id": 555},
    )

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(github_tasks.httpx, "Client", DummyClient)
    result = github_tasks.github_pr_chat(
        owner="acme",
        repo="repo",
        pull_number=12,
        comment_body="review this",
        chat_mode="review",
        commenter_login="alice",
    )
    assert result["ok"] is True
    assert result["result"]["comment_id"] == 555


def test_github_pr_chat_records_bug_on_failure(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_PR_SUMMARY_ENABLED", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_BOT_LOGIN", "jarvis")
    github_tasks.get_settings.cache_clear()

    def boom(**kwargs):
        raise RuntimeError("chat failure")

    monkeypatch.setattr(github_tasks, "_fetch_pr_and_files", boom)

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(github_tasks.httpx, "Client", DummyClient)
    result = github_tasks.github_pr_chat(
        owner="acme",
        repo="repo",
        pull_number=13,
        comment_body="review this",
        chat_mode="risks",
        commenter_login="alice",
    )
    assert result["ok"] is False
    assert str(result["bug_id"]).startswith("bug_")


def test_github_pr_chat_help_mode_skips_pr_fetch(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_PR_SUMMARY_ENABLED", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    github_tasks.get_settings.cache_clear()

    def fail_if_called(**kwargs):
        raise AssertionError("PR fetch should not be called in help mode")

    monkeypatch.setattr(github_tasks, "_fetch_pr_and_files", fail_if_called)
    monkeypatch.setattr(github_tasks, "_fetch_issue_comments", fail_if_called)
    monkeypatch.setattr(
        github_tasks,
        "_post_issue_comment",
        lambda **kwargs: {"comment_id": 999},
    )

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(github_tasks.httpx, "Client", DummyClient)
    result = github_tasks.github_pr_chat(
        owner="acme",
        repo="repo",
        pull_number=14,
        comment_body="help",
        chat_mode="help",
        commenter_login="alice",
    )
    assert result["ok"] is True
    assert result["result"]["comment_id"] == 999


def test_github_issue_sync_bug_report_success(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ISSUE_SYNC_ENABLED", "1")
    monkeypatch.setenv("GITHUB_ISSUE_SYNC_REPO", "acme/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    github_tasks.get_settings.cache_clear()

    bug_id = github_tasks._record_bug_report("Bug for sync", {"x": 1}, priority="medium")
    with get_conn() as conn:
        conn.execute("UPDATE bug_reports SET kind='feature' WHERE id=?", (bug_id,))

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"number": 77, "html_url": "https://github.com/acme/repo/issues/77"}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, *args, **kwargs):
            return DummyResponse()

    monkeypatch.setattr(github_tasks.httpx, "Client", DummyClient)
    result = github_tasks.github_issue_sync_bug_report(bug_id=bug_id)
    assert result["ok"] is True
    assert result["issue_number"] == 77
    with get_conn() as conn:
        row = conn.execute(
            "SELECT github_issue_number, github_issue_url FROM bug_reports WHERE id=?",
            (bug_id,),
        ).fetchone()
    assert row is not None
    assert int(row["github_issue_number"]) == 77


def test_github_issue_sync_bug_report_records_sync_error(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ISSUE_SYNC_ENABLED", "1")
    monkeypatch.setenv("GITHUB_ISSUE_SYNC_REPO", "acme/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    github_tasks.get_settings.cache_clear()

    bug_id = github_tasks._record_bug_report("Bug for sync failure", {"x": 1}, priority="medium")

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, *args, **kwargs):
            raise RuntimeError("gh down")

    monkeypatch.setattr(github_tasks.httpx, "Client", DummyClient)
    result = github_tasks.github_issue_sync_bug_report(bug_id=bug_id)
    assert result["ok"] is False
    with get_conn() as conn:
        row = conn.execute(
            "SELECT github_sync_error FROM bug_reports WHERE id=?",
            (bug_id,),
        ).fetchone()
    assert row is not None
    assert "gh down" in str(row["github_sync_error"])
