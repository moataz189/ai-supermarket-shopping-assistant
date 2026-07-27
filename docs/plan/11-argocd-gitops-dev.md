# CP11 — ArgoCD GitOps Bootstrap & Dev Deployment

Spec milestone: M4 (completes M4). Depends on: CP9, CP10.

## Goal

Install ArgoCD onto the kubeadm cluster (one-time bootstrap), stand up the `dev` namespace's
Kubernetes resources (backend, web, Postgres, ingestion CronJob), and wire ArgoCD to
continuously and automatically sync `k8s/dev/` — so a merge to `main` flows through to a
running dev deployment without any manual `kubectl apply` after this checkpoint.

## Scope

ArgoCD installation, `k8s/dev/` manifests, the `dev` and `prod` ArgoCD `Application`
resources (prod's manifest directory gets only a placeholder namespace for now — CP13 fills
it in), and the Terraform IAM/DynamoDB additions the deployed app needs. No GitHub Actions
yet (CP12) — manifests are applied by hand once, and thereafter ArgoCD takes over.

## Deliverables

- ArgoCD running in the cluster, reachable via port-forward or NodePort.
- `k8s/dev/` deployed and healthy: backend, all three MCP servers (each its own
  Deployment/Service, per CP9's container split), web, Postgres, and the ingestion CronJob,
  all running in the `supermarket-dev` namespace.
- The dev `Application` auto-syncs — a manual `kubectl apply -f k8s/dev/backend-deployment.yaml`
  with a changed image tag is picked up by ArgoCD without any further manual command.

## Files to Create

```
k8s/dev/namespace.yaml
k8s/dev/secret.env.example
k8s/dev/postgres-pv.yaml
k8s/dev/postgres-statefulset.yaml
k8s/dev/postgres-service.yaml
k8s/dev/supermarket-mcp-deployment.yaml
k8s/dev/supermarket-mcp-service.yaml
k8s/dev/recipe-mcp-deployment.yaml
k8s/dev/recipe-mcp-service.yaml
k8s/dev/retailer-cart-mcp-deployment.yaml
k8s/dev/retailer-cart-mcp-service.yaml
k8s/dev/backend-deployment.yaml
k8s/dev/backend-service.yaml
k8s/dev/web-deployment.yaml
k8s/dev/web-service.yaml
k8s/dev/ingestion-cronjob.yaml
k8s/prod/namespace.yaml
k8s/argocd/dev-application.yaml
k8s/argocd/prod-application.yaml
```

## Files to Modify

- `infra/terraform/main.tf` — extend the node IAM role with DynamoDB and Bedrock
  permissions, and create the DynamoDB checkpoint table.

## Detailed Implementation Steps

### Terraform additions (DynamoDB checkpoint table + IAM)

1. Add to `infra/terraform/main.tf`:
   ```hcl
   resource "aws_dynamodb_table" "langgraph_checkpoints" {
     name         = "supermarket-assistant-checkpoints"
     billing_mode = "PAY_PER_REQUEST"
     hash_key     = "thread_id"
     range_key    = "checkpoint_id"

     attribute {
       name = "thread_id"
       type = "S"
     }

     attribute {
       name = "checkpoint_id"
       type = "S"
     }
   }

   resource "aws_iam_role_policy" "app_permissions" {
     name = "supermarket-assistant-app"
     role = aws_iam_role.node.id
     policy = jsonencode({
       Version = "2012-10-17"
       Statement = [
         {
           Effect   = "Allow"
           Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:DeleteItem"]
           Resource = aws_dynamodb_table.langgraph_checkpoints.arn
         },
         {
           Effect   = "Allow"
           Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
           Resource = "*"
         }
       ]
     })
   }
   ```
   (Pods on either EC2 node inherit these permissions via the instance profile already
   attached in CP10 — no separate pod-level IAM identity is needed for a self-managed
   kubeadm cluster.)
2. `terraform apply` from `infra/terraform/` to create the table and attach the new policy.
3. Extend `app/agent/checkpointer.py` (from CP4) with the `dynamodb` branch it was left
   ready for:
   ```python
   if backend == "dynamodb":
       from langgraph_checkpoint_dynamodb import DynamoDBSaver  # or equivalent package

       return DynamoDBSaver(table_name="supermarket-assistant-checkpoints")
   ```
   (Confirm the exact package/class name against whatever LangGraph DynamoDB checkpointer
   is current at implementation time — pin it in `pyproject.toml`.)

### ArgoCD bootstrap (one-time, manual)

4. `export KUBECONFIG=<path from CP10>`.
5. `kubectl create namespace argocd`.
6. `kubectl apply -n argocd -f
   https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml`.
7. Wait for pods: `kubectl -n argocd get pods -w` until all `Running`.
8. Retrieve the initial admin password: `kubectl -n argocd get secret
   argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d`.
9. `kubectl -n argocd port-forward svc/argocd-server 8080:443 &` and log in at
   `https://localhost:8080` (or via `argocd login localhost:8080`) to confirm access.

### `k8s/dev/` manifests

10. Write `k8s/dev/namespace.yaml`:
    ```yaml
    apiVersion: v1
    kind: Namespace
    metadata:
      name: supermarket-dev
    ```
11. Write `k8s/dev/secret.env.example` (documents required keys; the real Secret is created
    manually, never committed):
    ```
    BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
    AWS_REGION=us-east-1
    SPOONACULAR_API_KEY=changeme
    POSTGRES_PASSWORD=changeme
    ```
    Create the real secret with: `kubectl -n supermarket-dev create secret generic
    app-secrets --from-env-file=k8s/dev/secret.env` (a local, gitignored copy of the example
    with real values).
12. Write `k8s/dev/postgres-pv.yaml` — since this cluster has no EBS CSI driver, use a
    `hostPath` PersistentVolume anchored to the worker node (acceptable simplification for a
    solo MVP; document the trade-off in Risks below):
    ```yaml
    apiVersion: v1
    kind: PersistentVolume
    metadata:
      name: postgres-dev-pv
    spec:
      capacity:
        storage: 5Gi
      accessModes: ["ReadWriteOnce"]
      hostPath:
        path: /var/lib/supermarket-assistant/postgres-dev
      nodeAffinity:
        required:
          nodeSelectorTerms:
          - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values: ["<worker-node-hostname>"]
    ---
    apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
      name: postgres-dev-pvc
      namespace: supermarket-dev
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 5Gi
      volumeName: postgres-dev-pv
    ```
13. Write `k8s/dev/postgres-statefulset.yaml` and `postgres-service.yaml` (standard
    `postgres:16` image, env from the `app-secrets` Secret, volume mount to the PVC above, a
    headless/ClusterIP Service named `postgres`).
14. Write one Deployment+Service pair per MCP server, each its own workload (per CP9's
    container split), each exposed only inside the cluster (`ClusterIP`, no NodePort needed
    — only the backend talks to them):
    - `k8s/dev/supermarket-mcp-deployment.yaml` / `-service.yaml` — image from CP9's
      `Dockerfile`, `command: ["python", "-m", "mcp_servers.supermarket_mcp.server"]`, env
      `DATABASE_URL` (same Postgres as the backend) and `PORT=8001`; Service named
      `supermarket-mcp` exposing `8001`.
    - `k8s/dev/recipe-mcp-deployment.yaml` / `-service.yaml` — same image, `command:
      ["python", "-m", "mcp_servers.recipe_mcp.server"]`, env `SPOONACULAR_API_KEY` (from
      the Secret) and `PORT=8002`; Service named `recipe-mcp` exposing `8002`.
    - `k8s/dev/retailer-cart-mcp-deployment.yaml` / `-service.yaml` — image from CP9's
      `Dockerfile.retailer-cart-mcp`, env `PORT=8003`; resource requests/limits generous
      enough for headless Chromium, e.g. `requests: {cpu: "250m", memory: "512Mi"}, limits:
      {cpu: "1", memory: "1Gi"}`; Service named `retailer-cart-mcp` exposing `8003`.
15. Write `k8s/dev/backend-deployment.yaml` (image from CP9's `Dockerfile`, env
    `DATABASE_URL=postgresql+psycopg://app:$(POSTGRES_PASSWORD)@postgres:5432/supermarket`,
    `CHECKPOINTER_BACKEND=dynamodb`, `AWS_REGION`, `BEDROCK_MODEL_ID`,
    `SPOONACULAR_API_KEY` from the Secret, plus the three MCP URLs pointed at the Services
    from step 14: `SUPERMARKET_MCP_URL=http://supermarket-mcp:8001/mcp`,
    `RECIPE_MCP_URL=http://recipe-mcp:8002/mcp`,
    `RETAILER_CART_MCP_URL=http://retailer-cart-mcp:8003/mcp`) and `backend-service.yaml`
    (`type: NodePort`, exposing `8000` on a NodePort within the range opened in CP10's
    security group).
16. Write `k8s/dev/web-deployment.yaml` (image from CP9's `web/Dockerfile`) and
    `web-service.yaml` (`type: NodePort`, exposing `80`).
17. Write `k8s/dev/ingestion-cronjob.yaml` (image from CP9's `Dockerfile`, `command:
    ["python", "-m", "app.ingestion.run", "--source", "live"]` — note this requires the
    `--source live` mode of CP2's ingestion CLI to be added when this checkpoint is
    implemented, since CP2 only built `--source fixtures`; schedule `"0 3 * * *"` for a daily
    run).
18. Write `k8s/prod/namespace.yaml` (just the namespace — a placeholder so the prod
    `Application` created in step 19 has a valid, syncable path; CP13 adds the rest):
    ```yaml
    apiVersion: v1
    kind: Namespace
    metadata:
      name: supermarket-prod
    ```

### ArgoCD `Application` resources

19. Write `k8s/argocd/dev-application.yaml` (automated sync, self-heal, and prune all
    enabled, per spec §7):
    ```yaml
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: supermarket-assistant-dev
      namespace: argocd
    spec:
      project: default
      source:
        repoURL: https://github.com/moataz189/ai-supermarket-shopping-assistant.git
        targetRevision: main
        path: k8s/dev
      destination:
        server: https://kubernetes.default.svc
        namespace: supermarket-dev
      syncPolicy:
        automated:
          selfHeal: true
          prune: true
        syncOptions:
          - CreateNamespace=true
    ```
20. Write `k8s/argocd/prod-application.yaml` (no `automated` block — manual sync only):
    ```yaml
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: supermarket-assistant-prod
      namespace: argocd
    spec:
      project: default
      source:
        repoURL: https://github.com/moataz189/ai-supermarket-shopping-assistant.git
        targetRevision: main
        path: k8s/prod
      destination:
        server: https://kubernetes.default.svc
        namespace: supermarket-prod
      syncPolicy:
        syncOptions:
          - CreateNamespace=true
    ```
21. Apply both once, directly (this one-time bootstrap step is the only manual `kubectl
    apply` for `Application` resources — everything after this is GitOps-only):
    `kubectl apply -f k8s/argocd/dev-application.yaml -f k8s/argocd/prod-application.yaml`.
22. Watch `kubectl -n argocd get applications` (or the ArgoCD UI) until
    `supermarket-assistant-dev` shows `Synced`/`Healthy`.
23. `kubectl -n supermarket-dev get pods` — confirm backend, all three MCP servers, web,
    postgres, and the ingestion CronJob's next scheduled run all look correct.
24. Manually trigger one ingestion run (`kubectl -n supermarket-dev create job --from=cronjob/ingestion-cronjob ingestion-manual-test`)
    and confirm it completes and populates Postgres.
25. `curl` the backend's and web's NodePorts (from the EC2 worker's public IP) to confirm
    both are reachable, then manually walk through the grocery-list, recipe, and
    retailer-choice flows end-to-end against this dev deployment — note that in this
    deployed environment, choosing a retailer drives Playwright against the **real**
    Shufersal/Rami Levy adapters (not the CP8 mock site), consistent with spec §6/§11
    treating live-site automation as best-effort and manually verified.
26. Commit all new/modified files (excluding the real `k8s/dev/secret.env`, `.tfstate`, and
    kubeconfig).

## Testing Tasks

- [ ] ArgoCD installed and reachable.
- [ ] `supermarket-assistant-dev` Application is `Synced`/`Healthy`.
- [ ] All dev-namespace pods running (backend, all three MCP servers, web, postgres);
      manual ingestion job run succeeds.
- [ ] Backend `/health` and web root reachable via NodePort from outside the cluster.
- [ ] Manual end-to-end walkthrough (grocery list, recipe, cart approval) against the dev
      deployment.
- [ ] A manifest change applied to `k8s/dev/` and pushed to `main` is picked up by ArgoCD
      without further manual `kubectl` commands.

## Acceptance Criteria

The `dev` namespace runs the full application (backend, all three MCP servers, web,
Postgres, ingestion) on the
kubeadm cluster, deployed and kept in sync by ArgoCD; the `prod` namespace exists with a
placeholder, ready for CP13.

## Risks

- The `hostPath` PersistentVolume for Postgres ties the pod to a specific node and has no
  redundancy — acceptable for a solo MVP; a real deployment would use a CSI-backed volume or
  RDS instead.
- Manually applying `Application` resources is a one-time step per this checkpoint's design
  (spec §7 "Bootstrap (one-time)") — if the ArgoCD installation is ever wiped, this step
  must be redone before GitOps resumes.

## Notes

CP12 (GitHub Actions) will be the only path that changes `k8s/dev/` image tags going
forward — do not hand-edit `k8s/dev/` image tags after CP12 lands except through the CI
pipeline, or the two will drift.

## Definition of Done

- [ ] ArgoCD installed; both `Application` resources applied.
- [ ] `k8s/dev/` fully deployed and healthy, verified via `kubectl` and manual walkthrough.
- [ ] Terraform DynamoDB table + IAM additions applied.
- [ ] Committed with message referencing CP11. **M4 milestone complete at this point.**
