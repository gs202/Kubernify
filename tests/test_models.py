"""Unit tests for the Kubernify data models."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kubernify.models import (
    ComponentMapEntry,
    ContainerType,
    StabilityAuditResult,
    VerificationReport,
    VerificationStatus,
    WorkloadType,
    filter_active_pods,
    is_tombstone_pod,
)

# ---------------------------------------------------------------------------
# VerificationStatus exit codes
# ---------------------------------------------------------------------------


class TestVerificationStatus:
    """Tests for ``VerificationStatus`` enum and exit code mapping."""

    def test_verification_status_exit_codes(self) -> None:
        """Verify exit codes: PASS=0, FAIL=1, SKIPPED=1."""
        assert VerificationStatus.PASS.exit_code == 0
        assert VerificationStatus.FAIL.exit_code == 1
        assert VerificationStatus.SKIPPED.exit_code == 1


# ---------------------------------------------------------------------------
# VerificationReport
# ---------------------------------------------------------------------------


class TestVerificationReport:
    """Tests for ``VerificationReport`` dataclass."""

    def test_verification_report_has_context_field(self) -> None:
        """Verify VerificationReport uses 'context' field (not 'cluster')."""
        report = VerificationReport(
            timestamp="2025-01-01T00:00:00Z",
            context="my-cluster-context",
            namespace="default",
            status=VerificationStatus.PASS,
        )

        assert report.context == "my-cluster-context"
        assert hasattr(report, "context")
        assert not hasattr(report, "cluster")

    def test_verification_report_to_dict(self) -> None:
        """Verify serialization includes 'context' field in output dict."""
        report = VerificationReport(
            timestamp="2025-01-01T00:00:00Z",
            context="my-cluster-context",
            namespace="default",
            status=VerificationStatus.PASS,
        )

        result = report.to_dict()

        assert "context" in result
        assert result["context"] == "my-cluster-context"
        assert "cluster" not in result
        assert result["namespace"] == "default"
        assert result["timestamp"] == "2025-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# ComponentMapEntry
# ---------------------------------------------------------------------------


class TestComponentMapEntry:
    """Tests for ``ComponentMapEntry`` dataclass defaults."""

    def test_component_map_entry_defaults(self) -> None:
        """Verify default empty pods list on ComponentMapEntry."""
        entry = ComponentMapEntry(
            workload_name="backend-deployment",
            workload_type="Deployment",
            container_name="backend",
            container_type=ContainerType.APP,
            actual_version="v1.2.3",
        )

        assert entry.pods == []
        assert entry.workload_name == "backend-deployment"
        assert entry.container_type == ContainerType.APP


# ---------------------------------------------------------------------------
# StabilityAuditResult
# ---------------------------------------------------------------------------


class TestStabilityAuditResult:
    """Tests for ``StabilityAuditResult`` dataclass defaults."""

    def test_stability_audit_result_defaults(self) -> None:
        """Verify all booleans default to False and errors list is empty."""
        result = StabilityAuditResult()

        assert result.converged is False
        assert result.revision_consistent is False
        assert result.pods_healthy is False
        assert result.scheduling_complete is False
        assert result.job_complete is False
        assert result.errors == []


# ---------------------------------------------------------------------------
# WorkloadType
# ---------------------------------------------------------------------------


class TestWorkloadType:
    """Tests for ``WorkloadType`` enum string values."""

    @pytest.mark.parametrize("member", list(WorkloadType))
    def test_workload_type_str_matches_value(self, member: WorkloadType) -> None:
        """Verify str(member) returns the Kubernetes resource kind string."""
        assert str(member) == member.value


# ---------------------------------------------------------------------------
# is_tombstone_pod / filter_active_pods
# ---------------------------------------------------------------------------


def _make_mock_pod(phase: str | None = "Running") -> MagicMock:
    """Create a lightweight mock pod with the given status phase."""
    pod = MagicMock()
    pod.status.phase = phase
    return pod


def _make_mock_pod_no_status() -> MagicMock:
    """Create a mock pod whose ``status`` attribute is ``None``."""
    pod = MagicMock()
    pod.status = None
    return pod


class TestIsTombstonePod:
    """Tests for :func:`is_tombstone_pod`."""

    def test_is_tombstone_pod_failed_phase(self) -> None:
        """Pod with phase 'Failed' is a tombstone."""
        pod = _make_mock_pod(phase="Failed")
        assert is_tombstone_pod(pod) is True

    def test_is_tombstone_pod_succeeded_phase(self) -> None:
        """Pod with phase 'Succeeded' is a tombstone."""
        pod = _make_mock_pod(phase="Succeeded")
        assert is_tombstone_pod(pod) is True

    def test_is_tombstone_pod_running_phase(self) -> None:
        """Pod with phase 'Running' is NOT a tombstone."""
        pod = _make_mock_pod(phase="Running")
        assert is_tombstone_pod(pod) is False

    def test_is_tombstone_pod_pending_phase(self) -> None:
        """Pod with phase 'Pending' is NOT a tombstone."""
        pod = _make_mock_pod(phase="Pending")
        assert is_tombstone_pod(pod) is False

    def test_is_tombstone_pod_no_status(self) -> None:
        """Pod with no status attribute is NOT a tombstone."""
        pod = _make_mock_pod_no_status()
        assert is_tombstone_pod(pod) is False


class TestFilterActivePods:
    """Tests for :func:`filter_active_pods`."""

    def test_filter_active_pods_removes_tombstones(self) -> None:
        """Mixed list returns only active (non-tombstone) pods."""
        running = _make_mock_pod(phase="Running")
        pending = _make_mock_pod(phase="Pending")
        failed = _make_mock_pod(phase="Failed")
        succeeded = _make_mock_pod(phase="Succeeded")

        result = filter_active_pods([running, pending, failed, succeeded])

        assert result == [running, pending]

    def test_filter_active_pods_empty_list(self) -> None:
        """Empty list returns empty list."""
        assert filter_active_pods([]) == []
