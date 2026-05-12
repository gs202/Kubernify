# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- New aggregate INFO log line `Discovery summary: <N> included, <N> skipped (--skip-containers workload-name match), <N> container-skipped (--skip-containers container-name match), <N> unparseable images, <N> not in manifest, <N> inspected` emitted after each cluster discovery cycle. The five buckets are mutually exclusive and sum to `inspected` (with `skipped` counting workloads filtered before inspection by workload-name match).
- New per-workload DEBUG log lines explaining why each workload was dropped from the verification scope: container-name skip, unparseable image, anchor-not-found in image path, or component-not-in-manifest. Deduplicated per `(workload, image)` so multi-pod workloads sharing the same image emit a single line.

### Changed

- Existing per-workload `Skipping inspection of workload <name> (matched skip pattern)` log demoted from INFO to DEBUG. Use the new aggregate `Discovery summary` line for an at-a-glance INFO view, or enable DEBUG logging to see per-workload skip/ignore decisions.
- Internal: `construct_component_map()` now returns a `ComponentMapResult` dataclass containing the component map and the three new exclusion-reason workload sets. No public CLI or report-schema impact.

## [1.2.0] - 2026-05-12

### Changed

- **Workload discovery performance**: ReplicaSets and Pods are now fetched once per discovery cycle using paginated `limit` / `_continue` requests, and per-workload lookups are served from in-memory maps. For a large namespace (e.g. 92 Deployments / 848 ReplicaSets), discovery drops from ~390+ scattered Kubernetes API calls per cycle to roughly 3 paginated namespace-wide reads (Workloads, ReplicaSets, Pods).
- The workload object loaded during discovery is now carried forward into the stability audit, removing redundant `read_namespaced_*` round trips per workload.
- Internal helpers `list_pods_by_deployment` / `list_pods_by_stateful_set` / `list_pods_by_daemon_set` collapsed into a single `list_pods_for_workload`. No public CLI or report-schema impact.

### Fixed

- Eliminates the HTTP 429 *Too Many Requests* and `urllib3` `IncompleteRead` errors that could surface against large namespaces during cluster discovery.

## [1.1.3] - 2026-04-29

### Fixed

- `--ignore-tombstone-pods` now filters evicted/failed pods from the **revision consistency check** in addition to the pod health check. Previously, evicted pods with stale ReplicaSet hashes caused false `revision_consistent: false` errors.
- `--ignore-tombstone-pods` now filters evicted/failed pods from **container image extraction** during version verification. Previously, evicted pods with old image versions caused false `version_error` reports in the component map.

## [1.1.2] - 2026-04-16

### Added

- `--output-file` CLI flag to save the JSON verification report to a file. The report is always printed to stdout; when `--output-file` is provided, it is additionally written to the specified path. Parent directories are created automatically if they don't exist.

## [1.1.1] - 2026-04-16

### Fixed

- Stability errors (e.g. `"Pod ... is terminating"`) are now surfaced in the component-level `errors` list in the verification report. Previously, these errors were only embedded inside each workload's `stability.errors` array but never propagated to the parent component's `errors`, making them invisible at the component summary level.

## [1.1.0] - 2026-04-15

### Changed

- **BREAKING:** Removed `TIMEOUT` from `VerificationStatus` enum. Timeout now produces `FAIL` (exit code `1`) instead of `TIMEOUT` (exit code `2`). This simplifies the exit code contract to `0` (pass) / `1` (fail).

### Added

- `passing_components` counter in report summary — counts components in PASS state (version match + stable workloads). The summary field order is now: `total_components` → `passing_components` → `failed_components` → `missing_components` → ...
- Stability flags documentation in README — added a table explaining each stability audit flag (`converged`, `revision_consistent`, `pods_healthy`, `scheduling_complete`, `job_complete`, `errors`)

## [1.0.7] - 2026-04-14

### Fixed

- `--allow-zero-replicas-for` now uses **substring matching** against workload names, consistent with `--skip-containers` and `--required-workloads`. Previously, exact matching caused the flag to silently fail when users passed short workload names (e.g. `my-worker`) that didn't match the fully-qualified Kubernetes workload name (e.g. `ns-123-my-worker`).

## [1.0.6] - 2026-04-13

### Fixed

- `--component-aliases` now supports multiple manifest keys aliasing to the same container image name. Previously, this raised `ValueError: Duplicate component alias`. Disambiguation is performed by matching each manifest key against the Kubernetes workload name (substring match).

### Added

- New `_resolve_component()` function for workload-name-based disambiguation when multiple manifest components share the same container image
- "Component Aliases" section in README documenting basic and shared-image alias usage

## [1.0.5] - 2026-03-30

### Added

- `--ignore-tombstone-pods` CLI flag to exclude Failed/Succeeded pods from per-pod health checks
- `StabilityAuditor.check_deployment_availability()` method to verify `available_replicas >= spec.replicas` for Deployments
- Deployment availability check always runs regardless of `--ignore-tombstone-pods` flag

## [1.0.4] - 2026-03-22

### Changed

- Expanded CLI argument descriptions in README with detailed behavioral documentation
- Added missing `--component-aliases` argument to CLI reference table
- Clarified substring vs exact matching semantics for `--required-workloads`, `--skip-containers`, and `--allow-zero-replicas-for`

## [1.0.3] - 2025-03-20

### Added

- `--allow-zero-replicas-for` CLI parameter to explicitly permit zero-replica workloads during verification

### Changed

- CI: use `pre-commit/action` for cached hook environments
- CI: use `pytest-xdist` for parallel test execution
- CI: switch Dependabot schedule from weekly to monthly

## [1.0.2] - 2025-02-01

### Added

- Initial public release of kubernify
- CLI tool for verifying Kubernetes deployments against a version manifest
- Deep stability auditing: convergence, revision consistency, pod health
- Support for Deployments, StatefulSets, DaemonSets, Jobs, and CronJobs
- Retry-until-converged verification loop with configurable timeout
- Repository-relative image parsing with configurable anchor
- Zero-replica workload awareness (version from PodSpec template)
- Structured JSON report output for CI/CD integration
- Dual context mode: direct kubeconfig context or GKE project ID resolution
- In-cluster auto-detection for running inside Kubernetes pods
- Configurable skip patterns for containers and workloads
- Required workload existence verification
- Dry-run mode for snapshot checks without waiting
- Python library API for programmatic usage
