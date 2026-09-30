# Tasks 004 — Paper Order Routing

- [x] 1. Ship spec/plan/tasks to `/mnt/store/apps/ibkr-paper/specs/004-paper-order-routing/`
- [x] 2. Tests: order JSON builder shape (stock MKT buy; option LMT sell)
- [x] 3. Tests: place → success / confirm-required (no auto-confirm) / error shapes
- [x] 4. Tests: confirm loops cascading replies
- [x] 5. Tests: paper-account guard refuses foreign accounts
- [x] 6. Tests: ticket tamper / expiry / single-use enforcement
- [x] 7. Tests: runner isolation — run_cycle never touches /orders
- [x] 8. Implement `src/engine/broker.py` (PaperBroker)
- [x] 9. Implement ledger tables (broker_orders, order_tickets)
- [x] 10. Implement API endpoints (/orders/preview|place|confirm, GET /orders, DELETE /orders/{id})
- [x] 11. Config: paper.account_id + order_ticket_ttl_sec
- [x] 12. Full pytest green in container
- [ ] 13. Live preview-only test vs paper gateway (no placement)
- [ ] 14. Commit incrementally; push to GitHub (repo creation pending Ankit)
