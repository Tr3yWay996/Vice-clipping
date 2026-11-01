"""Bounded optional regex execution; matching never stalls the recording loop."""

import multiprocessing as mp
import re
import threading


def validate_rules(rules):
    from .audio_streams import MATCH_FIELDS

    if not isinstance(rules, list) or len(rules) > 16:
        raise ValueError("audio.rules")
    for rule in rules:
        if (
            not isinstance(rule, dict)
            or rule.get("field", "name") not in MATCH_FIELDS
            or rule.get("mode", "exact") not in {"exact", "contains", "regex"}
        ):
            raise ValueError("audio.rules")
        value = rule.get("value")
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ValueError("audio.rules")
        if rule.get("mode") == "regex":
            try:
                re.compile(value, re.I)
            except re.error:
                raise ValueError("audio.regex")
    return rules


def _worker(pipe):
    pipe.send(True)
    try:
        while True:
            rules, streams = pipe.recv()
            result = []
            for stream in streams:
                for rule in rules:
                    text = getattr(stream, rule.get("field", "name"))
                    value = rule["value"]
                    mode = rule.get("mode", "exact")
                    matches = (
                        (re.search(value, text, re.I) is not None)
                        if mode == "regex"
                        else (
                            value.casefold() in text.casefold()
                            if mode == "contains"
                            else value.casefold() == text.casefold()
                        )
                    )
                    if matches:
                        result.append(stream.node_id)
                        break
            pipe.send(result)
    except (EOFError, BrokenPipeError):
        pass


class RuleMatcher:
    def __init__(self):
        self.process = None
        self.pipe = None
        self.lock = threading.Lock()

    def close(self):
        if self.pipe:
            self.pipe.close()
            self.pipe = None
        if self.process:
            self.process.terminate()
            self.process.join(timeout=1)
            self.process = None

    def evaluate(self, rules, streams):
        validate_rules(rules)
        if not any(r.get("mode") == "regex" for r in rules):
            from .audio_streams import matching_nodes

            return matching_nodes(streams, rules)
        with self.lock:
            if not self.process or not self.process.is_alive():
                self.close()
                context = mp.get_context("spawn")
                parent, child = context.Pipe()
                self.pipe = parent
                self.process = context.Process(
                    target=_worker, args=(child,), daemon=True
                )
                self.process.start()
                child.close()
                if not parent.poll(3):
                    self.close()
                    raise ValueError("audio.matcher_unavailable")
                parent.recv()
            try:
                self.pipe.send((rules, streams))
                if not self.pipe.poll(0.1):
                    raise ValueError("audio.regex_timeout")
                ids = set(self.pipe.recv())
                return [stream for stream in streams if stream.node_id in ids]
            except (OSError, EOFError, ValueError):
                self.close()
                raise ValueError("audio.regex_timeout")
