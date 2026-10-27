"""CapCut resource catalogue (effects, filters, transitions, animations, fonts) from pyCapCut metadata.

Names are CapCut's own (many are Chinese). `lookup()` accepts the CapCut name, an English alias from
ALIASES, or a pyCapCut enum member name, and refuses Pro (VIP) items when Pro is not allowed.
"""

from __future__ import annotations

from typing import Any

import pycapcut as cc

CATEGORIES: dict[str, Any] = {
    "transition": cc.TransitionType,
    "filter": cc.FilterType,
    "scene_effect": cc.VideoSceneEffectType,
    "character_effect": cc.VideoCharacterEffectType,
    "video_intro": cc.IntroType,
    "video_outro": cc.OutroType,
    "video_combo": cc.GroupAnimationType,
    "text_intro": cc.TextIntro,
    "text_outro": cc.TextOutro,
    "text_loop": cc.TextLoopAnim,
    "font": cc.FontType,
    "mask": cc.MaskType,
    "audio_effect": cc.AudioSceneEffectType,
    "tone_effect": cc.ToneEffectType,
}

# English intent -> candidate CapCut names, first match wins. Claude can always pass exact names too.
ALIASES: dict[str, dict[str, list[str]]] = {
    "transition": {
        "dissolve": ["叠化", "Dissolve"], "fade": ["叠化", "闪黑"], "fade_black": ["闪黑"], "flash": ["闪白", "White_Flash"],
        "white_flash": ["White_Flash", "闪白"], "zoom_in": ["拉近", "推近"], "zoom_out": ["拉远"], "push": ["推近"],
        "slide_left": ["向左"], "slide_right": ["向右"], "slide_up": ["向上", "上移"], "slide_down": ["向下", "下移"],
        "blur": ["模糊", "亮点模糊"], "spin": ["旋转", "中轴旋转"], "glitch": ["故障", "信号故障"], "wipe": ["擦除", "向右擦除"],
        "flip": ["Cutout_Flip", "翻页"], "fold": ["Fold_Over"],
    },
    "text_intro": {
        "pop": ["弹入", "放大", "Bumper_Car"], "fade": ["渐显"], "typewriter": ["打字机_I", "打字机"], "slide_up": ["向上滑动", "上滑"],
        "zoom": ["放大", "缩小"], "bounce": ["弹入", "弹簧"], "wipe": ["Wiping_In", "向右擦除"], "click": ["Click"],
    },
    "text_outro": {"fade": ["渐隐"], "pop": ["弹出", "缩小"], "slide_down": ["向下滑动", "下滑"]},
    "video_intro": {"fade": ["渐显"], "zoom": ["放大", "缩小"], "slide_up": ["向上滑动"], "pop": ["弹入"]},
    "video_outro": {"fade": ["渐隐"], "zoom": ["放大", "缩小"]},
    "scene_effect": {
        "shake": ["Shaky_Dolly", "抖动"], "flash": ["闪白", "Blinking"], "glitch": ["X_Signal", "故障"], "vhs": ["Betamax", "JVC"],
        "film_grain": ["胶片颗粒", "_70s"], "blur": ["模糊"], "zoom_pulse": ["Beat_Shots", "镜头变焦"], "vignette": ["暗角"],
        "rgb_split": ["RGB描边", "色差故障"],
    },
    "filter": {
        "warm_cinematic": ["Cinematic_Dusk", "Glowing_Tan"], "moody": ["Gritty_Noir", "HD_Dark", "Dark_Humble"],
        "clean": ["Enhance", "Crisp_Air"], "bw": ["BW_2", "Anime_B_W"], "vintage": ["VHS_I", "_1980"], "teal_orange": ["Blue_Hour", "Cyan_Nature"],
        "soft": ["Soft_Grain", "Dreamy_Halo"], "cyberpunk": ["Cyberpunk"],
    },
}


def _norm(name: str) -> str:
    return name.lower().replace(" ", "").replace("_", "")


def lookup(category: str, name: str, *, pro_allowed: bool = True):
    """Return the pyCapCut enum member for `name` (CapCut name, alias or enum name), or raise ValueError."""
    enum = CATEGORIES[category]
    candidates = ALIASES.get(category, {}).get(name.lower(), []) + [name]
    tried = []
    for cand in candidates:
        target = _norm(cand)
        for member in enum:
            meta = member.value
            if _norm(member.name) == target or _norm(getattr(meta, "name", "")) == target:
                if getattr(meta, "is_vip", False) and not pro_allowed:
                    tried.append(f"{cand} (Pro)")
                    break
                return member
        else:
            tried.append(cand)
    raise ValueError(f"No {'free ' if not pro_allowed else ''}CapCut {category} matching '{name}' (tried: {', '.join(tried)})")


def catalogue(category: str, *, pro_allowed: bool = True, query: str | None = None, limit: int = 200) -> list[dict]:
    enum = CATEGORIES[category]
    out = []
    for member in enum:
        meta = member.value
        vip = bool(getattr(meta, "is_vip", False))
        if vip and not pro_allowed:
            continue
        label = getattr(meta, "name", member.name)
        if query and _norm(query) not in _norm(label) and _norm(query) not in _norm(member.name):
            continue
        item = {"name": label, "id": member.name, "pro": vip}
        duration = getattr(meta, "default_duration", None)
        if duration:
            item["default_duration_s"] = round(duration / 1e6, 2)
        params = getattr(meta, "params", None)
        if params:
            item["params"] = [p.name for p in params]
        out.append(item)
        if len(out) >= limit:
            break
    return out


def aliases(category: str | None = None) -> dict:
    return ALIASES if category is None else ALIASES.get(category, {})
