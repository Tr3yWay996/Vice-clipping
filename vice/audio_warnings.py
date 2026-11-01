"""Failure episodes, separate from continuously published capture diagnostics."""

import math
import uuid

DEFAULTS = {
    "critical": True,
    "disconnected": True,
    "silence": False,
    "silence_seconds": 180,
    "ignored_sources": [],
    "ignored_conditions": [],
}


def preferences(raw):
    raw = raw if isinstance(raw, dict) else {}
    result = {**DEFAULTS, **{k: raw[k] for k in DEFAULTS if k in raw}}
    for key in ("critical", "disconnected", "silence"):
        if type(result[key]) is not bool:
            result[key] = DEFAULTS[key]
    seconds = result["silence_seconds"]
    result["silence_seconds"] = (
        max(30, min(86400, seconds))
        if isinstance(seconds, (float, int))
        and not isinstance(seconds, bool)
        and math.isfinite(seconds)
        else 180
    )
    for key in ("ignored_sources", "ignored_conditions"):
        result[key] = (
            [s for s in result[key] if isinstance(s, str) and len(s) <= 256][:128]
            if isinstance(result[key], list)
            else []
        )
    return result


class AudioWarningPolicy:
    def __init__(self):
        self.session = uuid.uuid4().hex
        self.sequence = 0
        self.episodes = {}

    def update(self, tracks, raw, routing_error=None):
        prefs = preferences(raw)
        live = {}
        result = []
        for track in tracks:
            source, state = track["id"], track["state"]
            kind = (
                "critical"
                if state == "unsupported" or state == "disconnected" and routing_error
                else (
                    "disconnected"
                    if state
                    in {
                        "disconnected",
                        "missing_game",
                        "missing_stream",
                        "meter_unavailable",
                    }
                    else "silence" if state == "quiet" else None
                )
            )
            if (
                not track["enabled"]
                or not kind
                or not prefs[kind]
                or source in prefs["ignored_sources"]
                or source + "|" + state in prefs["ignored_conditions"]
            ):
                continue
            previous = self.episodes.get(source)
            if not previous:
                self.sequence += 1
                previous = {
                    "id": self.session + ":" + str(self.sequence),
                    "source": source,
                    "state": state,
                    "kind": kind,
                }
            previous = {**previous, "state": state, "kind": kind}
            live[source] = previous
            result.append({**previous, "name": track["name"]})
        self.episodes = live
        return result
