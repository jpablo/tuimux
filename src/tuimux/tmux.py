from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
from typing import Iterable


class TmuxError(RuntimeError):
    pass


@dataclass(frozen=True)
class Session:
    name: str
    windows: int
    created: str
    attached: bool


@dataclass(frozen=True)
class Window:
    id: str
    name: str
    index: int
    active: bool


class TmuxClient:
    def __init__(self) -> None:
        self._inside_tmux = bool(self._env_tmux())

    @staticmethod
    def _env_tmux() -> str | None:
        return os.environ.get("TMUX")

    @property
    def inside_tmux(self) -> bool:
        return self._inside_tmux

    def _run(self, args: Iterable[str]) -> str:
        try:
            completed = subprocess.run(
                ["tmux", *args],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise TmuxError("tmux is not installed or not on PATH") from exc

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout).strip()
            raise TmuxError(message or f"tmux exited with {completed.returncode}")

        return completed.stdout.strip()

    @staticmethod
    def _is_no_server(message: str) -> bool:
        lowered = message.lower()
        return "no server running" in lowered or "failed to connect" in lowered

    def list_sessions(self) -> list[Session]:
        try:
            output = self._run(
                [
                    "list-sessions",
                    "-F",
                    "#{session_name}\t#{session_windows}\t#{session_created_string}\t#{session_attached}",
                ]
            )
        except TmuxError as exc:
            if self._is_no_server(str(exc)):
                return []
            raise

        sessions: list[Session] = []
        if not output:
            return sessions

        for line in output.splitlines():
            name, windows, created, attached = line.split("\t")
            sessions.append(
                Session(
                    name=name,
                    windows=int(windows),
                    created=created,
                    attached=attached == "1",
                )
            )
        sessions.sort(key=lambda session: session.name)
        return sessions

    def list_windows(self, session_name: str) -> list[Window]:
        try:
            output = self._run(
                [
                    "list-windows",
                    "-t",
                    session_name,
                    "-F",
                    "#{window_id}\t#{window_name}\t#{window_index}\t#{window_active}",
                ]
            )
        except TmuxError as exc:
            if self._is_no_server(str(exc)):
                return []
            raise

        windows: list[Window] = []
        if not output:
            return windows

        for line in output.splitlines():
            window_id, name, index, active = line.split("\t")
            windows.append(
                Window(
                    id=window_id,
                    name=name,
                    index=int(index),
                    active=active == "1",
                )
            )
        return windows

    def new_session(self, name: str) -> None:
        self._run(["new-session", "-d", "-s", name])

    def new_window(self, session_name: str, name: str | None = None) -> None:
        args = ["new-window", "-t", session_name]
        if name:
            args.extend(["-n", name])
        self._run(args)

    def kill_session(self, name: str) -> None:
        self._run(["kill-session", "-t", name])

    def kill_window(self, window_id: str) -> None:
        self._run(["kill-window", "-t", window_id])

    def rename_session(self, name: str, new_name: str) -> None:
        self._run(["rename-session", "-t", name, new_name])

    def rename_window(self, window_id: str, new_name: str) -> None:
        self._run(["rename-window", "-t", window_id, new_name])

    def select_window(self, window_id: str) -> None:
        self._run(["select-window", "-t", window_id])

    def enter_copy_mode(self) -> None:
        self._run(["copy-mode"])

    def show_buffer(self) -> str:
        return self._run(["show-buffer"])

    def capture_window(self, window_id: str, lines: int = 200) -> str:
        return self._run(
            [
                "capture-pane",
                "-t",
                window_id,
                "-p",
                "-S",
                f"-{lines}",
            ]
        )

    def attach(self, session_name: str) -> None:
        self._run(["attach", "-t", session_name])

    def switch_client(self, session_name: str) -> None:
        self._run(["switch-client", "-t", session_name])
