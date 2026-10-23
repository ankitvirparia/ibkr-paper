# Tasks 005 — Sync with IBKR Paper

TDD order: tests first (red), then implementation (green). Commit per task group.

1. [ ] Write tests/test_ibkr_state.py (mocked gateway): state mapping incl.
       CAD+USD cash, SessionNotLive -> API 503, AccountGuardError on foreign
       account, /iserver/accounts exactly-once init. (red)
2. [ ] Update tests/test_allocator.py: allocator sizes from supplied live
       NetLiq state. (red)
3. [ ] Add a guard test: no src/ module imports paper_ledger; app boots with
       no DB file. (red)
4. [ ] Implement src/engine/ibkr_state.py (ensure_session, get_account_state).
5. [ ] Rewire src/api.py account/positions endpoints to ibkr_state; remove
       PaperLedger wiring and ledger endpoints. Orders endpoints untouched.
6. [ ] Allocator: take account_state input; runner uses live state only.
7. [ ] us_momentum: remove auto_fill fill behavior (signals only).
8. [ ] Delete src/engine/paper_ledger.py; drop db_path from config.yaml;
       replace tests/test_paper_ledger.py with the new suite.
9. [ ] Full pytest green (incl. spec-004 routing suite, 54 tests).
10. [ ] Rebuild image + recreate container; live-verify account endpoint vs
        gateway summary; confirm no paper.db is recreated.
11. [ ] Commits: spec (done), tests, implementation, cleanup — conventional
        messages referencing Spec 005. Do NOT push (no remote configured).
