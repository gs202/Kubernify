"""Unit tests for KubernetesController initialization and context resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kubernify.kubernetes_controller import KubernetesController, KubernetesControllerException
from kubernify.models import WorkloadType

# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestKubernetesControllerInit:
    """Tests for ``KubernetesController.__init__`` and client initialization."""

    @patch("kubernify.kubernetes_controller.kubernetes.client.BatchV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.AppsV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.CoreV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.ApiClient")
    @patch("kubernify.kubernetes_controller.kubernetes.client.Configuration")
    @patch("kubernify.kubernetes_controller.kubernetes.config.load_kube_config")
    def test_init_with_context(
        self,
        mock_load_kube_config: MagicMock,
        mock_configuration: MagicMock,
        mock_api_client: MagicMock,
        mock_core_v1: MagicMock,
        mock_apps_v1: MagicMock,
        mock_batch_v1: MagicMock,
    ) -> None:
        """Verify context mode loads kubeconfig with the specified context."""
        mock_configuration.get_default_copy.return_value = MagicMock()

        controller = KubernetesController(context="my-cluster-context")

        mock_load_kube_config.assert_called_once_with(context="my-cluster-context")
        assert controller._context == "my-cluster-context"
        assert controller._gke_project is None

    @patch("kubernify.kubernetes_controller.kubernetes.client.BatchV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.AppsV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.CoreV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.ApiClient")
    @patch("kubernify.kubernetes_controller.kubernetes.client.Configuration")
    @patch("kubernify.kubernetes_controller.kubernetes.config.load_kube_config")
    @patch("kubernify.kubernetes_controller.kubernetes.config.list_kube_config_contexts")
    @patch("kubernify.kubernetes_controller.shutil.which", return_value="/usr/bin/gke-gcloud-auth-plugin")
    def test_init_with_gke_project(
        self,
        mock_which: MagicMock,
        mock_list_contexts: MagicMock,
        mock_load_kube_config: MagicMock,
        mock_configuration: MagicMock,
        mock_api_client: MagicMock,
        mock_core_v1: MagicMock,
        mock_apps_v1: MagicMock,
        mock_batch_v1: MagicMock,
    ) -> None:
        """Verify gke_project mode resolves context from kubeconfig contexts."""
        mock_configuration.get_default_copy.return_value = MagicMock()
        mock_list_contexts.return_value = (
            [
                {"name": "gke_my-gcp-project_us-central1_cluster-1"},
                {"name": "gke_other-project_us-east1_cluster-2"},
            ],
            {"name": "gke_my-gcp-project_us-central1_cluster-1"},
        )

        controller = KubernetesController(gke_project="my-gcp-project")

        mock_load_kube_config.assert_called_once_with(context="gke_my-gcp-project_us-central1_cluster-1")
        assert controller._gke_project == "my-gcp-project"

    def test_init_both_context_and_gke_project_raises(self) -> None:
        """Verify ValueError when both context and gke_project are provided."""
        with pytest.raises(
            (ValueError, KubernetesControllerException),
        ):
            KubernetesController(context="my-context", gke_project="my-project")

    @patch("kubernify.kubernetes_controller.kubernetes.client.BatchV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.AppsV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.CoreV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.ApiClient")
    @patch("kubernify.kubernetes_controller.kubernetes.client.Configuration")
    @patch("kubernify.kubernetes_controller.kubernetes.config.load_kube_config")
    @patch("kubernify.kubernetes_controller.kubernetes.config.load_incluster_config")
    def test_init_neither_tries_incluster(
        self,
        mock_load_incluster: MagicMock,
        mock_load_kube_config: MagicMock,
        mock_configuration: MagicMock,
        mock_api_client: MagicMock,
        mock_core_v1: MagicMock,
        mock_apps_v1: MagicMock,
        mock_batch_v1: MagicMock,
    ) -> None:
        """Verify in-cluster config is attempted first when neither context nor gke_project given."""
        mock_configuration.get_default_copy.return_value = MagicMock()

        controller = KubernetesController()

        mock_load_incluster.assert_called_once()
        assert controller._context is None
        assert controller._gke_project is None


# ---------------------------------------------------------------------------
# Context resolution tests
# ---------------------------------------------------------------------------


class TestGetKubeContext:
    """Tests for ``get_kube_context`` GKE context resolution."""

    @patch("kubernify.kubernetes_controller.kubernetes.client.BatchV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.AppsV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.CoreV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.ApiClient")
    @patch("kubernify.kubernetes_controller.kubernetes.client.Configuration")
    @patch("kubernify.kubernetes_controller.kubernetes.config.load_kube_config")
    @patch("kubernify.kubernetes_controller.kubernetes.config.list_kube_config_contexts")
    @patch("kubernify.kubernetes_controller.shutil.which", return_value="/usr/bin/gke-gcloud-auth-plugin")
    def test_get_kube_context_finds_gke_context(
        self,
        mock_which: MagicMock,
        mock_list_contexts: MagicMock,
        mock_load_kube_config: MagicMock,
        mock_configuration: MagicMock,
        mock_api_client: MagicMock,
        mock_core_v1: MagicMock,
        mock_apps_v1: MagicMock,
        mock_batch_v1: MagicMock,
    ) -> None:
        """Verify GKE context resolution finds matching context by project ID."""
        mock_configuration.get_default_copy.return_value = MagicMock()
        mock_list_contexts.return_value = (
            [
                {"name": "gke_target-project_us-central1_cluster-1"},
                {"name": "gke_other-project_us-east1_cluster-2"},
            ],
            {"name": "gke_target-project_us-central1_cluster-1"},
        )

        _controller = KubernetesController(gke_project="target-project")

        # The constructor calls get_kube_context internally and loads the resolved context
        mock_load_kube_config.assert_called_with(context="gke_target-project_us-central1_cluster-1")

    @patch("kubernify.kubernetes_controller.kubernetes.client.BatchV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.AppsV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.CoreV1Api")
    @patch("kubernify.kubernetes_controller.kubernetes.client.ApiClient")
    @patch("kubernify.kubernetes_controller.kubernetes.client.Configuration")
    @patch("kubernify.kubernetes_controller.kubernetes.config.load_kube_config")
    @patch("kubernify.kubernetes_controller.kubernetes.config.list_kube_config_contexts")
    @patch("kubernify.kubernetes_controller.shutil.which", return_value="/usr/bin/gke-gcloud-auth-plugin")
    def test_get_kube_context_no_match_raises(
        self,
        mock_which: MagicMock,
        mock_list_contexts: MagicMock,
        mock_load_kube_config: MagicMock,
        mock_configuration: MagicMock,
        mock_api_client: MagicMock,
        mock_core_v1: MagicMock,
        mock_apps_v1: MagicMock,
        mock_batch_v1: MagicMock,
    ) -> None:
        """Verify exception when no context matches the GKE project."""
        mock_configuration.get_default_copy.return_value = MagicMock()
        mock_list_contexts.return_value = (
            [
                {"name": "gke_other-project_us-east1_cluster-2"},
            ],
            {"name": "gke_other-project_us-east1_cluster-2"},
        )

        with pytest.raises(KubernetesControllerException, match="does not exist"):
            KubernetesController(gke_project="nonexistent-project")


# ---------------------------------------------------------------------------
# Helpers for cache + pagination tests
# ---------------------------------------------------------------------------


def _make_initialized_controller() -> KubernetesController:
    """Build a ``KubernetesController`` with stubbed K8s clients (no kubeconfig touch)."""
    with (
        patch("kubernify.kubernetes_controller.kubernetes.client.BatchV1Api"),
        patch("kubernify.kubernetes_controller.kubernetes.client.AppsV1Api"),
        patch("kubernify.kubernetes_controller.kubernetes.client.CoreV1Api"),
        patch("kubernify.kubernetes_controller.kubernetes.client.ApiClient"),
        patch("kubernify.kubernetes_controller.kubernetes.client.Configuration") as mock_cfg,
        patch("kubernify.kubernetes_controller.kubernetes.config.load_incluster_config"),
        patch("kubernify.kubernetes_controller.kubernetes.config.load_kube_config"),
    ):
        mock_cfg.get_default_copy.return_value = MagicMock()
        controller = KubernetesController()
    controller._apps_v1 = MagicMock()
    controller._core_v1 = MagicMock()
    return controller


def _make_rs(
    name: str,
    *,
    owner_kind: str = WorkloadType.DEPLOYMENT,
    owner_name: str = "my-deployment",
    pod_template_hash: str = "abc123",
    revision: str | None = "1",
    creation_timestamp: int = 0,
) -> MagicMock:
    rs = MagicMock()
    rs.metadata.name = name
    rs.metadata.labels = {"pod-template-hash": pod_template_hash}
    rs.metadata.annotations = {"deployment.kubernetes.io/revision": revision} if revision is not None else {}
    rs.metadata.creation_timestamp = creation_timestamp
    owner = MagicMock()
    owner.kind = owner_kind
    owner.name = owner_name
    rs.metadata.owner_references = [owner]
    return rs


def _make_pod(name: str, labels: dict[str, str] | None = None) -> MagicMock:
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.labels = labels or {}
    return pod


def _make_workload_obj(
    match_labels: dict[str, str],
    match_expressions: list[object] | None = None,
) -> MagicMock:
    workload = MagicMock()
    workload.spec.selector.match_labels = match_labels
    workload.spec.selector.match_expressions = match_expressions
    return workload


# ---------------------------------------------------------------------------
# ReplicaSet pagination + per-cycle cache
# ---------------------------------------------------------------------------


class TestListAllReplicaSets:
    def test_multi_page_pagination_and_label_selector(self) -> None:
        """Pagination loops on ``_continue`` and forwards ``label_selector`` to every request."""
        controller = _make_initialized_controller()
        page_one = MagicMock()
        page_one.items = [_make_rs("rs-1"), _make_rs("rs-2")]
        page_one.metadata._continue = "token-xyz"
        page_two = MagicMock()
        page_two.items = [_make_rs("rs-3")]
        page_two.metadata._continue = None
        controller._apps_v1.list_namespaced_replica_set.side_effect = [page_one, page_two]  # type: ignore[union-attr]

        result = controller.list_all_replica_sets(namespace="ns", page_size=2, label_selector="app=foo")

        assert [rs.metadata.name for rs in result] == ["rs-1", "rs-2", "rs-3"]
        first_kwargs = controller._apps_v1.list_namespaced_replica_set.call_args_list[0].kwargs  # type: ignore[union-attr]
        second_kwargs = controller._apps_v1.list_namespaced_replica_set.call_args_list[1].kwargs  # type: ignore[union-attr]
        assert first_kwargs == {"namespace": "ns", "limit": 2, "label_selector": "app=foo"}
        assert second_kwargs["_continue"] == "token-xyz"

    def test_api_failure_raises_controller_exception(self) -> None:
        controller = _make_initialized_controller()
        controller._apps_v1.list_namespaced_replica_set.side_effect = RuntimeError("boom")  # type: ignore[union-attr]

        with pytest.raises(KubernetesControllerException, match="Failed to list ReplicaSets"):
            controller.list_all_replica_sets(namespace="ns")


class TestDeploymentReplicaSetCache:
    def test_seed_groups_replica_sets_by_owning_deployment(self) -> None:
        controller = _make_initialized_controller()
        rs_a = _make_rs("rs-a", owner_name="deploy-a")
        rs_b1 = _make_rs("rs-b1", owner_name="deploy-b")
        rs_b2 = _make_rs("rs-b2", owner_name="deploy-b")
        rs_orphan = _make_rs("rs-orphan", owner_kind="Job", owner_name="some-job")
        page = MagicMock()
        page.items = [rs_a, rs_b1, rs_b2, rs_orphan]
        page.metadata._continue = None
        controller._apps_v1.list_namespaced_replica_set.return_value = page  # type: ignore[union-attr]

        controller.seed_deployment_replica_set_cache(namespace="ns")

        cache = controller._deployment_rs_cache["ns"]
        assert cache == {"deploy-a": [rs_a], "deploy-b": [rs_b1, rs_b2]}

    def test_seed_failure_leaves_cache_empty(self) -> None:
        controller = _make_initialized_controller()
        controller._apps_v1.list_namespaced_replica_set.side_effect = RuntimeError("boom")  # type: ignore[union-attr]

        controller.seed_deployment_replica_set_cache(namespace="ns")

        assert "ns" not in controller._deployment_rs_cache

    def test_clear_drops_namespace_or_everything(self) -> None:
        controller = _make_initialized_controller()
        controller._deployment_rs_cache = {"ns-a": {}, "ns-b": {}}
        controller.clear_deployment_replica_set_cache(namespace="ns-a")
        assert "ns-a" not in controller._deployment_rs_cache and "ns-b" in controller._deployment_rs_cache
        controller.clear_deployment_replica_set_cache()
        assert controller._deployment_rs_cache == {}

    def test_get_revision_uses_cache_when_seeded(self) -> None:
        controller = _make_initialized_controller()
        rs_old = _make_rs("rs-old", owner_name="my-deploy", pod_template_hash="old", revision="1", creation_timestamp=1)
        rs_new = _make_rs("rs-new", owner_name="my-deploy", pod_template_hash="new", revision="2", creation_timestamp=2)
        controller._deployment_rs_cache = {"ns": {"my-deploy": [rs_old, rs_new]}}

        info = controller.get_deployment_latest_revision_info(deployment_name="my-deploy", namespace="ns")

        assert info.hash == "new"
        assert info.number == 2
        controller._apps_v1.list_namespaced_replica_set.assert_not_called()  # type: ignore[union-attr]

    def test_get_revision_falls_back_to_pagination_when_cache_unseeded(self) -> None:
        """Reachable when ``seed_deployment_replica_set_cache`` failed at the start of a cycle."""
        controller = _make_initialized_controller()
        rs = _make_rs("rs-1", owner_name="my-deploy", pod_template_hash="hash-1", revision="3")
        page = MagicMock()
        page.items = [rs]
        page.metadata._continue = None
        controller._apps_v1.list_namespaced_replica_set.return_value = page  # type: ignore[union-attr]

        info = controller.get_deployment_latest_revision_info(deployment_name="my-deploy", namespace="ns")

        assert info.hash == "hash-1"
        assert info.number == 3
        controller._apps_v1.list_namespaced_replica_set.assert_called_once()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Workload-object reuse on list_pods_for_workload
# ---------------------------------------------------------------------------


class TestListPodsForWorkloadObjectReuse:
    """``list_pods_for_workload`` derives the selector from the in-memory workload."""

    def test_in_memory_workload_obj_drives_selector_and_skips_read(self) -> None:
        controller = _make_initialized_controller()
        page = MagicMock()
        page.items = []
        page.metadata._continue = None
        controller._core_v1.list_namespaced_pod.return_value = page  # type: ignore[union-attr]
        workload_obj = _make_workload_obj({"app": "demo"})

        controller.list_pods_for_workload(workload_name="demo", namespace="ns", workload_obj=workload_obj)

        controller._apps_v1.read_namespaced_deployment.assert_not_called()  # type: ignore[union-attr]
        kwargs = controller._core_v1.list_namespaced_pod.call_args.kwargs  # type: ignore[union-attr]
        assert kwargs["label_selector"] == "app=demo"
        assert kwargs["namespace"] == "ns"

    def test_workload_obj_without_selector_raises(self) -> None:
        controller = _make_initialized_controller()
        workload_obj = MagicMock()
        workload_obj.spec.selector = None

        with pytest.raises(KubernetesControllerException, match=r"has no spec\.selector"):
            controller.list_pods_for_workload(workload_name="bad", namespace="ns", workload_obj=workload_obj)


# ---------------------------------------------------------------------------
# Namespace-wide pod cache
# ---------------------------------------------------------------------------


class TestListAllPods:
    def test_multi_page_pagination(self) -> None:
        controller = _make_initialized_controller()
        page_one = MagicMock()
        page_one.items = [_make_pod("pod-1"), _make_pod("pod-2")]
        page_one.metadata._continue = "token-xyz"
        page_two = MagicMock()
        page_two.items = [_make_pod("pod-3")]
        page_two.metadata._continue = None
        controller._core_v1.list_namespaced_pod.side_effect = [page_one, page_two]  # type: ignore[union-attr]

        result = controller.list_all_pods(namespace="ns", page_size=2)

        assert [p.metadata.name for p in result] == ["pod-1", "pod-2", "pod-3"]
        second_kwargs = controller._core_v1.list_namespaced_pod.call_args_list[1].kwargs  # type: ignore[union-attr]
        assert second_kwargs["_continue"] == "token-xyz"

    def test_api_failure_raises_controller_exception(self) -> None:
        controller = _make_initialized_controller()
        controller._core_v1.list_namespaced_pod.side_effect = RuntimeError("boom")  # type: ignore[union-attr]

        with pytest.raises(KubernetesControllerException, match="Failed to list pods"):
            controller.list_all_pods(namespace="ns")


class TestPodListingUsesCache:
    """Cache-aware pod listing avoids per-workload API calls (with ``match_expressions`` bypass)."""

    def test_seeded_cache_filters_in_memory_and_skips_api(self) -> None:
        controller = _make_initialized_controller()
        controller._namespace_pod_cache = {
            "ns": [
                _make_pod("matching-1", {"app": "demo", "tier": "web"}),
                _make_pod("matching-2", {"app": "demo", "tier": "web", "extra": "x"}),
                _make_pod("non-matching", {"app": "other"}),
                _make_pod("partial-match", {"app": "demo"}),
            ]
        }
        workload_obj = _make_workload_obj({"app": "demo", "tier": "web"})

        result = controller.list_pods_for_workload(workload_name="demo", namespace="ns", workload_obj=workload_obj)

        assert [p.metadata.name for p in result] == ["matching-1", "matching-2"]
        controller._core_v1.list_namespaced_pod.assert_not_called()  # type: ignore[union-attr]

    def test_unseeded_cache_falls_back_to_api(self) -> None:
        """Reachable when ``seed_namespace_pod_cache`` failed at the start of a cycle."""
        controller = _make_initialized_controller()
        page = MagicMock()
        page.items = [_make_pod("api-pod", {"app": "demo"})]
        page.metadata._continue = None
        controller._core_v1.list_namespaced_pod.return_value = page  # type: ignore[union-attr]
        workload_obj = _make_workload_obj({"app": "demo"})

        result = controller.list_pods_for_workload(workload_name="demo", namespace="ns", workload_obj=workload_obj)

        assert [p.metadata.name for p in result] == ["api-pod"]
        controller._core_v1.list_namespaced_pod.assert_called_once()  # type: ignore[union-attr]

    def test_match_expressions_bypasses_cache(self) -> None:
        """``match_expressions`` cannot be reproduced by the cached ``match_labels`` filter."""
        controller = _make_initialized_controller()
        page = MagicMock()
        page.items = [_make_pod("api-pod", {"app": "demo"})]
        page.metadata._continue = None
        controller._core_v1.list_namespaced_pod.return_value = page  # type: ignore[union-attr]
        controller._namespace_pod_cache = {"ns": [_make_pod("cache-pod", {"app": "demo"})]}
        workload_obj = _make_workload_obj({"app": "demo"}, match_expressions=[MagicMock()])

        result = controller.list_pods_for_workload(workload_name="demo", namespace="ns", workload_obj=workload_obj)

        assert [p.metadata.name for p in result] == ["api-pod"]
        controller._core_v1.list_namespaced_pod.assert_called_once()  # type: ignore[union-attr]


class TestNamespacePodCacheLifecycle:
    """``seed`` / ``clear`` lifecycle for the namespace pod cache."""

    def test_seed_populates_and_failure_leaves_empty(self) -> None:
        controller = _make_initialized_controller()
        page = MagicMock()
        page.items = [_make_pod("pod-1")]
        page.metadata._continue = None
        controller._core_v1.list_namespaced_pod.return_value = page  # type: ignore[union-attr]

        controller.seed_namespace_pod_cache(namespace="ns")
        assert [p.metadata.name for p in controller._namespace_pod_cache["ns"]] == ["pod-1"]

        controller._core_v1.list_namespaced_pod.side_effect = RuntimeError("boom")  # type: ignore[union-attr]
        controller.seed_namespace_pod_cache(namespace="other")
        assert "other" not in controller._namespace_pod_cache

    def test_clear_drops_namespace_or_everything(self) -> None:
        controller = _make_initialized_controller()
        controller._namespace_pod_cache = {"ns-a": [], "ns-b": []}
        controller.clear_namespace_pod_cache(namespace="ns-a")
        assert "ns-a" not in controller._namespace_pod_cache and "ns-b" in controller._namespace_pod_cache
        controller.clear_namespace_pod_cache()
        assert controller._namespace_pod_cache == {}
