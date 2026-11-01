"""Native game intent independent of library tagging, without focus guessing."""

import configparser
import functools
import shlex
import time
from pathlib import Path
from .runtime import actual_home_dir


@functools.lru_cache(maxsize=2)
def desktop_game_rules(generation):
    rules = []
    for root in (
        Path("/usr/share/applications"),
        Path("/usr/local/share/applications"),
        actual_home_dir() / ".local/share/applications",
    ):
        for path in root.glob("*.desktop"):
            try:
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                parser.read(path)
                entry = parser["Desktop Entry"]
                if "Game" not in entry.get("Categories", "").split(";"):
                    continue
                args = shlex.split(entry.get("Exec", ""))
                exe = Path(args[0]).name if args else ""
                rules.append(
                    (exe.casefold(), entry.get("StartupWMClass", "").casefold())
                )
            except (OSError, configparser.Error, ValueError):
                continue
    return rules


def native_game(window, identity):
    executable = identity.get("executable", "").casefold()
    cls = window.get("class", "").casefold()
    return any(
        (exe and exe == executable) or (wm and wm == cls)
        for exe, wm in desktop_game_rules(int(time.monotonic() // 60))
    )
