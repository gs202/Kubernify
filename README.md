# kubernify

[![PyPI version](https://img.shields.io/pypi/v/kubernify?color=%2334D058&label=pypi%20package)](https://pypi.org/project/kubernify/)
[![Python versions](https://img.shields.io/pypi/pyversions/kubernify?color=%2334D058)](https://pypi.org/project/kubernify/)
[![CI](https://github.com/gs202/Kubernify/actions/workflows/ci.yml/badge.svg)](https://github.com/gs202/Kubernify/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

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

kubernify will connect to the cluster, discover all matching workloads, verify their image versions against the manifest, run stability audits, and exit with code `0` (pass), `1` (fail), or `2` (timeout).

---

## CLI Reference

```
kubernify [OPTIONS]
```

| Argument | Description | Default |
|----------|-------------|-----|
| `--context` | Kubeconfig context name. Mutually exclusive with `--gke-project`. | From kubeconfig |
| `--gke-project` | GCP project ID for GKE context resolution. Mutually exclusive with `--context`. |  |
| `--anchor` | **(required)** Image path anchor for component name extraction. See [How Image Anchor Works](#how-image-anchor-works). |  |
| `--manifest` | **(required)** JSON version manifest, e.g. `'{"backend": "v1.2.3"}'`. |  |
| `--namespace` | Kubernetes namespace to verify. | From kubeconfig context |
| `--required-workloads` | Comma-separated workload name patterns that must exist. |  |
| `--skip-containers` | Comma-separated container name patterns to skip during verification. |  |
| `--min-uptime` | Minimum pod uptime in seconds for stability checks. | `0` |
| `--restart-threshold` | Maximum allowed container restart count. | `3` |
| `--timeout` | Global timeout in seconds for the verification loop. | `300` |
| `--allow-zero-replicas` | Allow workloads with zero replicas to pass verification. | `false` |
| `--dry-run` | Snapshot check without waiting for convergence. | `false` |
| `--include-statefulsets` | Include StatefulSets in workload discovery. | `false` |
| `--include-daemonsets` | Include DaemonSets in workload discovery. | `false` |
| `--include-jobs` | Include Jobs and CronJobs in workload discovery. | `false` |

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
  --timeout 600 \
  --allow-zero-replicas
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


---

## Exit Codes

| Code | Meaning | Description |
|------|---------|-------------|
| `0` | **PASS** | All workloads match the manifest and pass stability audits |
| `1` | **FAIL** | One or more workloads have version mismatches or stability issues |
| `2` | **TIMEOUT** | Verification did not converge within the `--timeout` window |

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
