# CP15 — Test Suite Hardening & Demo Resilience

Spec milestone: M6 (starts). Depends on: CP12, CP13, CP14.

## Goal

Close the remaining gaps between the automated test suite and spec §6's testing strategy —
concurrent-thread-id isolation, ingestion edge cases, dietary-engine edge cases, MCP contract
completeness — and add the stored-snapshot fallback (spec §5) so a temporarily-unavailable
live retailer feed doesn't block a demo.

## Scope

Test additions and one ingestion-pipeline feature (snapshot fallback). No new
product-facing behavior beyond the fallback itself.

## Deliverables

- A concurrent-thread-id isolation test proving two simultaneous conversations never leak
  state into each other.
- Ingestion can fall back to a recent stored snapshot when a live feed download fails,
  through the exact same parse→validate→stage→activate code path as a live download.
- A short audit confirming every bullet in `docs/spec.md` §6 maps to at least one real test.

## Files to Create

```
tests/agent/test_concurrent_thread_isolation.py
tests/ingestion/test_snapshot_fallback.py
tests/ingestion/test_schema_tolerance.py
tests/dietary/test_rules_combined_constraints.py
data/snapshots/shufersal_latest.xml
data/snapshots/rami_levy_latest.xml
```

## Files to Modify (additional)

- `Dockerfile` (CP9, the shared app image used by the backend and the ingestion job) — add
  `COPY data ./data` alongside the existing `COPY app ./app` / `COPY mcp_servers
  ./mcp_servers` lines, so the fallback snapshot files are actually present in the deployed
  image. Without this, CP11/CP13's containers would have no
  fallback file to read and the fallback would only work in local, non-containerized runs.

## Files to Modify

- `app/ingestion/feeds/shufersal.py`, `rami_levy.py` — download function gains a fallback
  path.
- `app/ingestion/run.py` — CLI wires the fallback snapshot path in for the `live` source.
- `app/ingestion/pipeline.py` — after a successful **live** ingestion, write the just-fetched
  feed bytes to `data/snapshots/<retailer>_latest.xml` so the fallback stays reasonably
  fresh.

## Detailed Implementation Steps

### Concurrent thread-id isolation

1. Write `tests/agent/test_concurrent_thread_isolation.py`:
   ```python
   import asyncio

   from app.agent.graph import build_graph


   async def test_two_threads_do_not_leak_state(fake_supermarket_client_factory, fake_llm_factory, checkpointer):
       graph = build_graph(
           fake_supermarket_client_factory(), fake_recipe_client(), fake_retailer_cart_client(),
           fake_llm_factory(), checkpointer,
       )

       async def run(thread_id: str, message: str):
           return await graph.ainvoke(
               {"raw_message": message}, config={"configurable": {"thread_id": thread_id}}
           )

       result_a, result_b = await asyncio.gather(
           run("thread-a", "milk and bread"),
           run("thread-b", "rice and oil"),
       )

       assert result_a["final_result"]["carts"] != result_b["final_result"]["carts"]
       names_a = {item["name"] for item in result_a["final_result"]["carts"]["shufersal"]["items"]}
       names_b = {item["name"] for item in result_b["final_result"]["carts"]["shufersal"]["items"]}
       assert names_a.isdisjoint(names_b - names_a)  # no cross-contamination of items
   ```
   Adapt the exact fixture names to whatever CP4/CP7/CP8's test fakes ended up being called
   — the point is two concurrent `ainvoke` calls with different `thread_id`s against the
   same compiled graph/checkpointer instance, asserting their results reflect only their own
   input.
2. Add a second case in the same file where **one** thread hits an ambiguous-product
   interrupt while the other completes straight through concurrently; assert the
   interrupted thread's pending state is unaffected by the other thread's completion, and
   resuming it later (with its own `thread_id`) still produces the correct result.
3. Run, iterate to green.

### Demo-resilience snapshot fallback

4. Modify `app/ingestion/feeds/shufersal.py` (and `rami_levy.py` identically) to separate
   "fetch bytes" from "parse bytes", and add a fallback-aware fetch function:
   ```python
   import logging

   import httpx

   logger = logging.getLogger(__name__)


   def fetch(url: str, fallback_path: str) -> bytes:
       try:
           response = httpx.get(url, timeout=30.0)
           response.raise_for_status()
           return response.content
       except httpx.HTTPError as exc:
           logger.warning("Live feed fetch failed (%s); falling back to stored snapshot %s", exc, fallback_path)
           with open(fallback_path, "rb") as f:
               return f.read()
   ```
5. Modify `app/ingestion/pipeline.py`'s live-ingestion call site (added when `--source live`
   was implemented per CP11's ingestion CronJob) to: call `fetch(...)`, `parse(...)` the
   result, run `ingest_retailer_feed(...)` as before, and — only after a **successful**
   activation from a **live** fetch (not a fallback read) — write the fetched bytes to
   `data/snapshots/<retailer>_latest.xml`, keeping the fallback reasonably current:
   ```python
   def ingest_live(session, retailer, url, fallback_path, parse_fn):
       content = fetch(url, fallback_path)
       parsed = parse_fn(content)
       ingest_retailer_feed(session, retailer, parsed)
       if content is not None:
           with open(fallback_path, "wb") as f:
               f.write(content)
   ```
6. Commit two small, real, hand-built snapshot files at `data/snapshots/shufersal_latest.xml`
   and `rami_levy_latest.xml` (same shape as CP2's test fixtures) as the initial fallback
   content before any live ingestion has ever run.
7. Write `tests/ingestion/test_snapshot_fallback.py`: mock `httpx.get` to raise
   `httpx.HTTPError`, call `fetch(url, fallback_path=<a test fixture path>)`, assert it
   returns the fixture file's bytes instead of raising; a second test confirms a successful
   mock response is returned as-is without touching the fallback file.
8. Run, iterate to green.

### Ingestion schema tolerance

9. Write `tests/ingestion/test_schema_tolerance.py`: construct a feed fixture with one extra,
   unexpected XML field the parser doesn't know about; assert `parse()` still succeeds and
   simply ignores the unknown field (rather than raising) — this is a forward-compatibility
   guard distinct from CP2's `shufersal_corrupt.xml` case (which tests a feed missing
   required structure, and should still raise).

### Dietary engine combined constraints

10. Write `tests/dietary/test_rules_combined_constraints.py`: `forbidden_tags(["vegan"])`
    includes both `contains_meat` and `contains_dairy`; a name matching either is a
    violation; constraint text matching is case-insensitive
    (`violates("Whole MILK", ["No Dairy"])` is `True`).

### Test-suite audit against spec §6

11. Read through `docs/spec.md` §6 bullet by bullet and confirm each has at least one
    corresponding test file from CP1–CP15; record the mapping directly in this checkpoint's
    PR description (not a new doc file) so it's reviewable once, not maintained forever.
    Expected mapping:
    - Unit tests → CP2 (ingestion parsing), CP4 (`_resolve_item` rules, per-retailer cart
      building, budget trade-off logic), CP7 (dietary rules)
    - Integration tests → CP5 (chat endpoint), CP12 (Postgres compatibility)
    - Contract tests → CP3, CP6, CP8
    - End-to-end agent tests → CP4, CP7, CP8
    - Concurrent thread-id test → this checkpoint, step 1–3
    - Production-DB compatibility test → CP12
    - Ingestion tests → CP2, this checkpoint (fallback, schema tolerance)
    - Mock-site browser-automation tests → CP8
    If any spec §6 bullet has no owner, add the missing test now rather than leaving a gap.
12. Run the entire test suite (`pytest`), `ruff check`, commit.

## Testing Tasks

- [ ] Concurrent thread-id isolation tests pass.
- [ ] Snapshot fallback tests pass; fallback file exists and is realistic.
- [ ] Schema-tolerance test passes.
- [ ] Combined dietary-constraint tests pass.
- [ ] Full audit against spec §6 complete with no unowned bullets.

## Acceptance Criteria

The full automated test suite covers every bullet in spec §6, including concurrency
isolation and the demo-resilience fallback; ingestion continues to work end-to-end (via
fallback) even if a live retailer feed is temporarily unreachable.

## Risks

- The committed `data/snapshots/*.xml` files will go stale over time if live ingestion never
  successfully runs to refresh them — acceptable since they exist purely as a last-resort
  demo safety net, not a primary data source.
- In a deployed pod, the snapshot write-back in step 5 writes to the container's local
  filesystem, which is not persisted across pod restarts — so a refreshed snapshot only
  survives for that pod's lifetime, and the fallback effectively reverts to the
  image-baked snapshot after a restart. Acceptable for a best-effort demo safety net; a
  persistent volume for `data/snapshots/` would fix this but is not worth the added
  complexity for what this feature is for.

## Notes

This checkpoint intentionally does not add new product features — it is a test/robustness
pass over everything CP1–CP14 already built.

## Definition of Done

- [ ] All new tests pass; full suite green; `ruff check` clean.
- [ ] Snapshot fallback verified working.
- [ ] Committed with message referencing CP15.
