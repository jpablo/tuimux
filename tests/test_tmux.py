from __future__ import annotations

import pytest

from tuimux.tmux import TmuxClient, TmuxError


def test_list_sessions_parses_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TmuxClient()

    def fake_run(_args: list[str]) -> str:
        return "\n".join(
            [
                "vite\t1\tWed Dec 31 15:35:55 2025\t1",
                "sbt\t2\tWed Dec 31 15:35:33 2025\t0",
            ]
        )

    monkeypatch.setattr(client, "_run", fake_run)
    sessions = client.list_sessions()

    assert [session.name for session in sessions] == ["sbt", "vite"]
    assert sessions[0].windows == 2
    assert sessions[1].attached is True


def test_list_sessions_handles_no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TmuxClient()

    def fake_run(_args: list[str]) -> str:
        raise TmuxError("no server running on /tmp/tmux-1000/default")

    monkeypatch.setattr(client, "_run", fake_run)

    assert client.list_sessions() == []


def test_list_windows_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TmuxClient()

    def fake_run(_args: list[str]) -> str:
        return "\n".join(
            [
                "@1\tshell\t0\t1",
                "@2\tlogs\t1\t0",
            ]
        )

    monkeypatch.setattr(client, "_run", fake_run)
    windows = client.list_windows("dev")

    assert [window.name for window in windows] == ["shell", "logs"]
    assert windows[0].active is True
    assert windows[1].index == 1


@pytest.mark.parametrize(
    "method,args,expected",
    [
        ("rename_session", ("old", "new"), ["rename-session", "-t", "old", "new"]),
        ("rename_window", ("@3", "work"), ["rename-window", "-t", "@3", "work"]),
        ("select_window", ("@3",), ["select-window", "-t", "@3"]),
        ("enter_copy_mode", (), ["copy-mode"]),
        ("show_buffer", (), ["show-buffer"]),
        (
            "capture_window",
            ("@5", 50),
            ["capture-pane", "-t", "@5", "-p", "-S", "-50"],
        ),
    ],
)
def test_tmux_commands_call_run(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    args: tuple[object, ...],
    expected: list[str],
) -> None:
    client = TmuxClient()
    calls: list[list[str]] = []

    def fake_run(arguments: list[str]) -> str:
        calls.append(arguments)
        return ""

    monkeypatch.setattr(client, "_run", fake_run)
    getattr(client, method)(*args)

    assert calls == [expected]
