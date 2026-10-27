@echo off
rem Run the vedit engine from any working directory: vedit.cmd <command> [args]
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
uv run --quiet --project "%~dp0scripts" vedit %*
