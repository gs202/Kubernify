"""Data models for Kubernify component mapping and version verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TypeAlias

from kubernetes.client import V1CronJob, V1DaemonSet, V1Deployment, V1Job, V1Pod, V1PodSpec, V1StatefulSet

# ---------------------------------------------------------------------------
# Shared type alias — single definition used by stability_audit & workload_discovery
# ---------------------------------------------------------------------------
KubernetesWorkload: TypeAlias = V1Deployment | V1StatefulSet | V1DaemonSet | V1Job | V1CronJob

# ---------------------------------------------------------------------------
# Constants — replace magic numbers scattered across modules
# ---------------------------------------------------------------------------
DEFAULT_RESTART_THRESHOLD: int = 3  # Maximum acceptable container restart count before flagging instability.

DEFAULT_TIMEOUT_SECONDS: int = 300  # Global timeout for the verification loop (5 minutes).

DEFAULT_THREAD_POOL_WORKERS: int = 40  # Thread-pool size for concurrent workload inspection.

RETRY_INTERVAL_SECONDS: int = 10  # Seconds to sleep between verification/discovery retry iterations.


class WorkloadType(str, Enum):
    """Enum representing supported Kubernetes workload types."""

    DEPLOYMENT = "Deployment"
    STATEFUL_SET = "StatefulSet"
    DAEMON_SET = "DaemonSet"
    JOB = "Job"
    CRON_JOB = "CronJob"


class ContainerType(str, Enum):
    """Classification of a container within a pod spec."""

    INIT = "init"
    APP = "app"


class VerificationStatus(str, Enum):
    """Enumeration of possible verification statuses."""

    PASS = "PASS"  # noqa: S105
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"

    @property
    def exit_code(self) -> int:
        """Return the process exit code for this verification status.

        Returns:
            0 for PASS, 2 for TIMEOUT, 1 for everything else (FAIL, SKIPPED).
        """
        _EXIT_CODES: dict[VerificationStatus, int] = {
            VerificationStatus.PASS: 0,
            VerificationStatus.TIMEOUT: 2,
        }
        return _EXIT_CODES.get(self, 1)


@dataclass
class RevisionInfo:
    """Revision metadata for a Kubernetes workload.

    Captures the update/current revision hashes and, for StatefulSets,
    the rolling-update partition and strategy type.
    """

    hash: str = ""
    current_hash: str = ""
    partition: int = 0
    strategy: str = "RollingUpdate"
    number: int | None = None


@dataclass
class ImageReference:
    """Parsed container image reference.

    Represents the structured components extracted from a container image
    string by the image parser.
    """

    component: str
    full_image: str
    version: str | None = None
    sub_image: str | None = None
    registry: str | None = None


@dataclass
class PodInfo:
    """Information about a Kubernetes pod."""

    name: str
    ip: str
    node: str
    start_time: str
    phase: str


@dataclass
class ComponentMapEntry:
    """Represents a single component map entry containing workload and container information.

    This structure is used to track discovered workloads and their container versions
    during version verification.
    """

    workload_name: str
    workload_type: str
    container_name: str
    container_type: ContainerType
    actual_version: str
    pods: list[PodInfo] = field(default_factory=list)


@dataclass
class VerificationResult:
    """Result of a component verification check."""

    workload: str
    type: str
    container: str
    status: VerificationStatus
    error: str | None = None


@dataclass
class ComponentVerificationResult:
    """Aggregated verification result for a single manifest component.

    Collects per-workload :class:`VerificationResult` entries and tracks
    the overall component status and any error messages.
    """

    status: str = VerificationStatus.PASS.value
    errors: list[str] = field(default_factory=list)
    workloads: list[VerificationResult] = field(default_factory=list)


@dataclass
class VersionVerificationResults:
    """Top-level container returned by :func:`verify_versions`.

    Attributes:
        errors: Flat list of all error strings across every component.
        components: Per-component verification results keyed by component name.
    """

    errors: list[str] = field(default_factory=list)
    components: dict[str, ComponentVerificationResult] = field(default_factory=dict)


@dataclass
class StabilityAuditResult:
    """Result of a workload stability audit containing convergence, revision, health, and scheduling checks."""

    converged: bool = False
    revision_consistent: bool = False
    pods_healthy: bool = False
    scheduling_complete: bool = False
    job_complete: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class WorkloadInspectionResult:
    """Model representing the inspection result of a Kubernetes workload."""

    name: str
    type: str
    namespace: str
    latest_revision: RevisionInfo | None = None
    pods: list[V1Pod] = field(default_factory=list)
    pod_spec: V1PodSpec | None = None
    error: str | None = None


@dataclass
class ReportSummary:
    """Aggregated counts for the verification report."""

    total_components: int = 0
    missing_components: int = 0
    missing_workloads: int = 0
    failed_components: int = 0
    unstable_workloads: int = 0
    skipped_containers: int = 0


@dataclass
class WorkloadReport:
    """Report entry for a single workload within a component."""

    name: str
    type: str
    container: str
    version_error: str | None = None
    stability: dict[str, bool | list[str]] = field(default_factory=dict)


@dataclass
class ComponentReport:
    """Report entry for a single component's verification results."""

    status: str
    errors: list[str] = field(default_factory=list)
    workloads: list[WorkloadReport] = field(default_factory=list)


@dataclass
class VerificationReport:
    """Top-level verification report produced by generate_report.

    Attributes:
        timestamp: ISO 8601 UTC timestamp of report generation.
        context: Kubeconfig context name of the verified cluster.
        namespace: Kubernetes namespace that was inspected.
        status: Overall verification status (PASS / FAIL / TIMEOUT).
        summary: Aggregated counts of components, failures, etc.
        details: Per-component verification details keyed by component name.
            May also contain ``_missing_components`` and ``_missing_workloads``.
    """

    timestamp: str
    context: str
    namespace: str
    status: VerificationStatus
    summary: ReportSummary = field(default_factory=ReportSummary)
    details: dict[str, ComponentReport | list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serialise the report to a plain dict suitable for JSON output.

        Nested dataclass instances (summary, ComponentReport, WorkloadReport)
        are recursively converted via ``dataclasses.asdict``.
        """
        return asdict(self)
