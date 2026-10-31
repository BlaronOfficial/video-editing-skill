# Developer smoke tests

These need synthetic media in `tests/footage/` (git-ignored). Generate it with ffmpeg:

    ffmpeg -f lavfi -i testsrc2=size=1920x1080:rate=30:duration=12 -f lavfi -i sine=frequency=440:duration=12 -shortest footage/synthetic_a.mp4
    ffmpeg -f lavfi -i smptehdbars=size=1920x1080:rate=30:duration=8 -f lavfi -i sine=frequency=660:duration=8 -shortest footage/synthetic_b.mp4
    ffmpeg -f lavfi -i sine=frequency=220:duration=30 -af volume=0.3 footage/music_test.mp3

Run from this folder:

    uv run --project ../scripts python smoke_capcut.py            # build only (prints tracks + warnings)
    uv run --project ../scripts python smoke_capcut.py --write    # write vedit_test_01 into CapCut (CapCut closed)
    uv run --project ../scripts python smoke_render.py            # 540p preview -> out/preview.mp4

v2 phase checks (from the skill root, on copies of the E2E project in `tests/footage/e2e`):

    scripts/.venv/Scripts/python.exe tests/test_v2.py
    scripts/.venv/Scripts/python.exe tests/test_phase2.py [--render] [--net]
    scripts/.venv/Scripts/python.exe tests/test_phase3.py [--full] [--apps]   # hand-offs; --apps uses portable
                                                                              # Shotcut/LosslessCut in .cache/tools
