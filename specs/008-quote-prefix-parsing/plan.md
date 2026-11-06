# Plan — Spec 008

1. Failing tests first (`tests/test_quote_prefix.py`): C-prefixed last
   parses and Greeks compute; a garbage last degrades (mid from
   bid/ask still used); a quote with no usable price still returns None.
2. Add `_num()` to `src/ibkr_client.py`; use it in `_greeks_from_quote`.
3. Use the same `_num()` in `src/engine/runner.py`'s chain loop.
4. Full pytest suite green; commit + push.
5. Rebuild the container (app src is baked into the image — spec 007
   lesson) and verify `_num` is present in the running code.
6. Re-preview the affected order (AVGO 295P Dec 11) end to end.
