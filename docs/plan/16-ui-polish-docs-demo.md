# CP16 — UI Polish, Docs & Final Demo Readiness

Spec milestone: M6 (completes M6). Depends on: CP8, CP15.

## Goal

Polish the chat UI's handling of loading/error states and the clarification / two-cart
comparison / real-cart-result / warnings surfaces built across CP5–CP8, finalize the project
README, and rehearse the end-to-end demo script covering every acceptance criterion in
`docs/spec.md` §12.

## Scope

Frontend polish only (no new backend behavior), documentation, and a manual demo rehearsal.
This is the last checkpoint — after this, the project matches its spec end to end.

## Deliverables

- The UI clearly distinguishes: normal agent messages, item-clarification prompts, the
  two-cart comparison with its choose/decline control, the real-cart-preparation result
  (including blocked/partial states), missing items, warnings, stale-data banners, and
  budget trade-off suggestions — with loading and error states for the network call itself.
- A complete `README.md` covering setup, running locally (bare + docker-compose), running
  tests, deploying (Terraform → kubeadm → ArgoCD → promotion), viewing monitoring, and the
  demo script.
- A final manual pass through every bullet in spec §12 against the deployed `prod`
  namespace, confirming each one still holds after CP9–CP15's changes.

## Files to Modify

- `web/src/App.tsx`
- `web/src/components/RetailerCartsView.tsx`
- `web/src/components/ClarificationPrompt.tsx`
- `web/src/components/RetailerCartResultView.tsx`
- `README.md`

## Detailed Implementation Steps

### UI polish

1. In `web/src/App.tsx`, add a `loading` boolean set around every `postChat` call; disable
   the input/send button and show a spinner/"Thinking…" while a request is in flight.
2. Add an `error` state: if `postChat` throws (network failure, non-2xx), show a dismissible
   error banner instead of leaving the UI stuck or silently failing.
3. In `RetailerCartsView.tsx`, ensure each retailer's staleness warning renders as a
   distinct banner above that retailer's items — never mixed into the other retailer's
   section, matching spec §5's "reported independently, never one global flag." Ensure
   budget status (within/exceeds budget) and any `trade_off_suggestions` render clearly per
   retailer, and that savings vs. the other retailer is visible.
4. Ensure `ClarificationPrompt.tsx` (item/recipe ambiguity) and `RetailerCartsView.tsx`'s
   choose/decline control are visually distinguishable — different heading text ("I need to
   check something" vs. "Which cart would you like to use?") so a user never confuses an
   item clarification with the final retailer choice.
5. In `RetailerCartResultView.tsx`, ensure `added` items show a success indicator, `failed`
   items show their `reason`, and a `blocked` result shows a clear banner naming
   `blocked_reason` plus whatever partial `added` list exists — never a blank state that
   looks like nothing happened.
6. Manually re-walk every flow (grocery list, recipe, dietary substitution, ambiguous item
   clarification, over-budget with trade-off suggestion, choosing a retailer, choosing the
   other retailer, declining) against the local docker-compose stack, confirming the UI
   reads clearly at each step.

### Documentation

7. Rewrite `README.md`: project overview (linking to `docs/spec.md`); local setup
   (`make install && make test && make run`, plus `docker compose up`); required env vars
   (`.env.example`, `SPOONACULAR_API_KEY`, `BEDROCK_MODEL_ID`, AWS credentials); running
   tests (`make test`; `pytest tests/mcp` for Playwright/mock-site tests, needs
   `playwright install` first); deploying (`infra/terraform` → ArgoCD bootstrap (CP11) →
   CI/CD (CP12) → promotion (CP13), each pointing at its `docs/plan/` file); reaching
   Grafana (CP14); and a numbered demo script:
   1. Direct grocery-list request → both retailers' carts shown side by side.
   2. Recipe request ("shakshuka for 4") → scaled ingredients → both carts.
   3. A dietary-constrained request → show a substitution happening in each retailer's cart.
   4. A request engineered to hit an ambiguous item → clarification round-trip (once, not
      once per retailer) → both carts.
   5. A tight-budget request → show a retailer's cart reporting over-budget with a trade-off
      suggestion.
   6. Choose a retailer's cart → show Playwright preparing the real cart (mock site or, if
      demoing live, an actual Shufersal/Rami Levy product) → show it stops before checkout.
   7. Decline instead → show nothing further happens.
   8. Show the `dev` and `prod` namespaces both running on the same kubeadm cluster via
      `kubectl get pods -A`.
   9. Merge a trivial change → show the CI/CD pipeline run → show ArgoCD auto-sync `dev`.
   10. Run the promotion script → PR → manual ArgoCD sync → show `prod` update.
   11. Open the Grafana dashboard and point out request latency, MCP call rates, ingestion
       freshness, retailer-cart outcomes, and error codes from the demo traffic just
       generated.
8. Commit.

### Final acceptance-criteria pass

9. Walk through every bullet in `docs/spec.md` §12 one more time, against the deployed
   `prod` namespace (post-CP13/CP15 changes), and confirm each still holds. Fix anything
   that regressed during CP9–CP15 before considering the project done.

## Testing Tasks

- [ ] Manual UI walkthrough of all eight flows in step 6, confirming clarity of each state.
- [ ] `README.md` instructions followed literally by re-running local setup from a clean
      clone, confirming nothing is missing or stale.
- [ ] Full spec §12 acceptance-criteria re-walkthrough against `prod` passes.

## Acceptance Criteria

A new reader can follow `README.md` alone to run the project locally, understand how to
deploy it, and follow the demo script; the UI never leaves a user confused about which kind
of prompt (item clarification vs. final retailer choice) they're responding to, or what
happened after choosing a cart.

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
