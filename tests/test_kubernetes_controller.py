"""Unit tests for KubernetesController initialization and context resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kubernify.kubernetes_controller import KubernetesController, KubernetesControllerException

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

        mock_load_kube_config.assert_called_once_with(
            context="gke_my-gcp-project_us-central1_cluster-1"
        )
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
        mock_load_kube_config.assert_called_with(
            context="gke_target-project_us-central1_cluster-1"
        )

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
