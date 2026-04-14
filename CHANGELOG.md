# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
