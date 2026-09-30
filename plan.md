# ibkr-paper — plan

1. `src/strategies/base.py` — `Signal`, `StrategyContext`, `Strategy` ABC.
2. `src/strategies/us_momentum.py` + `src/strategies/options_income.py` + `TEMPLATE.py`.
3. `src/strategies/__init__.py` — registry.
4. `src/engine/allocator.py` — sleeve math, sizing guards, kill switch.
5. `src/engine/paper_ledger.py` — SQLite ledger.
6. `src/ibkr_client.py` — read-only CPGW client (httpx, self-signed local cert).
7. `src/engine/runner.py` — cycle orchestration.
8. `src/api.py` — FastAPI service.
9. `config.yaml`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`.
10. `tests/` — strategies, allocator, ledger, client (mocked). All green on server.
11. `docker compose up -d`; verify `/health`; document Ankit's one-time gateway login.
