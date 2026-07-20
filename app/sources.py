"""Data connectors. Free sources only; every record carries its source and fetch time.
Failures return errors, never invented values."""
import asyncio
import os
import statistics
from datetime import datetime, timezone

import httpx
import feedparser


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------- price tape
def _fetch_tape_sync(cfg: dict) -> dict:
    import yfinance as yf

    quotes, errors = [], []
    for item in cfg.get("tape", []):
        sym = item["symbol"]
        try:
            tk = yf.Ticker(sym)
            fi = tk.fast_info
            last = fi["lastPrice"]
            prev = fi["previousClose"]
            chg = round((last / prev - 1) * 100, 2) if prev else None
            spark: list[float] = []
            stats: dict = {}
            try:
                closes = [float(x) for x in tk.history(period="1y", interval="1d")["Close"].dropna().tolist()]
                spark = [round(c, 2) for c in closes[-22:]]
                rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
                if len(rets) > 30:
                    sd = statistics.pstdev(rets)
                    if sd and chg is not None:
                        stats["sigma"] = round((chg / 100) / sd, 1)
                    stats["vol20"] = round(statistics.pstdev(rets[-20:]) * (252 ** 0.5) * 100, 1)
                    stats["pct1y"] = round(100 * sum(1 for c in closes if c <= float(last)) / len(closes))
            except Exception:  # noqa: BLE001 - analytics optional; the quote still stands
                pass
            quotes.append(
                {
                    "name": item.get("name", sym),
                    "symbol": sym,
                    "price": round(float(last), 2),
                    "chg_pct": chg,
                    "unit": item.get("unit", ""),
                    "group": item.get("group", "OTHER"),
                    "spark": spark,
                    "stats": stats,
                    "source": "Yahoo Finance (delayed)",
                }
            )
        except Exception as exc:  # noqa: BLE001 - surface every failure honestly
            errors.append({"symbol": sym, "error": str(exc)[:120]})
    return {"quotes": quotes, "errors": errors, "as_of": _now()}


async def fetch_tape(cfg: dict) -> dict:
    data = await asyncio.to_thread(_fetch_tape_sync, cfg)
    if not any(q["symbol"] == "INR=X" for q in data["quotes"]):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.frankfurter.dev/v1/latest",
                    params={"base": "USD", "symbols": "INR"},
                )
                r.raise_for_status()
                j = r.json()
                data["quotes"].append(
                    {
                        "name": "USD/INR", "symbol": "INR=X", "price": j["rates"]["INR"],
                        "chg_pct": None, "unit": f"ECB ref {j['date']}",
                        "group": "MACRO & FX", "spark": [], "stats": {},
                        "source": "Frankfurter/ECB",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            data["errors"].append({"symbol": "INR=X(fallback)", "error": str(exc)[:120]})
    return data


# ---------------------------------------------------------------- news feeds
def _priority(title: str, rules: dict) -> str:
    t = title.lower()
    if any(k in t for k in rules.get("critical", [])):
        return "critical"
    if any(k in t for k in rules.get("important", [])):
        return "important"
    return "monitor"


async def _fetch_gdelt(query: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": f"{query} sourcelang:english",
                "mode": "ArtList", "format": "json",
                "maxrecords": 25, "sort": "DateDesc",
            },
        )
        r.raise_for_status()
        arts = r.json().get("articles", [])
    return [
        {"title": a.get("title", ""), "url": a.get("url", ""),
         "source": a.get("domain", "gdelt"), "published": a.get("seendate", ""),
         "lane": "CORRIDOR"}
        for a in arts
    ]


def _fetch_rss_sync(feeds: list) -> list[dict]:
    out = []
    for f in feeds:
        url = f["url"] if isinstance(f, dict) else f
        lane = f.get("lane", "NEWS") if isinstance(f, dict) else "NEWS"
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:8]:
                out.append(
                    {"title": e.get("title", ""), "url": e.get("link", ""),
                     "source": feed.feed.get("title", url)[:40],
                     "published": e.get("published", ""), "lane": lane}
                )
        except Exception:  # noqa: BLE001 - one dead feed must not kill the panel
            continue
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = it["title"].lower().strip()[:80]
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


async def fetch_news(cfg: dict) -> dict:
    rules = cfg.get("priority_rules", {})
    items, errors = [], []
    try:
        items += await _fetch_gdelt(cfg.get("gdelt_query", "oil India"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"GDELT: {str(exc)[:100]}")
    try:
        items += await asyncio.to_thread(_fetch_rss_sync, cfg.get("rss_feeds", []))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"RSS: {str(exc)[:100]}")

    items = _dedupe(items)
    imap = cfg.get("impact_map", {})
    for it in items:
        it["priority"] = _priority(it["title"], rules)
        if it["priority"] in ("critical", "important"):
            t = it["title"].lower()
            impacts: list[str] = []
            for kw, effects in imap.items():
                if kw in t:
                    impacts += [e for e in effects if e not in impacts]
            it["impacts"] = impacts[:4]
    order = {"critical": 0, "important": 1, "monitor": 2}
    items.sort(key=lambda x: order[x["priority"]])
    return {"items": items[:36], "errors": errors, "as_of": _now()}


# --------------------------------------------------- CFTC COT positioning (free)
async def fetch_cot(cfg: dict) -> dict:
    rows, errors = [], []
    async with httpx.AsyncClient(timeout=25) as client:
        for m in cfg.get("cot_markets", []):
            try:
                r = await client.get(
                    "https://publicreporting.cftc.gov/resource/6dca-aqww.json",
                    params={
                        "$where": f"upper(market_and_exchange_names) like '%{m['like'].upper()}%'",
                        "$order": "report_date_as_yyyy_mm_dd DESC",
                        "$select": "report_date_as_yyyy_mm_dd,noncomm_positions_long_all,noncomm_positions_short_all",
                        "$limit": "2",
                    },
                )
                r.raise_for_status()
                recs = r.json()
                if not recs:
                    raise ValueError("no records")
                def net(rec):
                    return int(float(rec["noncomm_positions_long_all"])) - int(float(rec["noncomm_positions_short_all"]))
                latest = net(recs[0])
                delta = latest - net(recs[1]) if len(recs) > 1 else None
                rows.append(
                    {"market": m["key"], "net": latest, "delta_wk": delta,
                     "date": recs[0]["report_date_as_yyyy_mm_dd"][:10],
                     "source": "CFTC legacy COT"}
                )
            except Exception as exc:  # noqa: BLE001
                errors.append({"market": m["key"], "error": str(exc)[:100]})
    return {"rows": rows, "errors": errors, "as_of": _now()}


# --------------------------------------------------- corridor conditions (free)
async def fetch_wx(cfg: dict) -> dict:
    rows, errors = [], []
    async with httpx.AsyncClient(timeout=15) as client:
        for w in cfg.get("weather", []):
            try:
                r = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={"latitude": w["lat"], "longitude": w["lon"],
                            "current": "temperature_2m,wind_speed_10m"},
                )
                r.raise_for_status()
                cur = r.json().get("current", {})
                rows.append(
                    {"name": w["name"], "tag": w.get("tag", ""),
                     "temp_c": cur.get("temperature_2m"),
                     "wind_kmh": cur.get("wind_speed_10m"),
                     "source": "Open-Meteo"}
                )
            except Exception as exc:  # noqa: BLE001
                errors.append({"name": w["name"], "error": str(exc)[:100]})
    return {"rows": rows, "errors": errors, "as_of": _now()}


# --------------------------------------------------- EIA inventories (free key)
async def fetch_eia(cfg: dict) -> dict:
    key = os.environ.get("EIA_API_KEY", "").strip()
    if not key:
        return {"status": "key_needed", "as_of": _now(),
                "note": "Free key at eia.gov/opendata — set EIA_API_KEY to activate."}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.get(
                "https://api.eia.gov/v2/petroleum/stoc/wstk/data/",
                params={
                    "api_key": key, "frequency": "weekly",
                    "data[0]": "value", "facets[series][]": "WCESTUS1",
                    "sort[0][column]": "period", "sort[0][direction]": "desc",
                    "length": "2",
                },
            )
            r.raise_for_status()
            recs = r.json()["response"]["data"]
        latest, prev = recs[0], recs[1] if len(recs) > 1 else None
        return {
            "status": "ok",
            "period": latest["period"],
            "us_crude_stocks_kbbl": latest["value"],
            "weekly_change_kbbl": (latest["value"] - prev["value"]) if prev else None,
            "source": "EIA weekly petroleum status",
            "as_of": _now(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:120], "as_of": _now()}
