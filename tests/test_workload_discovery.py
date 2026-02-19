"""Unit tests for workload discovery and the --include-* CLI flags.

Tests that ``WorkloadDiscovery`` correctly registers fetch/pod/revision methods
based on the ``include_statefulsets``, ``include_daemonsets``, and ``include_jobs``
constructor flags.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from kubernify.models import WorkloadType
from kubernify.workload_discovery import WorkloadDiscovery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_controller() -> MagicMock:
    """Create a ``MagicMock`` mimicking ``KubernetesController``.

    Returns:
        A ``MagicMock`` with stub methods for all workload fetch/pod/revision APIs.
    """
    controller = MagicMock()
    controller.get_deployments = MagicMock()
    controller.get_stateful_sets = MagicMock()
    controller.get_daemon_sets = MagicMock()
    controller.get_jobs = MagicMock()
    controller.get_cron_jobs = MagicMock()
    controller.list_pods_by_deployment = MagicMock()
    controller.list_pods_by_stateful_set = MagicMock()
    controller.list_pods_by_daemon_set = MagicMock()
    controller.list_pods_by_job = MagicMock()
    controller.get_deployment_latest_revision_info = MagicMock()
    controller.get_stateful_set_latest_revision_info = MagicMock()
    return controller


# ---------------------------------------------------------------------------
# Include flags — fetch method registration
# ---------------------------------------------------------------------------


class TestIncludeFlags:
    """Tests that ``--include-*`` flags control which workload types are discovered."""

    def test_default_includes_only_deployments(self) -> None:
        """Verify that with all include flags False, only Deployments are fetched."""
        controller = _make_mock_controller()

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=False,
            include_daemonsets=False,
            include_jobs=False,
        )

        assert WorkloadType.DEPLOYMENT in discovery._fetch_methods
        assert WorkloadType.STATEFUL_SET not in discovery._fetch_methods
        assert WorkloadType.DAEMON_SET not in discovery._fetch_methods
        assert WorkloadType.JOB not in discovery._fetch_methods
        assert WorkloadType.CRON_JOB not in discovery._fetch_methods

    def test_include_statefulsets_registers_methods(self) -> None:
        """Verify --include-statefulsets registers StatefulSet fetch, pod, and revision methods."""
        controller = _make_mock_controller()

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=True,
            include_daemonsets=False,
            include_jobs=False,
        )

        assert WorkloadType.STATEFUL_SET in discovery._fetch_methods
        assert WorkloadType.STATEFUL_SET in discovery._pod_methods
        assert WorkloadType.STATEFUL_SET in discovery._revision_methods

    def test_include_daemonsets_registers_methods(self) -> None:
        """Verify --include-daemonsets registers DaemonSet fetch and pod methods."""
        controller = _make_mock_controller()

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=False,
            include_daemonsets=True,
            include_jobs=False,
        )

        assert WorkloadType.DAEMON_SET in discovery._fetch_methods
        assert WorkloadType.DAEMON_SET in discovery._pod_methods
        # DaemonSets do not have a revision method in _revision_methods
        assert WorkloadType.DAEMON_SET not in discovery._revision_methods

    def test_include_jobs_registers_methods(self) -> None:
        """Verify --include-jobs registers Job and CronJob fetch methods."""
        controller = _make_mock_controller()

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=False,
            include_daemonsets=False,
            include_jobs=True,
        )

        assert WorkloadType.JOB in discovery._fetch_methods
        assert WorkloadType.CRON_JOB in discovery._fetch_methods
        assert WorkloadType.JOB in discovery._pod_methods

    def test_all_includes_enabled(self) -> None:
        """Verify all workload types are registered when all include flags are True."""
        controller = _make_mock_controller()

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=True,
            include_daemonsets=True,
            include_jobs=True,
        )

        assert WorkloadType.DEPLOYMENT in discovery._fetch_methods
        assert WorkloadType.STATEFUL_SET in discovery._fetch_methods
        assert WorkloadType.DAEMON_SET in discovery._fetch_methods
        assert WorkloadType.JOB in discovery._fetch_methods
        assert WorkloadType.CRON_JOB in discovery._fetch_methods

    def test_exclude_statefulsets_does_not_register(self) -> None:
        """Verify StatefulSet methods are absent when include_statefulsets is False."""
        controller = _make_mock_controller()

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=False,
            include_daemonsets=True,
            include_jobs=True,
        )

        assert WorkloadType.STATEFUL_SET not in discovery._fetch_methods
        assert WorkloadType.STATEFUL_SET not in discovery._pod_methods
        assert WorkloadType.STATEFUL_SET not in discovery._revision_methods

    def test_exclude_daemonsets_does_not_register(self) -> None:
        """Verify DaemonSet methods are absent when include_daemonsets is False."""
        controller = _make_mock_controller()

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=True,
            include_daemonsets=False,
            include_jobs=True,
        )

        assert WorkloadType.DAEMON_SET not in discovery._fetch_methods
        assert WorkloadType.DAEMON_SET not in discovery._pod_methods

    def test_exclude_jobs_does_not_register(self) -> None:
        """Verify Job and CronJob methods are absent when include_jobs is False."""
        controller = _make_mock_controller()

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=True,
            include_daemonsets=True,
            include_jobs=False,
        )

        assert WorkloadType.JOB not in discovery._fetch_methods
        assert WorkloadType.CRON_JOB not in discovery._fetch_methods
        assert WorkloadType.JOB not in discovery._pod_methods


# ---------------------------------------------------------------------------
# fetch_all_workloads tests
# ---------------------------------------------------------------------------


class TestFetchAllWorkloads:
    """Tests for ``fetch_all_workloads`` method."""

    def test_fetch_all_workloads_calls_registered_methods(self) -> None:
        """Verify fetch_all_workloads calls only the registered fetch methods."""
        controller = _make_mock_controller()
        controller.get_deployments.return_value = {"deploy-1": MagicMock()}
        controller.get_stateful_sets.return_value = {"sts-1": MagicMock()}

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=True,
            include_daemonsets=False,
            include_jobs=False,
        )

        result = discovery.fetch_all_workloads(namespace="default")

        controller.get_deployments.assert_called_once_with(namespace="default")
        controller.get_stateful_sets.assert_called_once_with(namespace="default")
        controller.get_daemon_sets.assert_not_called()
        controller.get_jobs.assert_not_called()
        controller.get_cron_jobs.assert_not_called()
        assert WorkloadType.DEPLOYMENT in result
        assert WorkloadType.STATEFUL_SET in result

    def test_fetch_all_workloads_only_deployments(self) -> None:
        """Verify only Deployment fetch is called when all include flags are False."""
        controller = _make_mock_controller()
        controller.get_deployments.return_value = {}

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=False,
            include_daemonsets=False,
            include_jobs=False,
        )

        result = discovery.fetch_all_workloads(namespace="production")

        controller.get_deployments.assert_called_once_with(namespace="production")
        controller.get_stateful_sets.assert_not_called()
        controller.get_daemon_sets.assert_not_called()
        controller.get_jobs.assert_not_called()
        controller.get_cron_jobs.assert_not_called()
        assert WorkloadType.DEPLOYMENT in result


# ---------------------------------------------------------------------------
# discover_cluster_state skip patterns tests
# ---------------------------------------------------------------------------


class TestDiscoverClusterStateSkipPatterns:
    """Tests for ``discover_cluster_state`` skip pattern filtering."""

    def test_skip_patterns_exclude_matching_workloads(self) -> None:
        """Verify workloads matching skip patterns are excluded from inspection."""
        controller = _make_mock_controller()

        mock_workload_1 = MagicMock()
        mock_workload_1.metadata.name = "backend-deployment"
        mock_workload_2 = MagicMock()
        mock_workload_2.metadata.name = "redis-cache"

        controller.get_deployments.return_value = {
            "backend-deployment": mock_workload_1,
            "redis-cache": mock_workload_2,
        }

        discovery = WorkloadDiscovery(
            k8s_controller=controller,
            include_statefulsets=False,
            include_daemonsets=False,
            include_jobs=False,
        )

        with patch.object(discovery, "inspect_workload") as mock_inspect:
            mock_inspect.return_value = MagicMock()
            _results, skipped = discovery.discover_cluster_state(
                namespace="default",
                skip_patterns=["redis"],
            )

        assert "redis-cache" in skipped
        # inspect_workload should only be called for backend-deployment
        assert mock_inspect.call_count == 1
        call_kwargs = mock_inspect.call_args[1]
        assert call_kwargs["workload_name"] == "backend-deployment"
