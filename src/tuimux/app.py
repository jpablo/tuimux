from __future__ import annotations

from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

from tuimux.tmux import Session, TmuxClient, TmuxError, Window


class SessionItem(ListItem):
    def __init__(self, session: Session) -> None:
        text = f"{session.name}  ({session.windows})"
        if session.attached:
            text = f"{text}  *"
        super().__init__(Static(text))
        self.session = session


class WindowItem(ListItem):
    def __init__(self, window: Window) -> None:
        marker = "*" if window.active else " "
        text = f"{marker} {window.index}: {window.name}"
        super().__init__(Static(text))
        self.window = window


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


class TuimuxApp(App):
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
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("enter", "attach", "Attach/Switch"),
        ("n", "new_session", "New Session"),
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="content"):
            with Vertical(classes="panel", id="sessions-panel"):
                yield Static("Sessions", classes="panel-title")
                yield ListView(id="sessions")
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

    def load_windows(self, session_name: str, force: bool = False) -> None:
        if not force and session_name == self._current_session:
            return
        self._current_session = session_name
        try:
            self._windows = self._client.list_windows(session_name)
        except TmuxError as exc:
            self._windows = []
            self.set_status(str(exc), error=True)
            self.update_windows_list()
            return

        self.update_windows_list()

    def update_windows_list(self) -> None:
        windows_view = self.query_one("#windows", ListView)
        with self.batch_update():
            windows_view.clear()
            windows_view.extend(WindowItem(window) for window in self._windows)
            if self._windows:
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
            self.load_windows(event.item.session.name)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "sessions":
            self.action_attach()

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_attach(self) -> None:
        session = self.get_selected_session()
        if not session:
            self.set_status("Select a session to attach.", error=True)
            return
        try:
            if self._client.inside_tmux:
                self._client.switch_client(session.name)
            else:
                self._client.attach(session.name)
        except TmuxError as exc:
            self.set_status(str(exc), error=True)

    async def action_new_session(self) -> None:
        result = await self.push_screen_wait(
            PromptScreen("New session name", placeholder="work")
        )
        if not result:
            return
        try:
            self._client.new_session(result)
        except TmuxError as exc:
            self.set_status(str(exc), error=True)
            return
        self.refresh_data()

    async def action_new_window(self) -> None:
        session = self.get_selected_session()
        if not session:
            self.set_status("Select a session first.", error=True)
            return
        result = await self.push_screen_wait(
            PromptScreen("New window name", placeholder="shell", allow_empty=True)
        )
        if result is None:
            return
        try:
            name = result or None
            self._client.new_window(session.name, name)
        except TmuxError as exc:
            self.set_status(str(exc), error=True)
            return
        self.load_windows(session.name, force=True)

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
            self.load_windows(session.name, force=True)

    def on_key(self, event: Key) -> None:
        if event.key == "tab":
            sessions = self.query_one("#sessions", ListView)
            windows = self.query_one("#windows", ListView)
            if sessions.has_focus:
                windows.focus()
            else:
                sessions.focus()
            event.prevent_default()


def main() -> None:
    TuimuxApp().run()


if __name__ == "__main__":
    main()
