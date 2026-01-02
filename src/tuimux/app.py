from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Provider
from textual.containers import Container, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.worker import Worker, WorkerState
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

from tuimux.tmux import Session, TmuxClient, TmuxError, Window


class SessionsListView(ListView):
    BINDINGS = [
        Binding("enter", "select_cursor", "Attach/Switch"),
        Binding("up", "cursor_up", "Cursor up", show=False),
        Binding("down", "cursor_down", "Cursor down", show=False),
    ]


class SessionItem(ListItem):
    def __init__(self, session: Session) -> None:
        parts = [f"{session.name}: {session.windows} windows"]
        if session.created:
            parts.append(f"(created {session.created})")
        if session.attached:
            parts.append("(attached)")
        text = " ".join(parts)
        super().__init__(Static(text))
        self.session = session


class WindowItem(ListItem):
    def __init__(self, window: Window) -> None:
        marker = "*" if window.active else " "
        text = f"{marker} {window.index}: {window.name}"
        super().__init__(Static(text))
        self.window = window


class TuimuxCommandsProvider(Provider):
    def _commands(self) -> list[tuple[str, str, Callable[[], object]]]:
        app = self.app
        return [
            (
                "Attach / switch session",
                "Attach to the selected session (detach with Ctrl-b d).",
                app.action_attach,
            ),
            ("Refresh", "Reload sessions and windows.", app.action_refresh),
            ("New session", "Create a new tmux session.", app.action_new_session),
            ("Rename session", "Rename the selected session.", app.action_rename_session),
            ("New window", "Create a new window in the selected session.", app.action_new_window),
            ("Kill session", "Kill the selected session.", app.action_kill_session),
            ("Kill window", "Kill the selected window.", app.action_kill_window),
            ("Help", "Open the help screen.", app.action_help),
        ]

    async def discover(self):
        for name, help_text, callback in self._commands():
            yield DiscoveryHit(name, callback, help=help_text)

    async def search(self, query: str):
        matcher = self.matcher(query)
        for name, help_text, callback in self._commands():
            if (match := matcher.match(name)) > 0:
                yield Hit(match, matcher.highlight(name), callback, help=help_text)


class PromptScreen(ModalScreen[Optional[str]]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        title: str,
        placeholder: str = "",
        value: str = "",
        allow_empty: bool = False,
    ) -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._value = value
        self._allow_empty = allow_empty

    def compose(self) -> ComposeResult:
        with Container(id="prompt"):
            yield Static(self._title, id="prompt-title")
            yield Input(placeholder=self._placeholder, value=self._value, id="prompt-input")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value and not self._allow_empty:
            self.dismiss(None)
        else:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmAttachScreen(ModalScreen[bool]):
    BINDINGS = [
        ("enter", "confirm", "Attach"),
        ("a", "confirm", "Attach"),
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    def __init__(self, session_name: str) -> None:
        super().__init__()
        self._session_name = session_name

    def compose(self) -> ComposeResult:
        with Container(id="confirm"):
            yield Static("Attach to session", id="confirm-title")
            yield Static(
                f"You are about to attach to \"{self._session_name}\".",
                id="confirm-body",
            )
            yield Static("Detach later with Ctrl-b d.", id="confirm-hint")
            yield Static("Press Enter to attach, Esc to cancel.", id="confirm-footer")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
        ("enter", "dismiss", "Close"),
    ]

    HELP_TEXT = (
        "Tuimux Help\n"
        "\n"
        "Basics\n"
        "- Session: A running tmux environment with its own windows.\n"
        "- Window: A tab inside a session; each window can hold panes.\n"
        "- Attached: A session currently connected to a tmux client.\n"
        "\n"
        "Navigation\n"
        "- Up/Down: Move through the list.\n"
        "- Tab: Switch focus between Sessions and Windows.\n"
        "- Enter: Attach/switch to the selected session.\n"
        "\n"
        "Actions\n"
        "- r: Refresh sessions/windows.\n"
        "- n: New session.\n"
        "- e: Rename selected session.\n"
        "- c: New window in selected session.\n"
        "- x: Kill selected session.\n"
        "- d: Kill selected window.\n"
        "- q: Quit.\n"
        "\n"
        "Learn more\n"
        "- https://github.com/tmux/tmux/wiki\n"
        "- https://man.openbsd.org/tmux\n"
    )

    def compose(self) -> ComposeResult:
        with Container(id="help"):
            yield Static(self.HELP_TEXT, id="help-text")

    def action_dismiss(self) -> None:
        self.dismiss(None)


@dataclass(frozen=True)
class _WindowsLoadResult:
    request_id: int
    session_name: str
    windows: list[Window]


class TuimuxApp(App):
    COMMANDS = App.COMMANDS | {TuimuxCommandsProvider}

    CSS = """
    Screen {
        background: #0b0f14;
        color: #e6eef9;
    }

    PromptScreen {
        align: center middle;
    }

    #content {
        height: 1fr;
        layout: horizontal;
        padding: 1;
    }

    .panel {
        background: #121923;
        border: tall #1b2533;
        padding: 1;
        width: 1fr;
        margin: 0 1;
    }

    .panel-title {
        color: #7b8aa1;
        text-style: bold;
        margin-bottom: 1;
    }

    ListView {
        background: transparent;
        border: round #1b2533;
        height: 1fr;
    }

    ListItem.--highlight {
        background: #1b2533;
    }

    #status {
        height: 3;
        padding: 0 1;
        background: #0f141b;
        color: #7b8aa1;
    }

    #status.error {
        color: #ff9b85;
    }

    #prompt {
        width: 60%;
        max-width: 60;
        padding: 2;
        border: heavy #8bd5ff;
        background: #0f141b;
    }

    #prompt-title {
        margin-bottom: 1;
        text-style: bold;
    }

    #confirm {
        width: 70%;
        max-width: 70;
        padding: 2;
        border: heavy #8bd5ff;
        background: #0f141b;
    }

    #confirm-title {
        margin-bottom: 1;
        text-style: bold;
    }

    #confirm-body {
        margin-bottom: 1;
    }

    #confirm-hint {
        color: #9fb0c6;
    }

    #confirm-footer {
        margin-top: 1;
        color: #7b8aa1;
    }

    #help {
        width: 80%;
        max-width: 90;
        padding: 2;
        border: heavy #8bd5ff;
        background: #0f141b;
    }

    #help-text {
        color: #c6d2e3;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("enter", "attach", "Attach/Switch"),
        ("n", "new_session", "New Session"),
        ("e", "rename_session", "Rename Session"),
        ("h", "help", "Help"),
        ("c", "new_window", "New Window"),
        ("x", "kill_session", "Kill Session"),
        ("d", "kill_window", "Kill Window"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._client = TmuxClient()
        self._sessions: list[Session] = []
        self._windows: list[Window] = []
        self._current_session: str | None = None
        self._windows_load_timer: Timer | None = None
        self._pending_windows_session: str | None = None
        self._pending_windows_force: bool = False
        self._windows_request_id: int = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="content"):
            with Vertical(classes="panel", id="sessions-panel"):
                yield Static("Sessions", classes="panel-title")
                yield SessionsListView(id="sessions")
            with Vertical(classes="panel", id="windows-panel"):
                yield Static("Windows", classes="panel-title")
                yield ListView(id="windows")
        yield Static("Ready.", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_data()
        self.query_one("#sessions", ListView).focus()

    def refresh_data(self) -> None:
        self._current_session = None
        try:
            self._sessions = self._client.list_sessions()
        except TmuxError as exc:
            self._sessions = []
            self._windows = []
            self.set_status(str(exc), error=True)
            self.update_lists()
            return

        if not self._sessions:
            self._windows = []
            self.set_status("No tmux sessions found.")
        else:
            self.set_status("Loaded tmux sessions.")
            self.update_lists()

    def update_lists(self) -> None:
        sessions_view = self.query_one("#sessions", ListView)
        windows_view = self.query_one("#windows", ListView)

        with self.batch_update():
            sessions_view.clear()
            sessions_view.extend(SessionItem(session) for session in self._sessions)

            if self._sessions:
                sessions_view.index = 0
            else:
                windows_view.clear()

    def request_windows_load(
        self, session_name: str, *, force: bool = False, immediate: bool = False
    ) -> None:
        """Request a windows refresh for a given session.

        When navigating sessions quickly we debounce the tmux call to avoid
        thrashing the UI with rapid clear/mount cycles (which can look like flicker).
        """
        self._pending_windows_session = session_name
        self._pending_windows_force = self._pending_windows_force or force

        if self._windows_load_timer is not None:
            self._windows_load_timer.stop()
            self._windows_load_timer = None

        delay = 0.0 if immediate else 0.08
        self._windows_load_timer = self.set_timer(delay, self._start_windows_load)

    def _start_windows_load(self) -> None:
        session_name = self._pending_windows_session
        if session_name is None:
            return
        force = self._pending_windows_force
        self._pending_windows_force = False

        selected = self.get_selected_session()
        if selected is None or selected.name != session_name:
            return

        if not force and session_name == self._current_session:
            return

        self._windows_request_id += 1
        request_id = self._windows_request_id

        def work() -> _WindowsLoadResult:
            return _WindowsLoadResult(
                request_id=request_id,
                session_name=session_name,
                windows=self._client.list_windows(session_name),
            )

        self.run_worker(
            work,
            name=f"windows:{request_id}",
            group="windows",
            description=session_name,
            exclusive=True,
            thread=True,
            exit_on_error=False,
        )

    async def update_windows_list(self) -> None:
        windows_view = self.query_one("#windows", ListView)
        with self.batch_update():
            await windows_view.clear()
            if self._windows:
                await windows_view.extend(WindowItem(window) for window in self._windows)
                windows_view.index = 0

    def get_selected_session(self) -> Session | None:
        sessions_view = self.query_one("#sessions", ListView)
        item = sessions_view.highlighted_child
        if isinstance(item, SessionItem):
            return item.session
        return None

    def get_selected_window(self) -> Window | None:
        windows_view = self.query_one("#windows", ListView)
        item = windows_view.highlighted_child
        if isinstance(item, WindowItem):
            return item.window
        return None

    def set_status(self, message: str, error: bool = False) -> None:
        status = self.query_one("#status", Static)
        status.update(message)
        if error:
            status.add_class("error")
        else:
            status.remove_class("error")

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "sessions" and isinstance(event.item, SessionItem):
            self.request_windows_load(event.item.session.name)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "sessions":
            self.action_attach()

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_attach(self) -> None:
        session = self.get_selected_session()
        if not session:
            self.set_status("Select a session to attach.", error=True)
            return
        if self._client.inside_tmux:
            try:
                self._client.switch_client(session.name)
            except TmuxError as exc:
                self.set_status(str(exc), error=True)
            return

        async def handle_result(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                self._client.attach(session.name)
            except TmuxError as exc:
                self.set_status(str(exc), error=True)

        self.push_screen(ConfirmAttachScreen(session.name), callback=handle_result)

    def action_new_session(self) -> None:
        async def handle_result(result: Optional[str]) -> None:
            if not result:
                return
            try:
                self._client.new_session(result)
            except TmuxError as exc:
                self.set_status(str(exc), error=True)
                return
            self.refresh_data()

        self.push_screen(
            PromptScreen("New session name", placeholder="work"),
            callback=handle_result,
        )

    def action_rename_session(self) -> None:
        session = self.get_selected_session()
        if not session:
            self.set_status("Select a session to rename.", error=True)
            return

        async def handle_result(result: Optional[str]) -> None:
            if not result:
                return
            if result == session.name:
                self.set_status("Session name unchanged.")
                return
            try:
                self._client.rename_session(session.name, result)
            except TmuxError as exc:
                self.set_status(str(exc), error=True)
                return
            self.refresh_data()

        self.push_screen(
            PromptScreen(
                "Rename session",
                placeholder="new-name",
                value=session.name,
            ),
            callback=handle_result,
        )

    def action_new_window(self) -> None:
        session = self.get_selected_session()
        if not session:
            self.set_status("Select a session first.", error=True)
            return

        async def handle_result(result: Optional[str]) -> None:
            if result is None:
                return
            try:
                name = result or None
                self._client.new_window(session.name, name)
            except TmuxError as exc:
                self.set_status(str(exc), error=True)
                return
            self.request_windows_load(session.name, force=True, immediate=True)

        self.push_screen(
            PromptScreen("New window name", placeholder="shell", allow_empty=True),
            callback=handle_result,
        )

    def action_kill_session(self) -> None:
        session = self.get_selected_session()
        if not session:
            self.set_status("Select a session to kill.", error=True)
            return
        try:
            self._client.kill_session(session.name)
        except TmuxError as exc:
            self.set_status(str(exc), error=True)
            return
        self.refresh_data()

    def action_kill_window(self) -> None:
        window = self.get_selected_window()
        if not window:
            self.set_status("Select a window to kill.", error=True)
            return
        try:
            self._client.kill_window(window.id)
        except TmuxError as exc:
            self.set_status(str(exc), error=True)
            return
        session = self.get_selected_session()
        if session:
            self.request_windows_load(session.name, force=True, immediate=True)

    def on_key(self, event: Key) -> None:
        if event.key == "tab":
            sessions = self.query_one("#sessions", ListView)
            windows = self.query_one("#windows", ListView)
            if sessions.has_focus:
                windows.focus()
            else:
                sessions.focus()
            event.prevent_default()

    async def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != "windows":
            return

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, _WindowsLoadResult):
                return
            if result.request_id != self._windows_request_id:
                return
            selected = self.get_selected_session()
            if selected is None or selected.name != result.session_name:
                return
            self._current_session = result.session_name
            self._windows = result.windows
            await self.update_windows_list()
            return

        if event.state == WorkerState.ERROR:
            name = event.worker.name
            if not name.startswith("windows:"):
                return
            try:
                request_id = int(name.split(":", 1)[1])
            except ValueError:
                return
            if request_id != self._windows_request_id:
                return
            selected = self.get_selected_session()
            if selected is None or selected.name != event.worker.description:
                return
            error = event.worker.error
            if isinstance(error, TmuxError):
                self.set_status(str(error), error=True)
            elif error is not None:
                self.set_status(str(error), error=True)
            self._current_session = event.worker.description
            self._windows = []
            await self.update_windows_list()


def main() -> None:
    TuimuxApp().run()


if __name__ == "__main__":
    main()
