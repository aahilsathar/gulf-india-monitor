# STRAIT

STRAIT — self-hosted market intelligence for commodities and the Gulf–India energy corridor. Fragmented free data in, readable decisions out. One page, always live:
price tape, corridor news ranked by transparent rules, a hand-maintained catalyst list, sparkline history, computed spreads, rule-based impact chips, and a Learn mode glossary.

Design principles: free sources only, every record carries its source and fetch time,
failures surface as errors — nothing is ever invented or faked.

## Data sources (all free)

| Feed | Source | Notes |
|---|---|---|
| Prices | Yahoo Finance via `yfinance` | ~15 min delayed futures; unofficial API, personal use |
| FX fallback | Frankfurter (ECB) | No key, daily reference rate |
| News | GDELT 2.0 DOC API | No key, global news index |
| News | RSS feeds in `config.yml` | Add/remove freely |
| Catalysts | `config.yml` | You maintain these by hand |

Dubai/Oman crude assessments and Platts cracks are licensed data. They are deliberately
absent rather than approximated.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. First data appears within ~30s; the app refreshes itself
(tape every 5 min, news every 15 min — change in `config.yml`). Press `R` or the
Refresh button to force a pull. Last data persists in `data/cache.json` across restarts.

## Deploy on a VPS (systemd)

```bash
# on the VPS
sudo apt update && sudo apt install -y python3-venv git
git clone <your-repo-url> /opt/gim && cd /opt/gim   # or scp the folder up
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Create `/etc/systemd/system/gim.service`:

```ini
[Unit]
Description=Gulf-India Monitor
After=network-online.target

[Service]
WorkingDirectory=/opt/gim
ExecStart=/opt/gim/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now gim
```

Optional nginx in front (recommended, add TLS with certbot):

```nginx
server {
  listen 80;
  server_name monitor.yourdomain.com;
  location / { proxy_pass http://127.0.0.1:8000; }
}
```

If you expose it publicly, put HTTP basic auth on it in nginx — this app has no login.

## Deploy with Docker instead

```bash
docker build -t gim . && docker run -d --restart=always -p 8000:8000 -v gim-data:/srv/data gim
```

## Customise

Everything user-facing lives in `config.yml`: tape symbols, the GDELT query, RSS feeds,
priority keywords, catalysts. Edit and restart (or `curl -X POST localhost:8000/api/refresh`).

## Known limitations

- Yahoo data is delayed and the API is unofficial; if a symbol breaks, it shows as a
  named failure on the tape, and FX falls back to ECB rates.
- GDELT indexing lags real time by ~15 minutes and skews toward English sources.
- Priority tags are keyword rules, not judgment — tune them in `config.yml`.
- Single-user by design; no auth, no write endpoints beyond refresh.

## Roadmap candidates

Spread panel (Brent–WTI, prompt spreads from the same free chain data), EIA weekly
inventories (free API key), FRED macro series (free key), and a thesis journal with
SQLite — in that order.


## v4 data layer (all free)

| Feed | Source | Key needed |
|---|---|---|
| 16-symbol grouped tape (energy, macro, freight proxies, India energy) | Yahoo Finance | No |
| Crack spreads: diesel, gasoline, 3-2-1, Brent–WTI | Calculated from tape | No |
| Speculative positioning (WTI, NatGas, Gold) | CFTC COT via public Socrata API | No |
| Corridor conditions (Hormuz, Fujairah, Mumbai, Delhi) | Open-Meteo | No |
| News lanes: maritime, freight, India energy, carbon, chokepoints | GDELT + RSS | No |
| US weekly crude inventories | EIA v2 API | Free key (`EIA_API_KEY`) |

To activate EIA: register at eia.gov/opendata, then on the server add
`Environment=EIA_API_KEY=yourkey` under `[Service]` in `/etc/systemd/system/gim.service`,
`systemctl daemon-reload && systemctl restart gim`.

## Put it on GitHub

From your laptop, inside the project folder:

```bash
git init && git add . && git commit -m "Gulf-India Monitor"
# create an empty repo named gulf-india-monitor at github.com/new, then:
git remote add origin https://github.com/YOUR_USERNAME/gulf-india-monitor.git
git branch -M main && git push -u origin main
```

Then future VPS updates become:

```bash
ssh root@YOUR_VPS "cd /opt/gim && git pull && systemctl restart gim"
```

(First time on the VPS: `cd /opt && rm -rf gim && git clone https://github.com/YOUR_USERNAME/gulf-india-monitor.git gim`
then reinstall the venv as in the deploy section. Your `data/cache.json` is gitignored, so live cache is untouched by pulls.)
