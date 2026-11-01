"""Local-only smart audio diagnostics and short, disposable capture samples."""

import json
from aiohttp import web


class AudioAPI:
    def _audio_service(self):
        router = getattr(self, "audio_router", None)
        if router is None:
            raise web.HTTPServiceUnavailable(
                text="Audio routing service is unavailable for this backend."
            )
        return router

    async def _api_audio_state(self, req):
        return web.json_response(self._audio_service().snapshot())

    async def _api_audio_monitor(self, req):
        body = await req.json()
        token = body.get("token", "")
        if not isinstance(token, str) or not token.isalnum() or len(token) > 64:
            raise web.HTTPBadRequest()
        router = self._audio_service()
        if len(router.leases) >= 8 and token not in router.leases:
            raise web.HTTPTooManyRequests()
        router.monitor_view(token, body.get("enabled") is True)
        return web.json_response({"ok": True})

    async def _api_audio_test(self, req):
        router = self._audio_service()
        if router.test_lock.locked():
            raise web.HTTPConflict(text="An audio capture test is already running.")
        async with router.test_lock:
            return web.json_response(await router.capture_test())

    async def _api_audio_sample(self, req):
        router = self._audio_service()
        item = router.tests.get(req.match_info["test"])
        if not item:
            raise web.HTTPNotFound()
        index = req.match_info["index"]
        if not index.isdecimal() or len(index) > 2:
            raise web.HTTPNotFound()
        path = item[0] / (index + ".wav")
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(
            path, headers={"Content-Type": "audio/wav", "Cache-Control": "no-store"}
        )

    async def _api_audio_test_delete(self, req):
        router = self._audio_service()
        router.delete_test(req.match_info["test"])
        return web.json_response({"ok": True})

    async def _api_audio_match(self, req):
        import asyncio
        from .audio_matching import validate_rules

        body = await req.json()
        try:
            rules = validate_rules(body.get("rules"))
        except (ValueError, AttributeError) as exc:
            raise web.HTTPBadRequest(text=str(exc))
        router = self._audio_service()
        try:
            results = []
            for rule in rules:
                matches = await asyncio.to_thread(
                    router.matcher.evaluate, [rule], router.streams
                )
                results.append([stream.node_id for stream in matches])
            return web.json_response({"matches": results})
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))

    async def _api_audio_icon(self, req):
        from pathlib import Path
        import re
        from .audio_graph import props

        router = self._audio_service()
        try:
            node = router.graph.get(int(req.match_info["node"]))
        except ValueError:
            raise web.HTTPNotFound()
        if not node:
            raise web.HTTPNotFound()
        names = [
            props(node).get("application.icon-name", ""),
            props(node).get("application.process.binary", ""),
        ]
        from .runtime import actual_home_dir

        roots = [
            actual_home_dir() / ".local/share/icons",
            Path("/usr/share/icons/hicolor"),
            Path("/usr/share/pixmaps"),
        ]
        for name in names:
            if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}", name):
                continue
            for root in roots:
                for folder in ("48x48/apps", "32x32/apps", "scalable/apps", ""):
                    for suffix in (".png", ".svg", ".xpm"):
                        path = root / folder / (name + suffix)
                        if path.is_file():
                            return web.FileResponse(
                                path, headers={"Cache-Control": "private, max-age=300"}
                            )
        raise web.HTTPNotFound()
