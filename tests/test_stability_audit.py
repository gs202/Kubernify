"""Unit tests for the stability audit checks in kubernify.stability_audit."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from kubernetes.client import (
    V1ContainerStateWaiting,
    V1ContainerStatus,
    V1DaemonSet,
    V1DaemonSetStatus,
    V1Deployment,
    V1Job,
    V1JobSpec,
    V1JobStatus,
    V1ObjectMeta,
    V1Pod,
    V1PodCondition,
    V1PodSpec,
    V1PodStatus,
)

from kubernify.models import WorkloadInspectionResult
from kubernify.stability_audit import StabilityAuditor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_auditor() -> StabilityAuditor:
    """Create a ``StabilityAuditor`` with a mocked ``KubernetesController``.

    Returns:
        A ``StabilityAuditor`` instance backed by a ``MagicMock`` controller.
    """
    mock_controller = MagicMock()
    return StabilityAuditor(k8s_controller=mock_controller)


def _make_workload(*, generation: int, observed_generation: int | None) -> MagicMock:
    """Create a mock workload with configurable generation metadata.

    Args:
        generation: The metadata.generation value.
        observed_generation: The status.observed_generation value (or None).

    Returns:
        A ``MagicMock`` representing a Kubernetes workload object.
    """
    workload = MagicMock()
    workload.metadata.generation = generation
    if observed_generation is not None:
        workload.status.observed_generation = observed_generation
    else:
        workload.status = None
    return workload


def _make_pod(
    *,
    name: str = "test-pod",
    ready: bool = True,
    restart_count: int = 0,
    waiting_reason: str | None = None,
    labels: dict[str, str] | None = None,
) -> V1Pod:
    """Create a mock V1Pod with configurable health attributes.

    Args:
        name: Pod name.
        ready: Whether the pod has a Ready=True condition.
        restart_count: Container restart count.
        waiting_reason: If set, the container waiting state reason.
        labels: Pod labels dict.

    Returns:
        A ``V1Pod`` instance with the specified attributes.
    """
    conditions = []
    if ready:
        conditions.append(V1PodCondition(type="Ready", status="True"))

    waiting_state = None
    if waiting_reason:
        waiting_state = V1ContainerStateWaiting(reason=waiting_reason)

    container_state = MagicMock()
    container_state.waiting = waiting_state

    return V1Pod(
        metadata=V1ObjectMeta(
            name=name,
            labels=labels or {},
            deletion_timestamp=None,
        ),
        spec=V1PodSpec(containers=[]),
        status=V1PodStatus(
            phase="Running",
            start_time="2025-01-01T00:00:00Z",
            conditions=conditions,
            container_statuses=[
                V1ContainerStatus(
                    name="main",
                    ready=ready,
                    restart_count=restart_count,
                    image="registry.example.com/my-org/my-app/backend:v1.0.0",
                    image_id="sha256:abc",
                    state=container_state,
                ),
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Controller convergence tests
# ---------------------------------------------------------------------------


class TestCheckControllerConvergence:
    """Tests for ``check_controller_convergence``."""

    def test_check_controller_convergence_converged(self) -> None:
        """Verify observedGeneration >= generation returns True."""
        auditor = _make_auditor()
        workload = _make_workload(generation=3, observed_generation=3)

        result = auditor.check_controller_convergence(workload=workload)

        assert result is True

    def test_check_controller_convergence_not_converged(self) -> None:
        """Verify observedGeneration < generation returns False."""
        auditor = _make_auditor()
        workload = _make_workload(generation=5, observed_generation=4)

        result = auditor.check_controller_convergence(workload=workload)

        assert result is False


# ---------------------------------------------------------------------------
# Revision consistency tests
# ---------------------------------------------------------------------------


class TestCheckRevisionConsistency:
    """Tests for ``check_revision_consistency``."""

    def test_check_revision_consistency_all_match(self) -> None:
        """Verify all pods with matching hash returns empty errors."""
        auditor = _make_auditor()
        pods = [
            _make_pod(name="pod-1", labels={"pod-template-hash": "abc12"}),
            _make_pod(name="pod-2", labels={"pod-template-hash": "abc12"}),
        ]

        errors = auditor.check_revision_consistency(
            pods=pods,
            expected_revision_hash="abc12",
            workload_type="Deployment",
        )

        assert errors == []

    def test_check_revision_consistency_mismatch(self) -> None:
        """Verify pod with wrong hash returns error."""
        auditor = _make_auditor()
        pods = [
            _make_pod(name="pod-1", labels={"pod-template-hash": "abc12"}),
            _make_pod(name="pod-2", labels={"pod-template-hash": "old-hash"}),
        ]

        errors = auditor.check_revision_consistency(
            pods=pods,
            expected_revision_hash="abc12",
            workload_type="Deployment",
        )

        assert len(errors) == 1
        assert "pod-2" in errors[0]
        assert "old-hash" in errors[0]


# ---------------------------------------------------------------------------
# Pod health tests
# ---------------------------------------------------------------------------


class TestCheckPodHealth:
    """Tests for ``check_pod_health``."""

    def test_check_pod_health_healthy(self) -> None:
        """Verify ready pod with low restarts returns empty errors."""
        auditor = _make_auditor()
        pod = _make_pod(name="healthy-pod", ready=True, restart_count=0)

        errors = auditor.check_pod_health(pod=pod, restart_threshold=3)

        assert errors == []

    def test_check_pod_health_not_ready(self) -> None:
        """Verify pod without Ready condition returns error."""
        auditor = _make_auditor()
        pod = _make_pod(name="unready-pod", ready=False, restart_count=0)

        errors = auditor.check_pod_health(pod=pod, restart_threshold=3)

        assert len(errors) >= 1
        assert any("not Ready" in e for e in errors)

    def test_check_pod_health_crash_loop(self) -> None:
        """Verify pod in CrashLoopBackOff returns error."""
        auditor = _make_auditor()
        pod = _make_pod(
            name="crash-pod",
            ready=False,
            restart_count=5,
            waiting_reason="CrashLoopBackOff",
        )

        errors = auditor.check_pod_health(pod=pod, restart_threshold=3)

        assert any("CrashLoopBackOff" in e for e in errors)

    def test_check_pod_health_high_restarts(self) -> None:
        """Verify pod exceeding restart threshold returns error."""
        auditor = _make_auditor()
        pod = _make_pod(name="restart-pod", ready=True, restart_count=10)

        errors = auditor.check_pod_health(pod=pod, restart_threshold=3)

        assert any("restarts" in e for e in errors)

    def test_check_pod_health_restarts_at_threshold_passes(self) -> None:
        """Verify pod with restarts exactly at threshold is acceptable."""
        auditor = _make_auditor()
        pod = _make_pod(name="border-pod", ready=True, restart_count=3)

        errors = auditor.check_pod_health(pod=pod, restart_threshold=3)

        assert not any("restarts" in e for e in errors)

    def test_check_pod_health_threshold_zero_no_restarts(self) -> None:
        """Verify threshold=0 allows pods with zero restarts."""
        auditor = _make_auditor()
        pod = _make_pod(name="clean-pod", ready=True, restart_count=0)

        errors = auditor.check_pod_health(pod=pod, restart_threshold=0)

        assert errors == []

    def test_check_pod_health_threshold_zero_with_restarts(self) -> None:
        """Verify threshold=0 flags pods that have any restarts."""
        auditor = _make_auditor()
        pod = _make_pod(name="restarted-pod", ready=True, restart_count=1)

        errors = auditor.check_pod_health(pod=pod, restart_threshold=0)

        assert any("restarts" in e for e in errors)

    def test_check_pod_health_threshold_negative_one_skips_check(self) -> None:
        """Verify threshold=-1 disables the restart check entirely."""
        auditor = _make_auditor()
        pod = _make_pod(name="noisy-pod", ready=True, restart_count=100)

        errors = auditor.check_pod_health(pod=pod, restart_threshold=-1)

        assert not any("restarts" in e for e in errors)


# ---------------------------------------------------------------------------
# DaemonSet scheduling tests
# ---------------------------------------------------------------------------


class TestVerifyDaemonSetScheduling:
    """Tests for ``verify_daemon_set_scheduling``."""

    def test_verify_daemon_set_scheduling_complete(self) -> None:
        """Verify available >= desired returns empty errors."""
        auditor = _make_auditor()
        ds = V1DaemonSet(
            metadata=V1ObjectMeta(name="test-ds"),
            status=V1DaemonSetStatus(
                desired_number_scheduled=3,
                number_available=3,
                updated_number_scheduled=3,
                current_number_scheduled=3,
                number_ready=3,
                number_misscheduled=0,
            ),
        )

        errors = auditor.verify_daemon_set_scheduling(daemon_set=ds)

        assert errors == []

    def test_verify_daemon_set_scheduling_incomplete(self) -> None:
        """Verify available < desired returns error."""
        auditor = _make_auditor()
        ds = V1DaemonSet(
            metadata=V1ObjectMeta(name="test-ds"),
            status=V1DaemonSetStatus(
                desired_number_scheduled=5,
                number_available=2,
                updated_number_scheduled=5,
                current_number_scheduled=5,
                number_ready=2,
                number_misscheduled=0,
            ),
        )

        errors = auditor.verify_daemon_set_scheduling(daemon_set=ds)

        assert len(errors) >= 1
        assert any("available" in e for e in errors)


# ---------------------------------------------------------------------------
# Job status tests
# ---------------------------------------------------------------------------


class TestVerifyJobStatus:
    """Tests for ``verify_job_status``."""

    def test_verify_job_status_succeeded(self) -> None:
        """Verify succeeded >= 1 returns empty errors."""
        auditor = _make_auditor()
        job = V1Job(
            metadata=V1ObjectMeta(name="test-job"),
            spec=V1JobSpec(
                template=MagicMock(),
                backoff_limit=6,
            ),
            status=V1JobStatus(succeeded=1, failed=0),
        )

        errors = auditor.verify_job_status(job=job)

        assert errors == []

    def test_verify_job_status_not_succeeded(self) -> None:
        """Verify succeeded = 0 returns error."""
        auditor = _make_auditor()
        job = V1Job(
            metadata=V1ObjectMeta(name="test-job"),
            spec=V1JobSpec(
                template=MagicMock(),
                backoff_limit=6,
            ),
            status=V1JobStatus(succeeded=0, failed=0),
        )

        errors = auditor.verify_job_status(job=job)

        assert len(errors) >= 1
        assert any("not succeeded" in e for e in errors)


# ---------------------------------------------------------------------------
# Min uptime tests
# ---------------------------------------------------------------------------


class TestCheckPodHealthMinUptime:
    """Tests for ``check_pod_health`` with ``min_uptime_sec`` parameter."""

    def test_pod_below_min_uptime_returns_error(self) -> None:
        """Verify pod with uptime below min_uptime_sec returns an uptime error."""
        auditor = _make_auditor()
        # Pod started 10 seconds ago, but we require 120 seconds
        recent_start = datetime.now(timezone.utc) - timedelta(seconds=10)
        pod = V1Pod(
            metadata=V1ObjectMeta(
                name="young-pod",
                labels={},
                deletion_timestamp=None,
            ),
            spec=V1PodSpec(containers=[]),
            status=V1PodStatus(
                phase="Running",
                start_time=recent_start,
                conditions=[
                    V1PodCondition(type="Ready", status="True"),
                ],
                container_statuses=[
                    V1ContainerStatus(
                        name="main",
                        ready=True,
                        restart_count=0,
                        image="registry.example.com/my-org/my-app/backend:v1.0.0",
                        image_id="sha256:abc",
                        state=MagicMock(waiting=None),
                    ),
                ],
            ),
        )

        errors = auditor.check_pod_health(pod=pod, restart_threshold=3, min_uptime_sec=120)

        assert len(errors) >= 1
        assert any("uptime" in e for e in errors)

    def test_pod_above_min_uptime_returns_no_error(self) -> None:
        """Verify pod with uptime above min_uptime_sec returns no uptime error."""
        auditor = _make_auditor()
        # Pod started 300 seconds ago, we require 120 seconds
        old_start = datetime.now(timezone.utc) - timedelta(seconds=300)
        pod = V1Pod(
            metadata=V1ObjectMeta(
                name="old-pod",
                labels={},
                deletion_timestamp=None,
            ),
            spec=V1PodSpec(containers=[]),
            status=V1PodStatus(
                phase="Running",
                start_time=old_start,
                conditions=[
                    V1PodCondition(type="Ready", status="True"),
                ],
                container_statuses=[
                    V1ContainerStatus(
                        name="main",
                        ready=True,
                        restart_count=0,
                        image="registry.example.com/my-org/my-app/backend:v1.0.0",
                        image_id="sha256:abc",
                        state=MagicMock(waiting=None),
                    ),
                ],
            ),
        )

        errors = auditor.check_pod_health(pod=pod, restart_threshold=3, min_uptime_sec=120)

        assert errors == []

    def test_pod_no_start_time_returns_error(self) -> None:
        """Verify pod with no start_time returns error when min_uptime_sec > 0."""
        auditor = _make_auditor()
        pod = V1Pod(
            metadata=V1ObjectMeta(
                name="no-start-pod",
                labels={},
                deletion_timestamp=None,
            ),
            spec=V1PodSpec(containers=[]),
            status=V1PodStatus(
                phase="Pending",
                start_time=None,
                conditions=[
                    V1PodCondition(type="Ready", status="True"),
                ],
                container_statuses=[
                    V1ContainerStatus(
                        name="main",
                        ready=True,
                        restart_count=0,
                        image="registry.example.com/my-org/my-app/backend:v1.0.0",
                        image_id="sha256:abc",
                        state=MagicMock(waiting=None),
                    ),
                ],
            ),
        )

        errors = auditor.check_pod_health(pod=pod, restart_threshold=3, min_uptime_sec=60)

        assert len(errors) >= 1
        assert any("not started" in e for e in errors)

    def test_min_uptime_zero_skips_check(self) -> None:
        """Verify min_uptime_sec=0 does not perform uptime check."""
        auditor = _make_auditor()
        # Pod started 1 second ago — would fail with min_uptime > 0
        recent_start = datetime.now(timezone.utc) - timedelta(seconds=1)
        pod = V1Pod(
            metadata=V1ObjectMeta(
                name="fresh-pod",
                labels={},
                deletion_timestamp=None,
            ),
            spec=V1PodSpec(containers=[]),
            status=V1PodStatus(
                phase="Running",
                start_time=recent_start,
                conditions=[
                    V1PodCondition(type="Ready", status="True"),
                ],
                container_statuses=[
                    V1ContainerStatus(
                        name="main",
                        ready=True,
                        restart_count=0,
                        image="registry.example.com/my-org/my-app/backend:v1.0.0",
                        image_id="sha256:abc",
                        state=MagicMock(waiting=None),
                    ),
                ],
            ),
        )

        errors = auditor.check_pod_health(pod=pod, restart_threshold=3, min_uptime_sec=0)

        assert errors == []


class TestCheckDeploymentAvailability:
    """Tests for StabilityAuditor.check_deployment_availability."""

    def test_available_equals_desired_passes(self, sample_deployment: V1Deployment) -> None:
        """Verify available_replicas == spec.replicas returns no errors."""
        # sample_deployment has spec.replicas=2, status.available_replicas=2
        errors = StabilityAuditor.check_deployment_availability(workload_obj=sample_deployment)
        assert errors == []

    def test_available_less_than_desired_fails(self, sample_deployment: V1Deployment) -> None:
        """Verify available_replicas < spec.replicas returns an error."""
        sample_deployment.status.available_replicas = 1  # only 1 of 2 available
        errors = StabilityAuditor.check_deployment_availability(workload_obj=sample_deployment)
        assert len(errors) == 1
        assert "1/2" in errors[0]

    def test_zero_desired_replicas_skips_check(self, sample_deployment: V1Deployment) -> None:
        """Verify spec.replicas == 0 skips the availability check."""
        sample_deployment.spec.replicas = 0
        sample_deployment.status.available_replicas = 0
        errors = StabilityAuditor.check_deployment_availability(workload_obj=sample_deployment)
        assert errors == []

    def test_none_available_replicas_treated_as_zero(self, sample_deployment: V1Deployment) -> None:
        """Verify None available_replicas is treated as 0 (fails when desired > 0)."""
        sample_deployment.status.available_replicas = None
        errors = StabilityAuditor.check_deployment_availability(workload_obj=sample_deployment)
        assert len(errors) == 1
        assert "0/2" in errors[0]

    def test_error_message_includes_tombstone_note(self, sample_deployment: V1Deployment) -> None:
        """Verify error message mentions tombstone exclusion."""
        sample_deployment.status.available_replicas = 0
        errors = StabilityAuditor.check_deployment_availability(workload_obj=sample_deployment)
        assert "tombstone" in errors[0].lower()


class TestAuditWorkloadTombstoneAndAvailability:
    """Tests for tombstone filtering and availability check in audit_workload."""

    def _make_auditor_with_deployment(self, deployment: V1Deployment) -> StabilityAuditor:
        """Return a StabilityAuditor whose _get_workload_object returns the given deployment."""
        auditor = _make_auditor()
        auditor._get_workload_object = MagicMock(return_value=deployment)  # type: ignore[method-assign]
        return auditor

    def _make_tombstone_pod(self, phase: str, name: str = "dead-pod") -> V1Pod:
        """Create a pod in a terminal phase (tombstone)."""
        return V1Pod(
            metadata=V1ObjectMeta(
                name=name,
                labels={"pod-template-hash": "abc12"},
                deletion_timestamp=None,
            ),
            spec=V1PodSpec(containers=[]),
            status=V1PodStatus(
                phase=phase,
                start_time="2025-01-01T00:00:00Z",
                conditions=[],
                container_statuses=[],
            ),
        )

    def test_tombstone_pod_fails_health_check_without_flag(
        self, sample_deployment: V1Deployment, sample_workload_inspection: WorkloadInspectionResult
    ) -> None:
        """Verify OOMKilled pod fails health check when flag is not set."""
        tombstone = self._make_tombstone_pod(phase="Failed", name="oomkilled-pod")
        sample_workload_inspection.pods = [tombstone]
        sample_deployment.status.available_replicas = 0  # availability also fails
        auditor = self._make_auditor_with_deployment(sample_deployment)

        result = auditor.audit_workload(
            workload_info=sample_workload_inspection,
            ignore_tombstone_pods=False,
        )

        assert result.pods_healthy is False
        assert any("oomkilled-pod" in e or "not Ready" in e for e in result.errors)

    def test_tombstone_pod_ignored_with_flag(
        self, sample_deployment: V1Deployment, sample_workload_inspection: WorkloadInspectionResult
    ) -> None:
        """Verify OOMKilled pod is excluded from health check when flag is set."""
        tombstone = self._make_tombstone_pod(phase="Failed", name="oomkilled-pod")
        live_pod = _make_pod(name="live-pod", ready=True, labels={"pod-template-hash": "abc12"})
        sample_workload_inspection.pods = [tombstone, live_pod]
        # availability: 1 available of 2 desired — still fails availability
        sample_deployment.status.available_replicas = 1
        auditor = self._make_auditor_with_deployment(sample_deployment)

        result = auditor.audit_workload(
            workload_info=sample_workload_inspection,
            ignore_tombstone_pods=True,
        )

        # Health check passes (tombstone excluded), but availability fails
        assert result.pods_healthy is True
        assert any("availability" in e.lower() for e in result.errors)

    def test_availability_check_always_runs(
        self, sample_deployment: V1Deployment, sample_workload_inspection: WorkloadInspectionResult
    ) -> None:
        """Verify availability check runs even when ignore_tombstone_pods=True."""
        sample_deployment.status.available_replicas = 0
        auditor = self._make_auditor_with_deployment(sample_deployment)

        result = auditor.audit_workload(
            workload_info=sample_workload_inspection,
            ignore_tombstone_pods=True,
        )

        assert any("availability" in e.lower() for e in result.errors)

    def test_availability_passes_when_replicas_match(
        self, sample_deployment: V1Deployment, sample_workload_inspection: WorkloadInspectionResult
    ) -> None:
        """Verify no availability errors when available == desired."""
        # sample_deployment: spec.replicas=2, status.available_replicas=2
        auditor = self._make_auditor_with_deployment(sample_deployment)

        result = auditor.audit_workload(workload_info=sample_workload_inspection)

        assert not any("availability" in e.lower() for e in result.errors)

    def test_succeeded_pod_filtered_with_flag(
        self, sample_deployment: V1Deployment, sample_workload_inspection: WorkloadInspectionResult
    ) -> None:
        """Verify Succeeded (completed) pod is excluded from health check when flag is set."""
        completed = self._make_tombstone_pod(phase="Succeeded", name="completed-pod")
        sample_workload_inspection.pods = [completed]
        auditor = self._make_auditor_with_deployment(sample_deployment)

        result = auditor.audit_workload(
            workload_info=sample_workload_inspection,
            ignore_tombstone_pods=True,
        )

        # No pods to health-check after filtering → pods_healthy=True (no errors)
        assert result.pods_healthy is True
