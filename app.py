"""
Weave Box web layer.

A tiny FastAPI app that serves the control panel and exposes four endpoints:
    GET  /api/status   current state + live telemetry
    POST /api/start    turn the mitigator on
    POST /api/stop     turn it off
    GET  /api/logs     recent mitigator log lines

Run it with:  python3 app.py   (systemd does this for you)
"""
import os

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse

import config
from controller import controller

app = FastAPI(title="Weave Box", docs_url=None, redoc_url=None)

_INDEX = os.path.join(config.BASE_DIR, "static", "index.html")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_INDEX)


@app.get("/api/status")
def api_status() -> dict:
    return controller.status()


@app.post("/api/start")
def api_start() -> dict:
    return controller.start()


@app.post("/api/stop")
def api_stop() -> dict:
    return controller.stop()


@app.get("/api/logs")
def api_logs(n: int = Query(200, ge=1, le=config.LOG_BUFFER)) -> dict:
    return {"lines": controller.logs(n)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
