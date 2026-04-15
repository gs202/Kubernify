# kubernify

[![PyPI version](https://img.shields.io/pypi/v/kubernify?color=%2334D058&label=pypi%20package)](https://pypi.org/project/kubernify/)
[![Python versions](https://img.shields.io/pypi/pyversions/kubernify?color=%2334D058)](https://pypi.org/project/kubernify/)
[![CI](https://github.com/gs202/Kubernify/actions/workflows/ci.yml/badge.svg)](https://github.com/gs202/Kubernify/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Total Downloads](https://img.shields.io/pepy/dt/kubernify?color=%2334D058)](https://pepy.tech/project/kubernify)

Verify Kubernetes deployments match a version manifest with deep stability auditing. Checks convergence, revision consistency, and pod health.

---

## Features

- **Manifest-driven verification** - Provide a JSON manifest of expected versions; kubernify verifies the cluster matches
- **Deep stability auditing** - Goes beyond version checks: convergence, revision consistency, pod health, DaemonSet scheduling, Job completion
- **Retry-until-converged loop** - Waits for rollouts to complete rather than just snapshot-checking
- **Repository-relative image parsing** - Flexible component name extraction from any image registry format
- **Comprehensive workload support** - Deployments, StatefulSets, DaemonSets, Jobs, and CronJobs
- **Zero-replica awareness** - Verifies version from PodSpec even when HPA/KEDA has scaled to zero
- **Structured JSON reports** - Machine-readable output for CI/CD pipeline integration

---

## Installation

```bash
pip install kubernify
```

Or with [pipx](https://pipx.pypa.io/) for isolated CLI usage:

```bash
pipx install kubernify
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add kubernify
```

---

## Quick Start

```bash
# Verify backend and frontend match expected versions in the "production" namespace
kubernify \
  --context my-cluster-context \
  --anchor my-app \
  --namespace production \
  --manifest '{"backend": "v1.2.3", "frontend": "v1.2.4"}'
```

kubernify will connect to the cluster, discover all matching workloads, verify their image versions against the manifest, run stability audits, and exit with code `0` (pass) or `1` (fail).

---

## CLI Reference

```
kubernify [OPTIONS]
```

| Argument | Description | Default |
|----------|-------------|---------|
| `--context` | Kubeconfig context name to use for cluster connection. Mutually exclusive with `--gke-project`. When omitted, the active kubeconfig context is used automatically. | From kubeconfig |
| `--gke-project` | GCP project ID — resolves the kube context from GKE-style context names (e.g., `gke_my-project_us-central1_cluster-name`). Mutually exclusive with `--context`. |  |
| `--anchor` | **(required)** The image path segment used as the anchor point for component name extraction. For example, given image `registry.example.com/my-org/my-app/backend:v1.0`, using `--anchor my-app` extracts the component name `backend`. See [How Image Anchor Works](#how-image-anchor-works). |  |
| `--manifest` | **(required)** JSON string containing the version manifest mapping component names to their expected versions, e.g. `'{"backend": "v1.2.3", "frontend": "v2.0.0"}'`. |  |
| `--component-aliases` | JSON string mapping manifest component names to their actual image names when they differ. Example: `'{"foo": "bar-baz"}'` means the manifest key `foo` corresponds to the container image named `bar-baz`. Multiple manifest keys can alias to the same image name — disambiguation is performed by matching the manifest key against the Kubernetes workload name (substring match). See [Component Aliases](#component-aliases). |  |
| `--namespace` | Kubernetes namespace to verify. Resolved automatically from kubeconfig context, in-cluster service account, or falls back to `default`. | From kubeconfig context |
| `--required-workloads` | Comma-separated **substring** patterns for workloads that must exist in the namespace, **independent of the manifest**. Useful for ensuring critical workloads (e.g., infrastructure sidecars, operators) are present even if they aren't version-verified. Each pattern is matched against discovered workload names using substring containment (e.g., `frontend` matches `my-app-frontend`). Verification fails if any pattern has no match. |  |
| `--skip-containers` | Comma-separated **substring** patterns to skip during verification. Each pattern is matched against both container names and workload names using substring containment (e.g., `backend` matches `my-app-backend`). Skipped workloads are excluded from both version verification and stability audits. |  |
| `--min-uptime` | Minimum pod uptime in seconds for stability checks. Pods running for less than this duration are flagged as unstable. | `0` |
| `--restart-threshold` | Maximum acceptable container restart count. Containers exceeding this threshold are flagged as unstable. Use `0` to forbid any restarts, or `-1` to skip the restart check entirely. | `3` |
| `--timeout` | Global timeout in seconds for the verification loop. The tool retries discovery and verification until all checks pass or this timeout is reached. Returns exit code `1` (FAIL) on timeout. | `300` |
| `--allow-zero-replicas` | Allow **all** workloads with zero running replicas to pass verification (version is still checked via the pod spec template). Mutually exclusive with `--allow-zero-replicas-for`. | `false` |
| `--allow-zero-replicas-for` | Comma-separated list of workload name **patterns** allowed to have 0 running replicas (e.g., `my-cronjob-worker,batch-processor`). Uses **substring matching**: `my-worker` matches `ns-123-my-worker`. Mutually exclusive with `--allow-zero-replicas`. |  |
| `--dry-run` | Perform a single snapshot check against the current cluster state without waiting for convergence. Exits immediately with pass/fail result. | `false` |
| `--include-statefulsets` | Include StatefulSets in workload discovery. By default, only Deployments are inspected. | `false` |
| `--include-daemonsets` | Include DaemonSets in workload discovery. By default, only Deployments are inspected. | `false` |
| `--include-jobs` | Include Jobs and CronJobs in workload discovery. By default, only Deployments are inspected. | `false` |
| `--ignore-tombstone-pods` | When set, pods in phase `Failed` or `Succeeded` (OOMKilled, Evicted, Completed scripts) are excluded from per-pod health checks. These "gray" pods do not cause health check failures. The deployment availability check (`available_replicas >= spec.replicas`) always runs regardless of this flag. | `false` |

---

## Usage Examples

### Basic Usage - Direct Kubeconfig Context

```bash
kubernify \
  --context my-cluster-context \
  --anchor my-app \
  --namespace production \
  --manifest '{"backend": "v1.2.3", "frontend": "v1.2.4"}'
```

### GKE Shorthand - Resolve Context from GCP Project

```bash
kubernify \
  --gke-project my-gke-project-123456 \
  --anchor my-app \
  --namespace production \
  --manifest '{"backend": "v1.2.3", "frontend": "v1.2.4"}'
```

### In-Cluster - Running Inside a Kubernetes Pod

```bash
# No --context needed; auto-detects in-cluster config and namespace
kubernify \
  --anchor my-app \
  --manifest '{"backend": "v1.2.3", "frontend": "v1.2.4"}'
```

### Full-Featured - All Options

```bash
kubernify \
  --context my-cluster-context \
  --anchor my-app \
  --namespace production \
  --manifest '{"backend": "v1.2.3", "frontend": "v1.2.4", "worker": "v1.2.3"}' \
  --required-workloads "backend, frontend, worker" \
  --skip-containers "istio-proxy, envoy, fluent-bit" \
  --include-statefulsets \
  --include-daemonsets \
  --include-jobs \
  --min-uptime 120 \
  --restart-threshold 5 \
  --ignore-tombstone-pods \
  --timeout 600 \
  --allow-zero-replicas
  # OR selectively:
  # --allow-zero-replicas-for "worker, cron-handler"
```

### Dry Run - Snapshot Check Without Waiting

```bash
kubernify \
  --context my-cluster-context \
  --anchor my-app \
  --manifest '{"backend": "v1.2.3"}' \
  --dry-run
```

### CI/CD Integration - GitHub Actions

```yaml
jobs:
  verify-deployment:
    runs-on: ubuntu-latest
    steps:
      - name: Set up kubeconfig
        run: |
          echo "${{ secrets.KUBECONFIG }}" > /tmp/kubeconfig
          export KUBECONFIG=/tmp/kubeconfig

      - name: Install kubernify
        run: pip install kubernify

      - name: Verify deployment
        run: |
          kubernify \
            --context ${{ secrets.KUBE_CONTEXT }} \
            --anchor my-app \
            --manifest '${{ steps.build.outputs.manifest }}' \
            --timeout 600 \
            --min-uptime 60
```

---

## Programmatic Usage

kubernify can be used as a Python library for custom verification workflows:

```python
from kubernify import __version__, VerificationStatus
from kubernify.kubernetes_controller import KubernetesController
from kubernify.workload_discovery import WorkloadDiscovery
from kubernify.cli import construct_component_map, verify_versions

controller = KubernetesController(context="my-cluster")
discovery = WorkloadDiscovery(k8s_controller=controller)

workloads, _ = discovery.discover_cluster_state(namespace="production")
component_map = construct_component_map(
    workloads=workloads,
    manifest={"backend": "v1.2.3"},
    repository_anchor="my-app",
)
results = verify_versions(manifest={"backend": "v1.2.3"}, component_map=component_map)

if results.errors:
    print(f"Verification failed: {results.errors}")
```

---

## How Image Anchor Works

kubernify uses a **repository-relative anchor** to extract component names from container image paths. The `--anchor` argument specifies the path segment after which the component name is derived.

```
Image: registry.example.com/my-org-foo/my-app-bar/backend:v1.2.3-x
       └──── registry ─────┘ └─ org ─┘ └ anchor ┘└ comp.┘└─ tag ─┘
```

**More examples:**

| Image | `--anchor` | Extracted Component |
|-------|-----------|-------------------|
| `registry.example.com/my-org/my-app/backend:v1.2.3` | `my-app` | `backend` |
| `registry.example.com/my-org/my-app/api/server:v2.0.0` | `my-app` | `api/server` |
| `gcr.io/my-project/my-app/worker:v1.0.0` | `my-app` | `worker` |

The extracted component name is then matched against the keys in your `--manifest` JSON to verify the correct version is deployed.

---

## Component Aliases

Use `--component-aliases` when a manifest component name differs from the container image name extracted by the anchor.

### Basic Alias (One-to-One)

If your manifest uses the key `foo` but the container image is named `bar-baz`:

```bash
kubernify \
  --anchor my-app \
  --manifest '{"foo": "v1.0.0", "backend": "v2.0.0"}' \
  --component-aliases '{"foo": "bar-baz"}'
```

This tells kubernify: when you see image `bar-baz`, map it to the manifest key `foo`.

### Shared Image Alias (Many-to-One)

Multiple manifest components can share the same container image name. kubernify disambiguates by matching each manifest key against the Kubernetes **workload name** (substring match).

For example, if both `ingest` and `process` use the same `shared-svc` image but run as separate workloads:

```bash
kubernify \
  --anchor my-app \
  --manifest '{"ingest": "v1.0.0", "process": "v1.0.0"}' \
  --component-aliases '{"ingest": "shared-svc", "process": "shared-svc"}' \
  --include-statefulsets
```

Given these workloads in the cluster:
- Deployment `my-app-123-ingest` → image `shared-svc:v1.0.0` → mapped to manifest key **`ingest`** (because `"ingest"` is a substring of `"my-app-123-ingest"`)
- StatefulSet `my-app-123-process-node` → image `shared-svc:v1.0.0` → mapped to manifest key **`process`** (because `"process"` is a substring of `"my-app-123-process-node"`)

**Resolution priority** when multiple candidates exist for the same image:

1. If only one candidate → use it directly
2. If multiple candidates → pick the one whose manifest key is a substring of the workload name
3. If no candidate matches the workload name → fall back to the raw image component name (if it's in the manifest)
4. If nothing matches → the workload is skipped (not mapped to any manifest key)

---

## Exit Codes

| Code | Meaning | Description |
|------|---------|-------------|
| `0` | **PASS** | All workloads match the manifest and pass stability audits |
| `1` | **FAIL** | One or more workloads have version mismatches, stability issues, or the verification timed out |

---

## Report Output

kubernify outputs a structured JSON report to stdout. The report contains:

- **`timestamp`** — ISO 8601 UTC timestamp of report generation
- **`context`** — Kubeconfig context name of the verified cluster
- **`namespace`** — Kubernetes namespace that was inspected
- **`status`** — Overall verification status (`PASS` or `FAIL`)
- **`summary`** — Aggregated counts (see below)
- **`details`** — Per-component verification details

### Summary Fields

| Field | Description |
|-------|-------------|
| `total_components` | Total number of components in the manifest |
| `passing_components` | Components in PASS state (version match and stable workloads) |
| `failed_components` | Total components in FAIL state (version mismatch or stability failure) |
| `missing_components` | Components in the manifest not found in the cluster |
| `missing_workloads` | Expected workloads not found during discovery |
| `version_mismatched_components` | Components where at least one workload has a version mismatch |
| `unstable_workloads` | Individual workloads with stability audit errors (pods not ready, convergence issues, etc.) |
| `skipped_containers` | Containers excluded from verification by skip patterns |

### Component Details

Each component in `details` contains:

- **`status`** — `PASS` or `FAIL`. A component is `FAIL` if it has version mismatches OR stability errors.
- **`errors`** — List of version-level error messages
- **`workloads`** — List of workloads with failures (only workloads with issues are included)

Each workload entry contains:

- **`name`** — Kubernetes workload name
- **`type`** — Workload type (Deployment, StatefulSet, DaemonSet, Job)
- **`container`** — Container name
- **`version_error`** — Version mismatch error (null if version matches)
- **`stability`** — Stability audit result with boolean checks and error list

### Example Output

```json
{
  "timestamp": "2025-01-15T10:30:00.000000+00:00",
  "context": "my-cluster-context",
  "namespace": "production",
  "status": "FAIL",
  "summary": {
    "total_components": 2,
    "passing_components": 1,
    "failed_components": 1,
    "missing_components": 0,
    "missing_workloads": 0,
    "version_mismatched_components": 0,
    "unstable_workloads": 1,
    "skipped_containers": 0
  },
  "details": {
    "frontend": {
      "status": "PASS",
      "errors": [],
      "workloads": []
    },
    "backend": {
      "status": "FAIL",
      "errors": [],
      "workloads": [
        {
          "name": "my-app-backend",
          "type": "Deployment",
          "container": "backend",
          "version_error": null,
          "stability": {
            "converged": true,
            "revision_consistent": true,
            "pods_healthy": false,
            "scheduling_complete": true,
            "job_complete": true,
            "errors": [
              "Pod my-app-backend-7f8b9c6d4-x2k9m is not Ready",
              "Deployment availability insufficient: 0/1 pods available (0 ready; tombstone pods excluded by Kubernetes controller)"
            ]
          }
        }
      ]
    }
  }
}
```

> **Note:** `version_mismatched_components` counts only components with version verification failures. `failed_components` counts all components in FAIL state, including those that passed version verification but have unstable workloads. A component's status is `FAIL` if **either** its version verification failed **or** any of its workloads have stability errors.

---

## Prerequisites

### Python

- Python **>= 3.10**

### For GKE Users

If using `--gke-project` for automatic GKE context resolution:

1. Install the [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
2. Install the GKE auth plugin:
   ```bash
   gcloud components install gke-gcloud-auth-plugin
   ```
3. Authenticate:
   ```bash
   gcloud auth login
   gcloud container clusters get-credentials CLUSTER_NAME --project PROJECT_ID
   ```

### RBAC Permissions

kubernify requires **read-only** access to workloads and pods. Apply the following RBAC configuration:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: kubernify-reader
  namespace: <namespace>
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
    verbs: ["get", "list"]
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: kubernify-reader-binding
  namespace: <namespace>
subjects:
  - kind: ServiceAccount
    name: kubernify
    namespace: <namespace>
roleRef:
  kind: Role
  name: kubernify-reader
  apiGroup: rbac.authorization.k8s.io
```

---

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and the PR process.

---

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
