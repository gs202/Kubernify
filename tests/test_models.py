"""Unit tests for the Kubernify data models."""

from __future__ import annotations

import pytest

from kubernify.models import (
    ComponentMapEntry,
    ContainerType,
    StabilityAuditResult,
    VerificationReport,
    VerificationStatus,
    WorkloadType,
)

# ---------------------------------------------------------------------------
# VerificationStatus exit codes
# ---------------------------------------------------------------------------


class TestVerificationStatus:
    """Tests for ``VerificationStatus`` enum and exit code mapping."""

    def test_verification_status_exit_codes(self) -> None:
        """Verify exit codes: PASS=0, FAIL=1, TIMEOUT=2, SKIPPED=1."""
        assert VerificationStatus.PASS.exit_code == 0
        assert VerificationStatus.FAIL.exit_code == 1
        assert VerificationStatus.TIMEOUT.exit_code == 2
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
