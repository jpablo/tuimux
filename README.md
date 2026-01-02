# tuimux

A modern TUI for tmux built with Textual.

## Quick start

```bash
uv venv .venv
source .venv/bin/activate
uv sync

uv pip install -e .

tuimux
```

## Dependency notes

- Use `uv add <pkg>` to add dependencies (updates `pyproject.toml` + lockfile).
- Use `uv sync` to install from the lockfile.
- Use `uv pip install -e .` for editable installs during development.

## Keys

- `r` refresh
- `Enter` attach/switch to the selected session
- `n` new session
- `e` rename selected session
- `h` help
- `w` rename selected window
- `c` new window in the selected session
- `x` kill selected session
- `d` kill selected window
- `v` enter copy mode (inside tmux)
- `y` copy tmux buffer to clipboard
- `p` preview selected session output
- `q` quit
