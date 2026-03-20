# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
