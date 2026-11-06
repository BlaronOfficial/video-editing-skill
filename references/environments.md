# Environments

`vedit env` says where the engine runs, what works there and what to set up next.

| Surface | How Claude reaches the engine | What works |
|---|---|---|
| Claude Code on the owner's Windows PC | the skill folder directly (`vedit ...`) | everything |
| Claude desktop app, local MCP (`claude-app-mcp`) | vedit registered as a local MCP server: tools `vedit`, `read_doc`, `view_image`, `env`, `studio_*`, ... | everything, natively on Windows (CapCut, Resolve, screen control included) |
| Claude app, remote device tools (`claude-app-vm`) | `device_bash` in a Linux VM with the skill folder mounted under `~/mnt/` | everything except CapCut build/learn, screen control, Resolve live import, installing fonts into Windows |
| Claude app with no PC (lite) | none (phone, web) | writing, planning, research, caption text, Canva/Drive connectors, Studio review; a hand-off note for the PC |
| macOS | the skill folder (`./vedit`) | expected to work; untested |

## Claude desktop app: local MCP

```
vedit env mcp                 # status and the entry it would write
vedit env mcp --install       # ask the owner first: edits the app's config (backup kept), then restart the app
```
The Microsoft Store build keeps its config in `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json`
(not `%APPDATA%\Claude`); `vedit env mcp` finds it. The entry runs `uv run --frozen --project <skill>\scripts vedit mcp`
(no batch file, quiet stdio). Only `mcpServers.vedit` is added or updated; everything else is kept. The app must
be closed while this runs: it keeps its config in memory and writes it back when a setting changes, which
drops an entry added while it was open (`--install` refuses while it runs). So the owner quits the app fully
(tray icon too), runs `<skill>\vedit.cmd env mcp --install` in a terminal, and starts the app again. Never
close the app for them: this Claude Code session may be running inside it.

## Claude app launcher skill

The engine's own `SKILL.md` is the source of truth; the Claude app needs a small launcher skill that finds the
engine and reads it. `vedit env launcher` writes `app/claude-app/video-editing.zip` with this PC's skill path
filled in; the owner uploads it in claude.ai (Settings > Capabilities > Skills), replacing older copies. It
tries, in order: the local MCP tools, the remote device tools, then lite mode. `vedit env` lists the synced
copies it can see and whether they are current.

## Shared skill folder (Windows + the Claude app's VM)

A virtual environment only runs on the system that made it. On Linux and macOS the `vedit` launcher keeps
the engine's venv in `~/.cache/vedit/venv` when the folder is shared with Windows (mounted under `~/mnt/`,
or a Windows venv is present), and tool venvs live in `.cache/tools-<os>/`, so neither side rebuilds the
other's. Fonts, models and `personal/` are shared.
