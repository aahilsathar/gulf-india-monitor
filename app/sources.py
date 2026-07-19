"""Data connectors. Free sources only; every record carries its source and fetch time.
Failures return errors, never invented values."""
import asyncio
import statistics
import time
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
            except Exception:  # noqa: BLE001 - analytics are optional; the quote still stands
                pass
            quotes.append(
                {
                    "name": item.get("name", sym),
                    "symbol": sym,
                    "price": round(float(last), 2),
                    "chg_pct": chg,
                    "unit": item.get("unit", ""),
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
    # FX fallback: if USD/INR failed on Yahoo, try Frankfurter (ECB, daily, no key)
    missing_inr = not any(q["symbol"] == "INR=X" for q in data["quotes"])
    if missing_inr:
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
                        "name": "USD/INR",
                        "symbol": "INR=X",
                        "price": j["rates"]["INR"],
                        "chg_pct": None,
                        "unit": f"ECB ref {j['date']}",
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
                "mode": "ArtList",
                "format": "json",
                "maxrecords": 25,
                "sort": "DateDesc",
            },
        )
        r.raise_for_status()
        arts = r.json().get("articles", [])
    return [
        {
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "source": a.get("domain", "gdelt"),
            "published": a.get("seendate", ""),
        }
        for a in arts
    ]


def _fetch_rss_sync(urls: list[str]) -> list[dict]:
    out = []
    for u in urls:
        try:
            feed = feedparser.parse(u)
            for e in feed.entries[:8]:
                out.append(
                    {
                        "title": e.get("title", ""),
                        "url": e.get("link", ""),
                        "source": feed.feed.get("title", u)[:40],
                        "published": e.get("published", ""),
                    }
                )
        except Exception:  # noqa: BLE001 - a dead feed should not kill the panel
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
    items: list[dict] = []
    errors: list[str] = []
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
    return {"items": items[:30], "errors": errors, "as_of": _now()}
