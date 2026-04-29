"""Unit tests for version verification functions in kubernify.cli."""

from __future__ import annotations

from unittest.mock import MagicMock

from kubernetes.client import V1Container, V1ObjectMeta, V1Pod, V1PodSpec, V1PodStatus

from kubernify.cli import (
    _extract_containers,
    construct_component_map,
    validate_manifest,
    verify_required_workloads,
    verify_versions,
)
from kubernify.models import (
    ComponentMapEntry,
    ContainerType,
    VerificationStatus,
    WorkloadInspectionResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workload_inspection(
    *,
    name: str,
    workload_type: str = "Deployment",
    image: str,
    namespace: str = "default",
) -> WorkloadInspectionResult:
    """Create a ``WorkloadInspectionResult`` with a single running pod.

    Args:
        name: Workload name.
        workload_type: Kubernetes workload kind.
        image: Container image reference string.
        namespace: Kubernetes namespace.

    Returns:
        A ``WorkloadInspectionResult`` with one pod running the given image.
    """
    pod = V1Pod(
        metadata=V1ObjectMeta(name=f"{name}-pod-xyz", namespace=namespace),
        spec=V1PodSpec(
            node_name="node-1",
            containers=[V1Container(name=name.split("-")[0], image=image)],
            init_containers=None,
        ),
        status=V1PodStatus(
            phase="Running",
            pod_ip="10.0.0.1",
            start_time="2025-01-01T00:00:00Z",
        ),
    )
    return WorkloadInspectionResult(
        name=name,
        type=workload_type,
        namespace=namespace,
        pods=[pod],
        pod_spec=pod.spec,
    )


def _make_zero_replica_workload(
    *,
    name: str,
    workload_type: str = "Deployment",
    image: str,
    namespace: str = "default",
) -> WorkloadInspectionResult:
    """Create a ``WorkloadInspectionResult`` with zero running pods (spec-only).

    Args:
        name: Workload name.
        workload_type: Kubernetes workload kind.
        image: Container image reference string.
        namespace: Kubernetes namespace.

    Returns:
        A ``WorkloadInspectionResult`` with no pods but a pod spec template.
    """
    pod_spec = V1PodSpec(
        containers=[V1Container(name=name.split("-")[0], image=image)],
        init_containers=None,
    )
    return WorkloadInspectionResult(
        name=name,
        type=workload_type,
        namespace=namespace,
        pods=[],
        pod_spec=pod_spec,
    )


# ---------------------------------------------------------------------------
# construct_component_map tests
# ---------------------------------------------------------------------------


class TestConstructComponentMap:
    """Tests for ``construct_component_map``."""

    def test_construct_component_map_basic(self) -> None:
        """Verify component map construction with mock workloads."""
        manifest = {"backend": "v1.2.3", "frontend": "v1.2.4"}
        workloads = [
            _make_workload_inspection(
                name="backend-deployment",
                image="registry.example.com/my-org/my-app/backend:v1.2.3",
            ),
            _make_workload_inspection(
                name="frontend-deployment",
                image="registry.example.com/my-org/my-app/frontend:v1.2.4",
            ),
        ]

        result = construct_component_map(
            workloads=workloads,
            manifest=manifest,
            repository_anchor="my-app",
        )

        assert "backend" in result
        assert "frontend" in result
        assert result["backend"][0].actual_version == "v1.2.3"
        assert result["frontend"][0].actual_version == "v1.2.4"

    def test_construct_component_map_skip_patterns(self) -> None:
        """Verify skip patterns exclude workloads from the component map."""
        manifest = {"backend": "v1.2.3", "frontend": "v1.2.4"}
        workloads = [
            _make_workload_inspection(
                name="backend-deployment",
                image="registry.example.com/my-org/my-app/backend:v1.2.3",
            ),
            _make_workload_inspection(
                name="frontend-deployment",
                image="registry.example.com/my-org/my-app/frontend:v1.2.4",
            ),
        ]

        result = construct_component_map(
            workloads=workloads,
            manifest=manifest,
            repository_anchor="my-app",
            skip_containers=["frontend"],
        )

        assert "backend" in result
        assert "frontend" not in result

    def test_construct_component_map_no_anchor_match(self) -> None:
        """Verify workloads without anchor match are skipped when not in manifest."""
        manifest = {"backend": "v1.2.3"}
        workloads = [
            _make_workload_inspection(
                name="redis-deployment",
                image="redis:7.0",
            ),
        ]

        result = construct_component_map(
            workloads=workloads,
            manifest=manifest,
            repository_anchor="my-app",
        )

        # redis is not in the manifest, so it should not appear
        assert "redis" not in result

    def test_construct_component_map_with_alias(self) -> None:
        """Verify alias remaps image name to manifest component name."""
        manifest = {"foo": "v1.0.0"}
        workloads = [
            _make_workload_inspection(
                name="foo-deployment",
                image="registry.example.com/my-org/my-app/bar-baz:v1.0.0",
            ),
        ]

        result = construct_component_map(
            workloads=workloads,
            manifest=manifest,
            repository_anchor="my-app",
            reverse_aliases={"bar-baz": ["foo"]},
        )

        assert "foo" in result
        assert result["foo"][0].actual_version == "v1.0.0"

    def test_construct_component_map_alias_does_not_affect_non_aliased(self) -> None:
        """Verify non-aliased components still work alongside aliases."""
        manifest = {"backend": "v1.2.3", "foo": "v1.0.0"}
        workloads = [
            _make_workload_inspection(
                name="backend-deployment",
                image="registry.example.com/my-org/my-app/backend:v1.2.3",
            ),
            _make_workload_inspection(
                name="foo-deployment",
                image="registry.example.com/my-org/my-app/bar-baz:v1.0.0",
            ),
        ]

        result = construct_component_map(
            workloads=workloads,
            manifest=manifest,
            repository_anchor="my-app",
            reverse_aliases={"bar-baz": ["foo"]},
        )

        assert "backend" in result
        assert "foo" in result
        assert result["backend"][0].actual_version == "v1.2.3"
        assert result["foo"][0].actual_version == "v1.0.0"

    def test_construct_component_map_without_alias_misses_component(self) -> None:
        """Verify that without alias, mismatched image name is not mapped."""
        manifest = {"foo": "v1.0.0"}
        workloads = [
            _make_workload_inspection(
                name="foo-deployment",
                image="registry.example.com/my-org/my-app/bar-baz:v1.0.0",
            ),
        ]

        result = construct_component_map(
            workloads=workloads,
            manifest=manifest,
            repository_anchor="my-app",
        )

        # Without alias, bar-baz != foo, so it's not in the map
        assert "foo" not in result

    def test_construct_component_map_multi_alias_disambiguation(self) -> None:
        """Verify multiple manifest keys sharing the same image are disambiguated by workload name."""
        manifest = {"foo": "v1.0.0", "bar": "v1.0.0"}
        workloads = [
            _make_workload_inspection(
                name="my-app-123-foo",
                image="registry.example.com/my-org/my-app/shared-svc:v1.0.0",
            ),
            _make_workload_inspection(
                name="my-app-123-bar-node",
                workload_type="StatefulSet",
                image="registry.example.com/my-org/my-app/shared-svc:v1.0.0",
            ),
        ]

        result = construct_component_map(
            workloads=workloads,
            manifest=manifest,
            repository_anchor="my-app",
            reverse_aliases={"shared-svc": ["foo", "bar"]},
        )

        assert "foo" in result
        assert "bar" in result
        assert result["foo"][0].workload_name == "my-app-123-foo"
        assert result["bar"][0].workload_name == "my-app-123-bar-node"

    def test_construct_component_map_multi_alias_no_workload_match_falls_back(self) -> None:
        """Verify multi-alias falls back to raw component name when no workload name matches."""
        manifest = {"shared-svc": "v1.0.0", "foo": "v1.0.0"}
        workloads = [
            _make_workload_inspection(
                name="my-app-123-unknown-service",
                image="registry.example.com/my-org/my-app/shared-svc:v1.0.0",
            ),
        ]

        result = construct_component_map(
            workloads=workloads,
            manifest=manifest,
            repository_anchor="my-app",
            reverse_aliases={"shared-svc": ["foo", "bar"]},
        )

        # Neither "foo" nor "bar" is in the workload name, but
        # "shared-svc" IS in the manifest, so it falls back to that.
        assert "shared-svc" in result
        assert result["shared-svc"][0].workload_name == "my-app-123-unknown-service"


# ---------------------------------------------------------------------------
# verify_versions tests
# ---------------------------------------------------------------------------


class TestVerifyVersions:
    """Tests for ``verify_versions``."""

    def test_verify_versions_all_match(self) -> None:
        """Verify all versions match returns no errors."""
        manifest = {"backend": "v1.2.3"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="backend-deployment",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[MagicMock()],
                ),
            ],
        }

        result = verify_versions(manifest=manifest, component_map=component_map)

        assert result.errors == []
        assert result.components["backend"].status == VerificationStatus.PASS.value

    def test_verify_versions_mismatch(self) -> None:
        """Verify version mismatch returns errors."""
        manifest = {"backend": "v2.0.0"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="backend-deployment",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[MagicMock()],
                ),
            ],
        }

        result = verify_versions(manifest=manifest, component_map=component_map)

        assert len(result.errors) >= 1
        assert any("mismatch" in e.lower() for e in result.errors)

    def test_verify_versions_missing_component(self) -> None:
        """Verify component not in map returns error."""
        manifest = {"backend": "v1.2.3", "missing-svc": "v1.0.0"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="backend-deployment",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[MagicMock()],
                ),
            ],
        }

        result = verify_versions(manifest=manifest, component_map=component_map)

        assert any("missing-svc" in e for e in result.errors)

    def test_verify_versions_zero_replicas_allowed(self) -> None:
        """Verify zero-replica workload passes with allow_zero_replicas=True."""
        manifest = {"backend": "v1.2.3"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="backend-deployment",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[],  # zero replicas
                ),
            ],
        }

        result = verify_versions(
            manifest=manifest,
            component_map=component_map,
            allow_zero_replicas=True,
        )

        assert result.errors == []

    def test_verify_versions_zero_replicas_not_allowed(self) -> None:
        """Verify zero-replica workload fails without allow_zero_replicas flag."""
        manifest = {"backend": "v1.2.3"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="backend-deployment",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[],  # zero replicas
                ),
            ],
        }

        result = verify_versions(
            manifest=manifest,
            component_map=component_map,
            allow_zero_replicas=False,
        )

        assert len(result.errors) >= 1
        assert any("0 running pods" in e for e in result.errors)

    def test_verify_versions_zero_replicas_for_named_workload_passes(self) -> None:
        """Verify zero-replica workload passes when its name is in allow_zero_replicas_for."""
        manifest = {"backend": "v1.2.3"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="backend-deployment",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[],
                ),
            ],
        }

        result = verify_versions(
            manifest=manifest,
            component_map=component_map,
            allow_zero_replicas=False,
            allow_zero_replicas_for=["backend-deployment"],
        )

        assert result.errors == []

    def test_verify_versions_zero_replicas_for_unlisted_workload_fails(self) -> None:
        """Verify zero-replica workload fails when not in allow_zero_replicas_for list."""
        manifest = {"backend": "v1.2.3"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="backend-deployment",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[],
                ),
            ],
        }

        result = verify_versions(
            manifest=manifest,
            component_map=component_map,
            allow_zero_replicas=False,
            allow_zero_replicas_for=["other-deployment"],
        )

        assert len(result.errors) == 1
        assert "0 running pods" in result.errors[0]

    def test_verify_versions_zero_replicas_for_mixed_workloads(self) -> None:
        """Verify only named workloads are exempted; others still fail."""
        manifest = {"backend": "v1.2.3"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="backend-deployment",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[],
                ),
                ComponentMapEntry(
                    workload_name="backend-worker",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[],
                ),
            ],
        }

        result = verify_versions(
            manifest=manifest,
            component_map=component_map,
            allow_zero_replicas=False,
            allow_zero_replicas_for=["backend-deployment"],
        )

        assert len(result.errors) == 1
        assert "backend-worker" in result.errors[0]

    def test_verify_versions_zero_replicas_for_empty_list(self) -> None:
        """Verify empty allow_zero_replicas_for list behaves like default (all fail)."""
        manifest = {"backend": "v1.2.3"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="backend-deployment",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[],
                ),
            ],
        }

        result = verify_versions(
            manifest=manifest,
            component_map=component_map,
            allow_zero_replicas=False,
            allow_zero_replicas_for=[],
        )

        assert len(result.errors) == 1
        assert "0 running pods" in result.errors[0]

    def test_verify_versions_zero_replicas_for_with_version_mismatch(self) -> None:
        """Verify named workload with zero replicas but wrong version still fails on version mismatch."""
        manifest = {"backend": "v2.0.0"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="backend-deployment",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[],
                ),
            ],
        }

        result = verify_versions(
            manifest=manifest,
            component_map=component_map,
            allow_zero_replicas=False,
            allow_zero_replicas_for=["backend-deployment"],
        )

        assert len(result.errors) == 1
        assert "mismatch" in result.errors[0].lower()

    def test_verify_versions_zero_replicas_for_substring_matching(self) -> None:
        """Verify allow_zero_replicas_for uses substring matching against workload names.

        A short pattern like 'my-worker' should match a fully-qualified workload
        name such as 'ns-123456-my-worker', consistent with how --skip-containers
        and --required-workloads use substring matching.
        """
        manifest = {"backend": "v1.2.3"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="ns-123456-my-worker",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[],
                ),
            ],
        }

        result = verify_versions(
            manifest=manifest,
            component_map=component_map,
            allow_zero_replicas=False,
            allow_zero_replicas_for=["my-worker"],
        )

        assert result.errors == []

    def test_verify_versions_zero_replicas_for_substring_no_match(self) -> None:
        """Verify substring matching does not match unrelated workload names."""
        manifest = {"backend": "v1.2.3"}
        component_map = {
            "backend": [
                ComponentMapEntry(
                    workload_name="ns-123456-my-worker",
                    workload_type="Deployment",
                    container_name="backend",
                    container_type=ContainerType.APP,
                    actual_version="v1.2.3",
                    pods=[],
                ),
            ],
        }

        result = verify_versions(
            manifest=manifest,
            component_map=component_map,
            allow_zero_replicas=False,
            allow_zero_replicas_for=["other-service"],
        )

        assert len(result.errors) == 1
        assert "0 running pods" in result.errors[0]


# ---------------------------------------------------------------------------
# validate_manifest tests
# ---------------------------------------------------------------------------


class TestValidateManifest:
    """Tests for ``validate_manifest``."""

    def test_validate_manifest_all_found(self) -> None:
        """Verify all components found returns empty list."""
        manifest = {"backend": "v1.2.3", "frontend": "v1.2.4"}
        component_map = {
            "backend": [MagicMock()],
            "frontend": [MagicMock()],
        }

        errors = validate_manifest(manifest=manifest, component_map=component_map)  # type: ignore[arg-type]

        assert errors == []

    def test_validate_manifest_missing(self) -> None:
        """Verify missing component returns error message."""
        manifest = {"backend": "v1.2.3", "missing-svc": "v1.0.0"}
        component_map = {
            "backend": [MagicMock()],
        }

        errors = validate_manifest(manifest=manifest, component_map=component_map)  # type: ignore[arg-type]

        assert len(errors) == 1
        assert "missing-svc" in errors[0]


# ---------------------------------------------------------------------------
# verify_required_workloads tests
# ---------------------------------------------------------------------------


class TestVerifyRequiredWorkloads:
    """Tests for ``verify_required_workloads``."""

    def test_verify_required_workloads_found(self) -> None:
        """Verify required workload found returns empty list."""
        discovered = [
            WorkloadInspectionResult(name="my-app-frontend", type="Deployment", namespace="default"),
            WorkloadInspectionResult(name="my-app-backend", type="Deployment", namespace="default"),
        ]

        errors = verify_required_workloads(
            required_workloads=["frontend"],
            discovered_workloads=discovered,
        )

        assert errors == []

    def test_verify_required_workloads_missing(self) -> None:
        """Verify missing required workload returns error."""
        discovered = [
            WorkloadInspectionResult(name="my-app-backend", type="Deployment", namespace="default"),
        ]

        errors = verify_required_workloads(
            required_workloads=["frontend"],
            discovered_workloads=discovered,
        )

        assert len(errors) == 1
        assert "frontend" in errors[0]


# ---------------------------------------------------------------------------
# _extract_containers tombstone pod filtering tests
# ---------------------------------------------------------------------------


def _make_pod(
    *,
    name: str,
    image: str,
    phase: str = "Running",
    pod_ip: str = "10.0.0.1",
    node_name: str = "node-1",
) -> V1Pod:
    """Create a ``V1Pod`` with the given phase and image.

    Args:
        name: Pod name.
        image: Container image reference string.
        phase: Pod status phase (e.g. ``"Running"``, ``"Failed"``).
        pod_ip: Pod IP address.
        node_name: Node the pod is scheduled on.

    Returns:
        A ``V1Pod`` instance.
    """
    return V1Pod(
        metadata=V1ObjectMeta(name=name),
        spec=V1PodSpec(
            node_name=node_name,
            containers=[V1Container(name="app", image=image)],
            init_containers=None,
        ),
        status=V1PodStatus(
            phase=phase,
            pod_ip=pod_ip,
            start_time="2025-01-01T00:00:00Z",
        ),
    )


class TestExtractContainersTombstoneFiltering:
    """Tests for tombstone pod filtering in ``_extract_containers``."""

    def test_extract_containers_filters_tombstone_pods(self) -> None:
        """When ``ignore_tombstone_pods=True``, evicted/failed pods are excluded."""
        healthy_pod = _make_pod(name="comp-pod-abc", image="registry/anchor/comp:v2", phase="Running")
        evicted_pod = _make_pod(name="comp-pod-old", image="registry/anchor/comp:v1", phase="Failed")

        workload = WorkloadInspectionResult(
            name="comp",
            type="Deployment",
            namespace="default",
            pods=[healthy_pod, evicted_pod],
            pod_spec=healthy_pod.spec,
        )

        results = _extract_containers(workload, ignore_tombstone_pods=True)

        assert len(results) == 1
        image, container_type, pod_info = results[0]
        assert image == "registry/anchor/comp:v2"
        assert container_type == ContainerType.APP
        assert pod_info is not None
        assert pod_info.phase == "Running"

    def test_extract_containers_includes_tombstone_pods_when_flag_disabled(self) -> None:
        """When ``ignore_tombstone_pods=False``, all pods are included."""
        healthy_pod = _make_pod(name="comp-pod-abc", image="registry/anchor/comp:v2", phase="Running")
        evicted_pod = _make_pod(name="comp-pod-old", image="registry/anchor/comp:v1", phase="Failed")

        workload = WorkloadInspectionResult(
            name="comp",
            type="Deployment",
            namespace="default",
            pods=[healthy_pod, evicted_pod],
            pod_spec=healthy_pod.spec,
        )

        results = _extract_containers(workload, ignore_tombstone_pods=False)

        assert len(results) == 2
        images = {r[0] for r in results}
        assert images == {"registry/anchor/comp:v2", "registry/anchor/comp:v1"}

    def test_extract_containers_falls_back_to_pod_spec_when_all_pods_are_tombstones(self) -> None:
        """When all pods are tombstones and ``ignore_tombstone_pods=True``, fall back to pod_spec."""
        evicted_pod = _make_pod(name="comp-pod-old", image="registry/anchor/comp:v1", phase="Failed")

        pod_spec = V1PodSpec(
            containers=[V1Container(name="app", image="registry/anchor/comp:v2")],
            init_containers=None,
        )

        workload = WorkloadInspectionResult(
            name="comp",
            type="Deployment",
            namespace="default",
            pods=[evicted_pod],
            pod_spec=pod_spec,
        )

        results = _extract_containers(workload, ignore_tombstone_pods=True)

        assert len(results) == 1
        image, container_type, pod_info = results[0]
        assert image == "registry/anchor/comp:v2"
        assert container_type == ContainerType.APP
        # pod_info is None when falling back to pod_spec
        assert pod_info is None

    def test_construct_component_map_filters_tombstone_pods(self) -> None:
        """``construct_component_map`` with ``ignore_tombstone_pods=True`` excludes stale versions."""
        healthy_pod = _make_pod(name="comp-pod-abc", image="registry/anchor/comp:v2", phase="Running")
        evicted_pod = _make_pod(name="comp-pod-old", image="registry/anchor/comp:v1", phase="Failed")

        workload = WorkloadInspectionResult(
            name="comp",
            type="Deployment",
            namespace="default",
            pods=[healthy_pod, evicted_pod],
            pod_spec=healthy_pod.spec,
        )

        manifest = {"comp": "v2"}
        component_map = construct_component_map(
            workloads=[workload],
            manifest=manifest,
            repository_anchor="anchor",
            ignore_tombstone_pods=True,
        )

        assert "comp" in component_map
        entries = component_map["comp"]
        assert len(entries) == 1
        assert entries[0].actual_version == "v2"
