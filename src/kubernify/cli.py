"""Kubernify — Kubernetes deployment version verification tool.

Verifies that deployed workloads in a Kubernetes cluster match a given version
manifest.  Checks for:

1. Existence of expected workloads
2. Version consistency
3. Pod stability (Ready, not terminating, restart count)
4. Controller convergence
5. Revision consistency
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone

from .image_parser import parse_image_reference
from .kubernetes_controller import KubernetesController
from .models import (
    DEFAULT_RESTART_THRESHOLD,
    DEFAULT_TIMEOUT_SECONDS,
    RETRY_INTERVAL_SECONDS,
    ComponentMapEntry,
    ComponentReport,
    ComponentVerificationResult,
    ContainerType,
    ImageReference,
    PodInfo,
    ReportSummary,
    StabilityAuditResult,
    VerificationReport,
    VerificationResult,
    VerificationStatus,
    VersionVerificationResults,
    WorkloadInspectionResult,
    WorkloadReport,
)
from .stability_audit import StabilityAuditor
from .workload_discovery import WorkloadDiscovery

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configure logging for CLI usage. Only called from main()."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s : %(name)-13s : %(levelname)s :: %(message)s",
    )


def _get_current_namespace() -> str:
    """Read active namespace from kubeconfig or in-cluster service account."""
    import kubernetes.config

    # 1. Try kubeconfig (local dev)
    try:
        _, active_context = kubernetes.config.list_kube_config_contexts()
        if ns := active_context.get("context", {}).get("namespace"):
            return ns
    except Exception:  # noqa: S110
        pass

    # 2. Try in-cluster service account (running in Pod)
    try:
        with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as f:
            return f.read().strip()
    except FileNotFoundError:
        pass

    # 3. Fallback
    return "default"


# ---------------------------------------------------------------------------
# Container extraction helpers
# ---------------------------------------------------------------------------


def _containers_from_spec(
    init_containers: list | None,
    app_containers: list | None,
    pod_info: PodInfo | None,
) -> list[tuple[str, ContainerType, PodInfo | None]]:
    """Yield ``(image, container_type, pod_info)`` tuples from container lists.

    Consolidates the duplicated init/app iteration that was previously
    repeated for both running pods and zero-replica pod-spec templates.

    Args:
        init_containers: Init containers (may be ``None``).
        app_containers: Application containers (may be ``None``).
        pod_info: Associated pod metadata, or ``None`` for spec-only extraction.

    Returns:
        List of ``(image_string, ContainerType, PodInfo | None)`` tuples.
    """
    results: list[tuple[str, ContainerType, PodInfo | None]] = []
    for container in init_containers or []:
        results.append((container.image, ContainerType.INIT, pod_info))
    for container in app_containers or []:
        results.append((container.image, ContainerType.APP, pod_info))
    return results


def _extract_containers(workload: WorkloadInspectionResult) -> list[tuple[str, ContainerType, PodInfo | None]]:
    """Extract container image/type/pod tuples from a workload.

    When running pods exist, their containers are used directly.  When no pods
    exist (zero-replica workloads), the function falls back to the pod spec
    template so that version verification can still be performed.

    Args:
        workload: A Kubernetes workload inspection result containing pods and pod_spec.

    Returns:
        List of ``(image_string, container_type, pod_info)`` tuples.
    """
    if pods := workload.pods:
        results: list[tuple[str, ContainerType, PodInfo | None]] = []
        for pod in pods:
            pod_info = PodInfo(
                name=pod.metadata.name,
                ip=pod.status.pod_ip,
                node=pod.spec.node_name,
                start_time=str(pod.status.start_time),
                phase=pod.status.phase,
            )
            results.extend(_containers_from_spec(pod.spec.init_containers, pod.spec.containers, pod_info))
        return results

    if pod_spec := workload.pod_spec:
        logger.info(f"Workload '{workload.name}' has 0 pods — using pod spec template for version extraction")
        return _containers_from_spec(pod_spec.init_containers, pod_spec.containers, None)

    return []


# ---------------------------------------------------------------------------
# Component map construction
# ---------------------------------------------------------------------------


def _build_or_update_entry(
    component_map: dict[str, list[ComponentMapEntry]],
    component: str,
    workload_name: str,
    workload_type: str,
    parsed: ImageReference,
    container_type: ContainerType,
    pod_info: PodInfo | None,
) -> None:
    """Insert a new ``ComponentMapEntry`` or append a pod to an existing one.

    Groups entries by ``(workload_name, workload_type, component, version)``
    so that multiple pods running the same container image are collected under
    a single entry.

    Args:
        component_map: Mutable mapping being built up.
        component: Parsed component name (manifest key).
        workload_name: Name of the owning workload.
        workload_type: Kind of the owning workload (e.g. ``Deployment``).
        parsed: Parsed ``ImageReference`` containing component and version.
        container_type: ``ContainerType`` enum value (``INIT`` or ``APP``).
        pod_info: Pod metadata, or ``None`` for zero-replica workloads.
    """
    existing_entry = next(
        (
            entry
            for entry in component_map[component]
            if entry.workload_name == workload_name
            and entry.workload_type == workload_type
            and entry.container_name == parsed.component
            and entry.actual_version == parsed.version
        ),
        None,
    )

    if existing_entry:
        if pod_info:
            existing_entry.pods.append(pod_info)
    else:
        component_map[component].append(
            ComponentMapEntry(
                workload_name=workload_name,
                workload_type=workload_type,
                container_name=parsed.component,
                container_type=container_type,
                actual_version=parsed.version,
                pods=[pod_info] if pod_info else [],
            )
        )


def _should_skip(skip_patterns: list[str], container_name: str, workload_name: str) -> str | None:
    """Check if a workload/container should be skipped based on skip patterns.

    Matches each pattern against both the container name and the workload name.

    Args:
        skip_patterns: List of substring patterns to match.
        container_name: Kubernetes container name (e.g. ``"backend"``).
        workload_name: Kubernetes workload name.

    Returns:
        The first matching pattern, or ``None`` if nothing matched.
    """
    for pattern in skip_patterns:
        if pattern in container_name or pattern in workload_name:
            return pattern
    return None


def construct_component_map(
    workloads: list[WorkloadInspectionResult],
    manifest: dict[str, str],
    repository_anchor: str,
    skip_containers: list[str] | None = None,
) -> dict[str, list[ComponentMapEntry]]:
    """Construct a map of components to their found workloads and versions.

    Always extracts containers from both running pods and zero-replica pod spec
    templates so that all manifest components can be verified.

    Args:
        workloads: Discovered Kubernetes workload objects.
        manifest: Version manifest mapping component names to expected versions.
        repository_anchor: Repository name used as the anchor for image parsing.
        skip_containers: Optional list of patterns; workloads whose container name
            or workload name matches any pattern are excluded from the map entirely.

    Returns:
        Dict mapping component names to lists of ``ComponentMapEntry`` instances.
    """
    component_map: dict[str, list[ComponentMapEntry]] = defaultdict(list)
    skip_patterns = skip_containers or []

    for workload in workloads:
        for image, container_type, pod_info in _extract_containers(workload=workload):
            try:
                parsed = parse_image_reference(image=image, repository_anchor=repository_anchor)
            except ValueError:
                continue

            if parsed.component not in manifest:
                continue

            if _should_skip(skip_patterns=skip_patterns, container_name=parsed.component, workload_name=workload.name):
                continue

            _build_or_update_entry(
                component_map=component_map,
                component=parsed.component,
                workload_name=workload.name,
                workload_type=workload.type,
                parsed=parsed,
                container_type=container_type,
                pod_info=pod_info,
            )

    return dict(component_map)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_manifest(manifest: dict[str, str], component_map: dict[str, list[ComponentMapEntry]]) -> list[str]:
    """Validate that all components in the manifest exist in the cluster.

    Args:
        manifest: Version manifest mapping component names to expected versions.
        component_map: Discovered component map from ``construct_component_map``.

    Returns:
        List of error messages for missing components.
    """
    return [f"Component '{c}' not found in cluster" for c in manifest if c not in component_map]


def verify_required_workloads(
    required_workloads: list[str],
    discovered_workloads: list[WorkloadInspectionResult],
) -> list[str]:
    """Verify that specific workloads exist in the discovered workloads.

    Uses partial matching — checks if the required workload name is contained
    in any discovered workload name.  For example, ``'frontend'`` will match
    ``'my-app-frontend'``.

    Args:
        required_workloads: List of required workload name patterns.
        discovered_workloads: List of discovered workload inspection results.

    Returns:
        List of error messages for missing required workloads.
    """
    found_names = {w.name for w in discovered_workloads}
    return [
        f"Required workload '{required}' not found"
        for required in required_workloads
        if not any(required in name for name in found_names)
    ]


# ---------------------------------------------------------------------------
# Version verification
# ---------------------------------------------------------------------------


def _verify_component_entry(
    entry: ComponentMapEntry,
    expected_version: str,
    allow_zero_replicas: bool,
) -> VerificationResult:
    """Verify a single workload entry against expected version and replica count.

    Note: skip-pattern filtering is already performed in ``construct_component_map``,
    so entries reaching this function are guaranteed to not match any skip pattern.

    Args:
        entry: Workload entry containing container and version information.
        expected_version: Expected version string.
        allow_zero_replicas: When ``True``, do not fail workloads with 0 running pods.

    Returns:
        ``VerificationResult`` containing verification status.
    """
    if not entry.pods and not allow_zero_replicas:
        return VerificationResult(
            workload=entry.workload_name,
            type=entry.workload_type,
            container=entry.container_name,
            status=VerificationStatus.FAIL,
            error=f"Workload has 0 running pods (version from pod spec: {entry.actual_version})",
        )

    if entry.actual_version != expected_version:
        return VerificationResult(
            workload=entry.workload_name,
            type=entry.workload_type,
            container=entry.container_name,
            status=VerificationStatus.FAIL,
            error=f"Version mismatch: expected {expected_version}, found {entry.actual_version}",
        )

    return VerificationResult(
        workload=entry.workload_name,
        type=entry.workload_type,
        container=entry.container_name,
        status=VerificationStatus.PASS,
    )


def verify_versions(
    manifest: dict[str, str],
    component_map: dict[str, list[ComponentMapEntry]],
    allow_zero_replicas: bool = False,
) -> VersionVerificationResults:
    """Verify versions for all components.

    Args:
        manifest: Dict mapping component names to expected version strings.
        component_map: Dict mapping component names to their discovered workloads.
        allow_zero_replicas: When ``True``, do not fail workloads with 0 running pods.

    Returns:
        A ``VersionVerificationResults`` instance with per-component details.
    """
    results = VersionVerificationResults()

    for component, expected_version in manifest.items():
        comp_result = ComponentVerificationResult()

        if component not in component_map:
            msg = f"Component '{component}' not found"
            comp_result.status = VerificationStatus.FAIL.value
            comp_result.errors.append(msg)
            results.errors.append(msg)
            results.components[component] = comp_result
            continue

        for entry in component_map[component]:
            entry_status = _verify_component_entry(
                entry=entry,
                expected_version=expected_version,
                allow_zero_replicas=allow_zero_replicas,
            )
            comp_result.workloads.append(entry_status)
            if entry_status.status == VerificationStatus.FAIL:
                comp_result.status = VerificationStatus.FAIL.value
                comp_result.errors.append(f"{entry.workload_name}: {entry_status.error}")
                results.errors.append(f"[{component}] {entry.workload_name}: {entry_status.error}")

        results.components[component] = comp_result

    return results


def load_manifest(manifest: str) -> dict[str, str]:
    """Parse a JSON string manifest into a dict.

    Args:
        manifest: JSON string containing the version manifest.

    Returns:
        Parsed dict mapping component names to expected versions.

    Raises:
        ValueError: If the manifest is empty or not valid JSON.
    """
    if not manifest:
        raise ValueError("Manifest JSON string must not be empty")
    try:
        return json.loads(manifest)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Manifest is not valid JSON: {manifest}") from exc


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    overall_status: VerificationStatus,
    verification_results: VersionVerificationResults,
    stability_results: dict[str, StabilityAuditResult],
    missing_components: list[str],
    missing_workloads: list[str],
    context: str,
    namespace: str,
    skipped_workload_names: list[str] | None = None,
) -> VerificationReport:
    """Generate the final verification report.

    Args:
        overall_status: Overall verification status (PASS / FAIL / TIMEOUT).
        verification_results: Structured results produced by ``verify_versions``.
        stability_results: Mapping of workload keys to their stability audit results.
        missing_components: List of component-level error messages.
        missing_workloads: List of workload-level error messages.
        context: Kubeconfig context name or identifier.
        namespace: Kubernetes namespace that was inspected.
        skipped_workload_names: Names of workloads skipped during discovery.

    Returns:
        A fully populated ``VerificationReport`` instance.
    """
    summary = ReportSummary(
        total_components=len(verification_results.components),
        missing_components=len(missing_components),
        missing_workloads=len(missing_workloads),
        skipped_containers=len(skipped_workload_names) if skipped_workload_names else 0,
    )

    report = VerificationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        context=context,
        namespace=namespace,
        status=overall_status,
        summary=summary,
    )

    for component, comp_result in verification_results.components.items():
        if comp_result.status == VerificationStatus.FAIL.value:
            summary.failed_components += 1

        comp_report = ComponentReport(
            status=comp_result.status,
            errors=comp_result.errors,
        )

        for w_entry in comp_result.workloads:
            w_key = f"{w_entry.type}/{w_entry.workload}"
            is_skipped = w_entry.status == VerificationStatus.SKIPPED

            if is_skipped:
                summary.skipped_containers += 1
                continue

            stability_entry = stability_results.get(w_key)
            stability_dict = asdict(stability_entry) if stability_entry else {}

            w_report = WorkloadReport(
                name=w_entry.workload,
                type=w_entry.type,
                container=w_entry.container,
                version_error=w_entry.error,
                stability=stability_dict,
            )

            has_stability_errors = bool(stability_dict.get("errors"))
            has_version_failure = w_entry.status == VerificationStatus.FAIL

            if has_stability_errors:
                summary.unstable_workloads += 1

            # Only include workloads with failures (version or stability)
            if has_version_failure or has_stability_errors:
                comp_report.workloads.append(w_report)

        report.details[component] = comp_report

    if missing_components:
        report.details["_missing_components"] = missing_components
    if missing_workloads:
        report.details["_missing_workloads"] = missing_workloads

    return report


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        args: Optional list of argument strings (defaults to ``sys.argv``).

    Returns:
        Parsed ``argparse.Namespace``.
    """
    parser = argparse.ArgumentParser(
        description="Kubernify — Verify Kubernetes deployments match a version manifest",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    context_group = parser.add_mutually_exclusive_group()
    context_group.add_argument(
        "--context",
        help="Kubeconfig context name to use for cluster connection",
    )
    context_group.add_argument(
        "--gke-project",
        help="GCP project ID — resolves the kube context from GKE-style context names",
    )

    parser.add_argument(
        "--manifest",
        required=True,
        help='JSON string containing the version manifest (e.g. \'{"backend": "v1.2.3"}\')',
    )
    parser.add_argument(
        "--namespace",
        default=_get_current_namespace(),
        help="Kubernetes namespace (default: from kubeconfig or 'default')",
    )
    parser.add_argument(
        "--required-workloads",
        help="Comma-separated list of workload names that MUST exist (e.g., 'frontend, api')",
    )
    parser.add_argument(
        "--skip-containers",
        help=(
            "Comma-separated list of patterns to skip verification for; "
            "matched against both container names and workload names"
        ),
    )
    parser.add_argument("--min-uptime", type=int, default=0, help="Minimum pod uptime in seconds")
    parser.add_argument(
        "--restart-threshold",
        type=int,
        default=DEFAULT_RESTART_THRESHOLD,
        help="Maximum acceptable restart count per container",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Global timeout in seconds")
    parser.add_argument(
        "--allow-zero-replicas",
        action="store_true",
        help="Allow workloads with 0 replicas to pass verification without flagging as a failure",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate manifest against current cluster state without waiting",
    )
    parser.add_argument(
        "--anchor",
        required=True,
        help=(
            "The image path segment used as the anchor point for component name extraction. "
            "Example: for image 'registry.example.com/my-org/my-app/backend:v1.0', "
            "using --anchor my-app extracts component name 'backend'."
        ),
    )
    parser.add_argument(
        "--include-statefulsets",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Include StatefulSets",
    )
    parser.add_argument(
        "--include-daemonsets",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Include DaemonSets",
    )
    parser.add_argument(
        "--include-jobs",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Include Jobs and CronJobs",
    )
    return parser.parse_args(args)


# ---------------------------------------------------------------------------
# Stability audit orchestration
# ---------------------------------------------------------------------------


def _parse_comma_list(raw: str | None) -> list[str]:
    """Parse a comma-separated string into a stripped list, or return empty list.

    Args:
        raw: Raw comma-separated string, or ``None``.

    Returns:
        List of stripped, non-empty strings.
    """
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _perform_stability_audit(
    auditor: StabilityAuditor,
    component_map: dict[str, list[ComponentMapEntry]],
    discovered_items: list[WorkloadInspectionResult],
    discovered_map: dict[str, WorkloadInspectionResult],
    required_workloads: list[str],
    skip_containers: list[str],
    restart_threshold: int,
    min_uptime: int,
) -> tuple[dict[str, StabilityAuditResult], bool]:
    """Perform stability audit on relevant workloads.

    Args:
        auditor: ``StabilityAuditor`` instance.
        component_map: Map of components to their workloads.
        discovered_items: List of discovered workload items.
        discovered_map: Map of workload keys to inspection results.
        required_workloads: List of required workload names.
        skip_containers: List of container name patterns to skip.
        restart_threshold: Maximum acceptable restart count per container.
        min_uptime: Minimum pod uptime in seconds.

    Returns:
        Tuple of ``(stability_results, all_stable)`` where ``stability_results``
        maps workload keys to ``StabilityAuditResult`` and ``all_stable`` is
        ``True`` when every audited workload has zero errors.
    """
    stability_results: dict[str, StabilityAuditResult] = {}
    all_stable = True
    workloads_to_audit: set[str] = set()
    workloads_to_skip: set[str] = set()

    # Build sets from component map entries
    for comp_entries in component_map.values():
        for entry in comp_entries:
            w_key = f"{entry.workload_type}/{entry.workload_name}"
            if _should_skip(
                skip_patterns=skip_containers,
                container_name=entry.container_name,
                workload_name=entry.workload_name,
            ):
                workloads_to_skip.add(w_key)
            else:
                workloads_to_audit.add(w_key)

    # Add required workloads that match discovered items
    for item in discovered_items:
        w_key = f"{item.type}/{item.name}"
        if _should_skip(skip_patterns=skip_containers, container_name="", workload_name=item.name):
            workloads_to_skip.add(w_key)
            continue
        for required in required_workloads:
            if required in item.name and w_key not in workloads_to_skip:
                workloads_to_audit.add(w_key)
                break

    for w_key in workloads_to_audit:
        if w_key not in discovered_map:
            continue
        audit_res = auditor.audit_workload(
            workload_info=discovered_map[w_key],
            restart_threshold=restart_threshold,
            min_uptime_sec=min_uptime,
        )
        stability_results[w_key] = audit_res
        if audit_res.errors:
            all_stable = False

    return stability_results, all_stable


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------


def run_verification(args: argparse.Namespace) -> int:
    """Main execution flow.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process exit code (0 = PASS, 1 = FAIL, 2 = TIMEOUT).
    """
    start_time = time.time()

    try:
        manifest = load_manifest(manifest=args.manifest)

        required_workloads = _parse_comma_list(args.required_workloads)
        if required_workloads:
            logger.info(f"Required workloads: {required_workloads}")

        skip_containers = _parse_comma_list(args.skip_containers)
        if skip_containers:
            logger.info(f"Skipping verification for patterns (container/workload name): {skip_containers}")

        k8s_controller = KubernetesController(
            context=args.context,
            gke_project=args.gke_project,
        )
        discovery = WorkloadDiscovery(
            k8s_controller=k8s_controller,
            include_statefulsets=args.include_statefulsets,
            include_daemonsets=args.include_daemonsets,
            include_jobs=args.include_jobs,
        )
        auditor = StabilityAuditor(k8s_controller=k8s_controller)
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        return 1

    overall_status = VerificationStatus.PASS
    verification_results = VersionVerificationResults()
    stability_results: dict[str, StabilityAuditResult] = {}
    missing_components: list[str] = []
    missing_workloads: list[str] = []
    skipped_workload_names: list[str] = []

    report_context = args.context or args.gke_project or "in-cluster"

    while True:
        if time.time() - start_time > args.timeout:
            logger.error("Global timeout reached")
            overall_status = VerificationStatus.TIMEOUT
            break

        logger.info("Discovering cluster state...")
        try:
            discovered_items, skipped_workload_names = discovery.discover_cluster_state(
                namespace=args.namespace,
                skip_patterns=skip_containers,
            )
            discovered_map = {f"{item.type}/{item.name}": item for item in discovered_items}
            component_map = construct_component_map(
                workloads=discovered_items,
                manifest=manifest,
                repository_anchor=args.anchor,
                skip_containers=skip_containers,
            )
        except Exception as e:
            logger.error(f"Discovery failed: {e}")
            if args.dry_run:
                return 1
            time.sleep(RETRY_INTERVAL_SECONDS)
            continue

        missing_components = validate_manifest(manifest=manifest, component_map=component_map)
        missing_workloads = verify_required_workloads(
            required_workloads=required_workloads,
            discovered_workloads=discovered_items,
        )
        verification_results = verify_versions(
            manifest=manifest,
            component_map=component_map,
            allow_zero_replicas=args.allow_zero_replicas,
        )

        stability_results, all_stable = _perform_stability_audit(
            auditor=auditor,
            component_map=component_map,
            discovered_items=discovered_items,
            discovered_map=discovered_map,
            required_workloads=required_workloads,
            skip_containers=skip_containers,
            restart_threshold=args.restart_threshold,
            min_uptime=args.min_uptime,
        )

        has_errors = bool(verification_results.errors) or bool(missing_components) or bool(missing_workloads)

        if args.dry_run:
            if has_errors or not all_stable:
                overall_status = VerificationStatus.FAIL
            break

        if not has_errors and all_stable:
            logger.info("Verification and stability checks passed!")
            overall_status = VerificationStatus.PASS
            break

        logger.info("Waiting for convergence/stability...")
        time.sleep(RETRY_INTERVAL_SECONDS)

    try:
        report = generate_report(
            overall_status=overall_status,
            verification_results=verification_results,
            stability_results=stability_results,
            missing_components=missing_components,
            missing_workloads=missing_workloads,
            context=report_context,
            namespace=args.namespace,
            skipped_workload_names=skipped_workload_names,
        )
        print(json.dumps(report.to_dict(), indent=2))
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        return 1

    return overall_status.exit_code


def main() -> None:
    """CLI entry point for kubernify."""
    _setup_logging()
    try:
        parsed_args = parse_args()
        sys.exit(run_verification(args=parsed_args))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
