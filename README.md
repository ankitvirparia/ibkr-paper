# ibkr-paper — paper-trading signal service for IBKR (50% options / 50% US stocks)

## What it is
- Talks to the local `ibkr-gateway` (IBKR Client Portal Gateway) for market data.
- **Paper only**: signals are simulated in a local SQLite ledger. No order code exists.
- Two sleeves: `options` (income strategies) and `equity` (US stock strategies).

## Deploy a new strategy
1. Copy `src/strategies/TEMPLATE.py` → `src/strategies/my_strat.py`, implement `generate()`.
2. Add one line to `src/strategies/__init__.py` `STRATEGIES`.
3. Optional: add params under `strategies:` in `config.yaml`.
4. Rebuild: `docker compose up -d --build`.

## Run
```bash
cd /mnt/store/apps/ibkr-paper
docker compose up -d --build
curl http://100.101.82.11:8005/health
curl -X POST http://100.101.82.11:8005/signals/run
```

## API
- `GET /health`, `GET /strategies`
- `GET /ibkr/auth`, `GET /ibkr/accounts`, `GET /ibkr/positions?account=DUT160850`
- `POST /signals/run` — one paper cycle
- `GET /paper/signals`, `GET /paper/positions`, `GET /paper/pnl`

## Paper login (Ankit)
Gateway login is manual, in the browser: `https://100.101.82.11:5000`
(paper username `sonalivpt`), then this service can read market data.
