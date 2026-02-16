"""Textual TUI setup wizard for Jarvis."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Center, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
)

from jarvis.cli.checks import (
    CheckResult,
    check_agent_bundles,
    check_database,
    check_http_service,
    check_migrations_applied,
    check_python_version,
    check_tool_exists,
)
from jarvis.cli.env_groups import ENV_GROUPS, EnvGroup

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _load_existing_env() -> dict[str, str]:
    env_path = PROJECT_ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip()
    return values


def _write_env(values: dict[str, str]) -> None:
    env_path = PROJECT_ROOT / ".env"
    lines: list[str] = []
    for key, val in sorted(values.items()):
        lines.append(f"{key}={val}")
    env_path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


class WelcomeScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            with Vertical(id="welcome-box"):
                yield Static(
                    "[bold]Welcome to Jarvis Setup[/bold]\n\n"
                    "This wizard will walk you through:\n\n"
                    "  1. Checking prerequisites (python3, uv, git, docker)\n"
                    "  2. Configuring your .env file\n"
                    "  3. Starting Docker services\n"
                    "  4. Running database migrations\n"
                    "  5. Verifying everything works\n",
                    id="welcome-text",
                )
                yield Button("Begin", variant="primary", id="begin-btn")
        yield Footer()

    @on(Button.Pressed, "#begin-btn")
    def go_next(self) -> None:
        self.app.push_screen(PrereqScreen())


class PrereqScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Label("Checking prerequisites...")
            yield DataTable(id="prereq-table")
            yield Button("Continue", variant="primary", id="continue-btn", disabled=True)
            yield Button("Quit", variant="error", id="quit-btn")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#prereq-table", DataTable)
        table.add_columns("Check", "Status", "Detail")

        all_ok = True
        checks = [
            check_tool_exists("python3"),
            check_tool_exists("uv"),
            check_tool_exists("git"),
            check_tool_exists("docker"),
            check_python_version(),
        ]
        for result in checks:
            icon = "\u2713" if result.passed else "\u2717"
            table.add_row(result.name, icon, result.message)
            if not result.passed:
                all_ok = False

        btn = self.query_one("#continue-btn", Button)
        btn.disabled = not all_ok
        if not all_ok:
            table.add_row("", "", "[red]Fix missing tools before continuing.[/red]")

    @on(Button.Pressed, "#continue-btn")
    def go_next(self) -> None:
        self.app.push_screen(EnvWizardScreen(group_index=0))

    @on(Button.Pressed, "#quit-btn")
    def quit_app(self) -> None:
        self.app.exit()


class EnvWizardScreen(Screen[None]):
    def __init__(self, group_index: int) -> None:
        super().__init__()
        self.group_index = group_index
        self.group: EnvGroup = ENV_GROUPS[group_index]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label(
                f"[bold]{self.group.title}[/bold] ({self.group_index + 1}/{len(ENV_GROUPS)})"
            )
            yield Static(self.group.description)
            yield Static("")
            for var in self.group.vars:
                existing = self.app.env_values.get(var.name, "")  # type: ignore[attr-defined]
                default = existing or var.default
                yield Label(f"{var.name} — {var.description}")
                yield Input(
                    value=default,
                    placeholder=var.name,
                    password=var.secret,
                    id=f"input-{var.name}",
                )
            yield Static("")
            with Center():
                yield Button("Continue", variant="primary", id="continue-btn")
                if not self.group.required:
                    yield Button("Skip (use defaults)", id="skip-btn")
        yield Footer()

    def _collect_values(self) -> None:
        for var in self.group.vars:
            inp = self.query_one(f"#input-{var.name}", Input)
            value = inp.value.strip()
            if value:
                self.app.env_values[var.name] = value  # type: ignore[attr-defined]
            elif var.default:
                self.app.env_values[var.name] = var.default  # type: ignore[attr-defined]

    def _advance(self) -> None:
        next_idx = self.group_index + 1
        if next_idx < len(ENV_GROUPS):
            self.app.push_screen(EnvWizardScreen(group_index=next_idx))
        else:
            _write_env(self.app.env_values)  # type: ignore[attr-defined]
            self.app.push_screen(DockerScreen())

    @on(Button.Pressed, "#continue-btn")
    def go_next(self) -> None:
        self._collect_values()
        self._advance()

    @on(Button.Pressed, "#skip-btn")
    def skip_group(self) -> None:
        for var in self.group.vars:
            if var.default:
                self.app.env_values[var.name] = var.default  # type: ignore[attr-defined]
        self._advance()


class DockerScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Label("[bold]Starting Docker Services[/bold]")
            yield RichLog(id="docker-log", highlight=True)
            yield Button("Continue", variant="primary", id="continue-btn", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.run_docker()

    async def _run_docker(self) -> None:
        log = self.query_one("#docker-log", RichLog)
        log.write("[dim]Running: docker compose up -d[/dim]\n")
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "compose",
                "up",
                "-d",
                cwd=str(PROJECT_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                log.write(line.decode(errors="replace").rstrip())
            await proc.wait()
            if proc.returncode == 0:
                log.write("\n[green]Docker services started.[/green]")
            else:
                log.write(f"\n[red]docker compose exited with code {proc.returncode}[/red]")
        except FileNotFoundError:
            log.write("[red]docker not found on PATH[/red]")
        except Exception as exc:
            log.write(f"[red]Error: {exc}[/red]")

        btn = self.query_one("#continue-btn", Button)
        btn.disabled = False

    def run_docker(self) -> None:
        asyncio.ensure_future(self._run_docker())

    @on(Button.Pressed, "#continue-btn")
    def go_next(self) -> None:
        self.app.push_screen(MigrateScreen())


class MigrateScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Label("[bold]Running Database Migrations[/bold]")
            yield RichLog(id="migrate-log", highlight=True)
            yield Button("Continue", variant="primary", id="continue-btn", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.run_migrate()

    async def _run_migrate(self) -> None:
        log = self.query_one("#migrate-log", RichLog)
        log.write("[dim]Running migrations...[/dim]\n")
        try:
            from jarvis.db.migrations.runner import run_migrations

            run_migrations()
            log.write("[green]Migrations applied successfully.[/green]")
        except Exception as exc:
            log.write(f"[red]Migration error: {exc}[/red]")

        btn = self.query_one("#continue-btn", Button)
        btn.disabled = False

    def run_migrate(self) -> None:
        asyncio.ensure_future(self._run_migrate())

    @on(Button.Pressed, "#continue-btn")
    def go_next(self) -> None:
        self.app.push_screen(VerifyScreen())


class VerifyScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Label("[bold]Verification[/bold]")
            yield DataTable(id="verify-table")
            yield Button("Continue", variant="primary", id="continue-btn")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#verify-table", DataTable)
        table.add_columns("Check", "Status", "Detail")

        checks: list[CheckResult] = [check_agent_bundles(PROJECT_ROOT / "agents")]

        try:
            from jarvis.config import Settings

            settings = Settings()
            checks.append(check_database(settings.app_db))
            checks.append(check_migrations_applied(settings.app_db))
            checks.append(
                check_http_service("Ollama", settings.ollama_base_url, "/api/tags")
            )
            sglang_base = settings.sglang_base_url.rstrip("/v1").rstrip("/")
            checks.append(check_http_service("SGLang", sglang_base, "/health"))
            checks.append(
                check_http_service("SearXNG", settings.searxng_base_url, "/")
            )
        except Exception:
            pass

        for result in checks:
            icon = "\u2713" if result.passed else "\u2717"
            table.add_row(result.name, icon, result.message)

    @on(Button.Pressed, "#continue-btn")
    def go_next(self) -> None:
        self.app.push_screen(DoneScreen())


class DoneScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            with Vertical(id="done-box"):
                yield Static(
                    "[bold green]Setup Complete![/bold green]\n\n"
                    "Next steps:\n\n"
                    "  [bold]make api[/bold]     — Start the FastAPI server\n"
                    "  [bold]make worker[/bold]  — Start the Celery worker\n"
                    "  [bold]jarvis doctor[/bold] — Run full diagnostics\n",
                    id="done-text",
                )
                yield Button("Exit", variant="primary", id="exit-btn")
        yield Footer()

    @on(Button.Pressed, "#exit-btn")
    def quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class SetupWizardApp(App[None]):
    TITLE = "Jarvis Setup"
    CSS = """
    #welcome-box, #done-box {
        width: 70;
        height: auto;
        padding: 2 4;
    }
    """

    env_values: dict[str, str] = {}

    def on_mount(self) -> None:
        self.env_values = _load_existing_env()
        self.push_screen(WelcomeScreen())


def run_setup_wizard() -> None:
    app = SetupWizardApp()
    app.run()
