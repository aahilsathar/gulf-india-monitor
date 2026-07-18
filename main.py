"""Gulf-India Monitor — FastAPI backend.

Runs its own refresh loop, caches to disk, serves the dashboard.
Start with:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import sources

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / "cache.json"

cfg = yaml.safe_load((ROOT / "config.yml").read_text())
cache: dict = {"tape": None, "news": None}
fetched_at: dict = {"tape": 0.0, "news": 0.0}


def _load_cache() -> None:
    if CACHE_FILE.exists():
        try:
            saved = json.loads(CACHE_FILE.read_text())
            cache.update(saved.get("cache", {}))
            fetched_at.update(saved.get("fetched_at", {}))
        except Exception:  # noqa: BLE001 - corrupt cache is not fatal
            pass


def _save_cache() -> None:
    CACHE_FILE.write_text(json.dumps({"cache": cache, "fetched_at": fetched_at}))


async def _refresh(kind: str) -> None:
    fn = sources.fetch_tape if kind == "tape" else sources.fetch_news
    try:
        cache[kind] = await fn(cfg)
        fetched_at[kind] = time.time()
        _save_cache()
    except Exception as exc:  # noqa: BLE001 - keep last good data, mark nothing fresh
        err = {"errors": [str(exc)[:150]], "as_of": None}
        if cache[kind] is None:
            cache[kind] = err


async def _refresher() -> None:
    while True:
        now = time.time()
        jobs = []
        if now - fetched_at["tape"] > cfg["refresh_minutes"]["tape"] * 60:
            jobs.append(_refresh("tape"))
        if now - fetched_at["news"] > cfg["refresh_minutes"]["news"] * 60:
            jobs.append(_refresh("news"))
        if jobs:
            await asyncio.gather(*jobs)
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_cache()
    task = asyncio.create_task(_refresher())
    yield
    task.cancel()


app = FastAPI(title="Gulf-India Monitor", lifespan=lifespan)


def _age(kind: str) -> int | None:
    return int(time.time() - fetched_at[kind]) if fetched_at[kind] else None


@app.get("/api/all")
async def api_all():
    return {
        "tape": cache["tape"],
        "news": cache["news"],
        "catalysts": cfg.get("catalysts", []),
        "ages_sec": {"tape": _age("tape"), "news": _age("news")},
    }


@app.post("/api/refresh")
async def api_refresh():
    await asyncio.gather(_refresh("tape"), _refresh("news"))
    return {"ok": True, "ages_sec": {"tape": _age("tape"), "news": _age("news")}}


@app.get("/api/health")
async def api_health():
    def status(kind: str) -> str:
        if cache[kind] is None:
            return "cold"
        key = "quotes" if kind == "tape" else "items"
        if not (cache[kind] or {}).get(key):
            return "cold"
        limit = cfg["refresh_minutes"][kind] * 60 * 3
        age = _age(kind)
        return "ok" if age is not None and age < limit else "stale"

    return {"tape": status("tape"), "news": status("news")}


@app.exception_handler(Exception)
async def unhandled(_, exc):
    return JSONResponse(status_code=500, content={"error": str(exc)[:200]})


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
