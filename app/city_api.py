"""Same-origin, compressed scene endpoints; simulation states stay in Python."""

import gzip
import json
from pathlib import Path
from flask import Response, send_file
from core.storage import json_safe
from visualisation.urban_scene import scene_config, scene_state, traffic_model


def register_city(app, jobs):
    cache = {}

    def compressed(payload):
        return gzip.compress(
            json.dumps(json_safe(payload), separators=(",", ":")).encode(),
            compresslevel=5,
        )

    def response(blob):
        return Response(
            blob,
            mimetype="application/json",
            headers={
                "Content-Encoding": "gzip",
                "Cache-Control": "private, no-cache",
            },
        )

    @app.server.get("/district")
    def district_page():
        return send_file(Path(__file__).parent / "static" / "city" / "index.html")

    @app.server.get("/api/city/<identifier>")
    def city_config(identifier):
        try:
            if identifier not in cache:
                cache[identifier] = compressed(scene_config(jobs.result(identifier)))
                while len(cache) > 4:
                    cache.pop(next(iter(cache)))
            return response(cache[identifier])
        except (ValueError, FileNotFoundError) as exc:
            return {"error": str(exc)}, 404

    @app.server.get("/api/city/<identifier>/state/<int:step>")
    def city_state(identifier, step):
        try:
            return Response(
                json.dumps(json_safe(scene_state(jobs.result(identifier), step))),
                mimetype="application/json",
                headers={"Cache-Control": "private,max-age=3600"},
            )
        except (ValueError, FileNotFoundError) as exc:
            return {"error": str(exc)}, 404

    traffic_cache = []

    @app.server.get("/api/city-traffic")
    def city_traffic():
        if not traffic_cache:
            traffic_cache.append(compressed(traffic_model()))
        return response(traffic_cache[0])
