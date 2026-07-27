# CP16 — UI Polish, Docs & Final Demo Readiness

Spec milestone: M6 (completes M6). Depends on: CP8, CP15.

## Goal

Polish the chat UI's handling of loading/error states and the clarification /
cart-approval / real-cart-result / warnings surfaces built across CP5–CP8, finalize the
project README, and rehearse the end-to-end demo script that walks through every acceptance
criterion in `docs/spec.md` §12.

## Scope

Frontend polish only (no new backend behavior), documentation, and a manual demo rehearsal.
This is the last checkpoint — after this, the project matches its spec end to end.

## Deliverables

- The UI clearly distinguishes: normal agent messages, clarification prompts, the
  cart-approval prompt, the real-cart-preparation result (including blocked/partial states),
  missing items, warnings, and stale-data banners — with loading and error states for the
  network call itself.
- A complete `README.md` covering setup, running locally (bare + docker-compose), running
  tests, deploying (Terraform → kubeadm → ArgoCD → promotion), viewing monitoring, and the
  demo script.
- A final manual pass through every bullet in spec §12 against the deployed `prod`
  namespace, confirming each one still holds after CP9–CP15's changes.

## Files to Modify

- `web/src/App.tsx`
- `web/src/components/CartView.tsx`
- `web/src/components/ClarificationPrompt.tsx`
- `web/src/components/CartApprovalPrompt.tsx`
- `web/src/components/RetailerCartResultView.tsx`
- `README.md`

## Detailed Implementation Steps

### UI polish

1. In `web/src/App.tsx`, add a `loading` boolean state set around every `postChat` call;
   disable the input/send button and show a small spinner/"Thinking…" indicator while a
   request is in flight, so double-submission isn't possible.
2. Add a `error` state: if `postChat` throws (network failure, non-2xx), show a dismissible
   error banner ("Something went wrong — try again") instead of leaving the UI stuck or
   silently failing.
3. In `CartView.tsx`, ensure the per-retailer staleness warning (from a `warnings` entry with
   a staleness code) renders as a distinct, visually separate banner above the cart items —
   not mixed in with missing-items text — matching spec §5's "surfaced per-retailer, never
   collapsed into one global flag."
4. In `ClarificationPrompt.tsx` and `CartApprovalPrompt.tsx`, ensure both are visually
   distinguishable from each other (different heading text: "I need to check something" vs.
   "Ready to add this to your cart?") so a user never confuses a product/recipe
   clarification with the cart-approval decision.
5. In `RetailerCartResultView.tsx`, ensure: `added` items render with a success indicator,
   `failed` items render with their `reason`, and a `blocked` result renders a clear banner
   naming `blocked_reason` plus whatever partial `added` list exists — never an empty/blank
   state that looks like nothing happened.
6. Manually re-walk every flow (grocery list, recipe, dietary substitution, ambiguous
   clarification, cart approval declined, cart approval approved with partial failure,
   cart approval approved with a block) against the local docker-compose stack, confirming
   the UI reads clearly at each step.

### Documentation

7. Rewrite `README.md` with these sections: a one-paragraph project overview (linking to
   `docs/spec.md`); local setup (`make install && make test && make run`, plus
   `docker compose up`); required environment variables (`.env.example` from CP1, plus
   `SPOONACULAR_API_KEY`, `BEDROCK_MODEL_ID`, AWS credentials); how to run the test suite
   (`make test`, `pytest tests/mcp` for the Playwright/mock-site tests specifically since
   they need `playwright install` first); how to deploy (`infra/terraform` →
   `kubectl`/ArgoCD bootstrap from CP11 → CI/CD from CP12 → promotion from CP13, each with a
   one-line pointer to its `docs/plan/` file); how to reach Grafana (CP14); and a numbered
   demo script:
   1. Direct grocery-list request → proposed cart.
   2. Recipe request ("shakshuka for 4") → scaled ingredients → proposed cart.
   3. A dietary-constrained request → show a substitution happening.
   4. A request engineered to hit an ambiguous product match → clarification round-trip.
   5. Approve a proposed cart → show Playwright preparing the real cart (mock site or, if
      demoing live, an actual Shufersal/Rami Levy product) → show it stops before checkout.
   6. Decline a proposed cart → show nothing further happens.
   7. Show the `dev` and `prod` namespaces both running on the same kubeadm cluster via
      `kubectl get pods -A`.
   8. Merge a trivial change → show the CI/CD pipeline run → show ArgoCD auto-sync `dev`.
   9. Run the promotion script → PR → manual ArgoCD sync → show `prod` update.
   10. Open the Grafana dashboard and point out request latency, MCP call rates, ingestion
       freshness, retailer-cart outcomes, and error codes populated from the demo traffic
       just generated.
8. Commit.

### Final acceptance-criteria pass

9. Walk through every bullet in `docs/spec.md` §12 one more time, against the deployed
   `prod` namespace (post-CP13/CP15 changes), and confirm each still holds. Fix anything
   that regressed during CP9–CP15 before considering the project done.

## Testing Tasks

- [ ] Manual UI walkthrough of all seven flows listed in step 6, confirming clarity of each
      state.
- [ ] `README.md` instructions followed literally by re-running local setup from a clean
      clone, confirming nothing is missing or stale.
- [ ] Full spec §12 acceptance-criteria re-walkthrough against `prod` passes.

## Acceptance Criteria

A new reader can follow `README.md` alone to run the project locally, understand how to
deploy it, and follow the demo script; the UI never leaves a user confused about which kind
of prompt (clarification vs. approval) they're responding to, or what happened after
approving a cart.

## Risks

- None specific to this checkpoint — it is a polish/documentation pass, not new
  functionality.

## Notes

This is the final checkpoint. Once its Definition of Done is met, `docs/plan.md`'s Final
Milestone section should be checked off in full.

## Definition of Done

- [ ] UI polish items implemented and manually verified.
- [ ] `README.md` complete and verified against a clean clone.
- [ ] Full spec §12 acceptance-criteria walkthrough passes against `prod`.
- [ ] Committed with message referencing CP16. **M6 milestone complete — project complete.**
