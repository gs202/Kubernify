"""Shared pytest fixtures for Kubernify test suite."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client import (
    V1Container,
    V1ContainerStatus,
    V1Deployment,
    V1DeploymentSpec,
    V1DeploymentStatus,
    V1LabelSelector,
    V1ObjectMeta,
    V1Pod,
    V1PodCondition,
    V1PodSpec,
    V1PodStatus,
    V1PodTemplateSpec,
)

from kubernify.models import RevisionInfo, WorkloadInspectionResult


@pytest.fixture()
def mock_k8s_client() -> MagicMock:
    """Patch kubernetes.client API classes and return a mock bundle.

    Returns:
        A ``MagicMock`` with ``core_v1``, ``apps_v1``, and ``batch_v1``
        attributes representing the patched Kubernetes API clients.
    """
    with (
        patch("kubernetes.client.CoreV1Api") as mock_core,
        patch("kubernetes.client.AppsV1Api") as mock_apps,
        patch("kubernetes.client.BatchV1Api") as mock_batch,
        patch("kubernetes.client.ApiClient") as mock_api_client,
    ):
        bundle = MagicMock()
        bundle.core_v1 = mock_core.return_value
        bundle.apps_v1 = mock_apps.return_value
        bundle.batch_v1 = mock_batch.return_value
        bundle.api_client = mock_api_client.return_value
        yield bundle


@pytest.fixture()
def sample_manifest() -> dict[str, str]:
    """Return a sample version manifest for testing.

    Returns:
        Dict mapping component names to expected version strings.
    """
    return {"backend": "v1.2.3", "frontend": "v1.2.4"}


@pytest.fixture()
def sample_pod() -> V1Pod:
    """Create a mock V1Pod with configurable metadata.

    Returns:
        A ``V1Pod`` instance with realistic metadata, spec, and status.
    """
    return V1Pod(
        metadata=V1ObjectMeta(
            name="backend-pod-abc12",
            namespace="default",
            labels={"app": "backend", "pod-template-hash": "abc12"},
            deletion_timestamp=None,
        ),
        spec=V1PodSpec(
            node_name="node-1",
            containers=[
                V1Container(
                    name="backend",
                    image="registry.example.com/my-org/my-app/backend:v1.2.3",
                ),
            ],
            init_containers=None,
        ),
        status=V1PodStatus(
            phase="Running",
            pod_ip="10.0.0.1",
            start_time="2025-01-01T00:00:00Z",
            conditions=[
                V1PodCondition(type="Ready", status="True"),
            ],
            container_statuses=[
                V1ContainerStatus(
                    name="backend",
                    ready=True,
                    restart_count=0,
                    image="registry.example.com/my-org/my-app/backend:v1.2.3",
                    image_id="sha256:abc123",
                    state=MagicMock(waiting=None),
                ),
            ],
        ),
    )


@pytest.fixture()
def sample_deployment() -> V1Deployment:
    """Create a mock V1Deployment with realistic spec and status.

    Returns:
        A ``V1Deployment`` instance suitable for stability and convergence tests.
    """
    return V1Deployment(
        metadata=V1ObjectMeta(
            name="backend-deployment",
            namespace="default",
            generation=3,
        ),
        spec=V1DeploymentSpec(
            replicas=2,
            selector=V1LabelSelector(match_labels={"app": "backend"}),
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels={"app": "backend"}),
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="backend",
                            image="registry.example.com/my-org/my-app/backend:v1.2.3",
                        ),
                    ],
                ),
            ),
        ),
        status=V1DeploymentStatus(
            observed_generation=3,
            replicas=2,
            ready_replicas=2,
            available_replicas=2,
        ),
    )


@pytest.fixture()
def sample_workload_inspection() -> WorkloadInspectionResult:
    """Create a WorkloadInspectionResult with sample data.

    Returns:
        A ``WorkloadInspectionResult`` for a Deployment with one pod and revision info.
    """
    pod = V1Pod(
        metadata=V1ObjectMeta(
            name="backend-pod-abc12",
            namespace="default",
            labels={"app": "backend", "pod-template-hash": "abc12"},
            deletion_timestamp=None,
        ),
        spec=V1PodSpec(
            node_name="node-1",
            containers=[
                V1Container(
                    name="backend",
                    image="registry.example.com/my-org/my-app/backend:v1.2.3",
                ),
            ],
            init_containers=None,
        ),
        status=V1PodStatus(
            phase="Running",
            pod_ip="10.0.0.1",
            start_time="2025-01-01T00:00:00Z",
            conditions=[
                V1PodCondition(type="Ready", status="True"),
            ],
            container_statuses=[
                V1ContainerStatus(
                    name="backend",
                    ready=True,
                    restart_count=0,
                    image="registry.example.com/my-org/my-app/backend:v1.2.3",
                    image_id="sha256:abc123",
                    state=MagicMock(waiting=None),
                ),
            ],
        ),
    )

    return WorkloadInspectionResult(
        name="backend-deployment",
        type="Deployment",
        namespace="default",
        latest_revision=RevisionInfo(hash="abc12"),
        pods=[pod],
        pod_spec=pod.spec,
    )
