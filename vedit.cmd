@echo off
rem Run the vedit engine from any working directory: vedit.cmd <command> [args]
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
rem --frozen: use scripts\uv.lock as shipped; re-locking would change a tracked file and block `vedit update`
uv run --frozen --quiet --project "%~dp0scripts" vedit %*
