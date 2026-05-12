"""Kubernetes API controller for Kubernify.

Provides a unified interface to the Kubernetes API for fetching workloads,
listing pods, and retrieving revision metadata.  Supports both in-cluster
and local kubeconfig authentication.
"""

from __future__ import annotations

import logging
import os
import pathlib
import shutil
import threading
import time
from collections.abc import Callable
from typing import Any

import kubernetes
import kubernetes.client
import kubernetes.config
from kubernetes.client import (
    V1CronJob,
    V1DaemonSet,
    V1Deployment,
    V1Job,
    V1LabelSelector,
    V1Pod,
    V1ReplicaSet,
    V1StatefulSet,
)

from .models import RevisionInfo, WorkloadType


class KubernetesControllerException(Exception):
    """Base exception for KubernetesController errors."""


class KubernetesController:
    """Thin wrapper around the Kubernetes Python client.

    Handles configuration loading (in-cluster or kubeconfig), connection
    pooling, and provides convenience methods for workload and pod queries.

    Args:
        context: Kubeconfig context name to use directly for cluster connection.
        gke_project: GCP project ID — resolves the kube context from GKE-style
            context names. Cannot be specified together with ``context``.
        insecure: When ``True``, disable SSL certificate verification.
    """

    def __init__(
        self,
        context: str | None = None,
        gke_project: str | None = None,
        insecure: bool = False,
    ) -> None:
        self.logger = logging.getLogger(__name__)

        # Reduce noise from kubernetes client REST logging (only set once)
        k8s_rest_logger = logging.getLogger("kubernetes.client.rest")
        if not k8s_rest_logger.level or k8s_rest_logger.level == logging.NOTSET:
            k8s_rest_logger.setLevel(logging.INFO)

        self._context = context
        self._gke_project = gke_project
        self._insecure = insecure

        # Client and API instances
        self._api_client: kubernetes.client.ApiClient | None = None
        self._core_v1: kubernetes.client.CoreV1Api | None = None
        self._apps_v1: kubernetes.client.AppsV1Api | None = None
        self._batch_v1: kubernetes.client.BatchV1Api | None = None

        # Lock for thread-safe initialization of the client
        self._client_lock = threading.Lock()

        # Per-discovery-cycle caches keyed by namespace; both are accessed
        # from a thread pool so each has its own lock.
        self._deployment_rs_cache: dict[str, dict[str, list[V1ReplicaSet]]] = {}
        self._rs_cache_lock = threading.Lock()
        self._namespace_pod_cache: dict[str, list[V1Pod]] = {}
        self._namespace_pod_cache_lock = threading.Lock()

        # Initialize the client immediately
        self._initialize_client()

    @property
    def core_v1(self) -> kubernetes.client.CoreV1Api:
        if self._core_v1 is None:
            raise RuntimeError("Kubernetes client not initialized")
        return self._core_v1

    @property
    def apps_v1(self) -> kubernetes.client.AppsV1Api:
        if self._apps_v1 is None:
            raise RuntimeError("Kubernetes client not initialized")
        return self._apps_v1

    @property
    def batch_v1(self) -> kubernetes.client.BatchV1Api:
        if self._batch_v1 is None:
            raise RuntimeError("Kubernetes client not initialized")
        return self._batch_v1

    # ------------------------------------------------------------------
    # Client initialisation
    # ------------------------------------------------------------------

    def _initialize_client(self) -> None:
        """Initialise the Kubernetes client with robust error handling.

        Resolution logic:
            - If both ``context`` and ``gke_project`` are provided → raise ``ValueError``.
            - If ``context`` is provided → load kubeconfig with that context directly.
            - If ``gke_project`` is provided → ensure GKE auth plugin is on PATH,
              resolve the context via ``get_kube_context()``, then load kubeconfig.
            - If neither → try in-cluster config first, then fall back to default
              kubeconfig context.
        """
        with self._client_lock:
            if self._api_client:
                return

            if self._context and self._gke_project:
                raise ValueError("Cannot specify both 'context' and 'gke_project'")

            try:
                if self._context:
                    kubernetes.config.load_kube_config(context=self._context)
                    self.logger.info(f"Successfully loaded kubeconfig for context: {self._context}")
                elif self._gke_project:
                    self._ensure_gke_auth_plugin_on_path()
                    resolved_context = self.get_kube_context()
                    kubernetes.config.load_kube_config(context=resolved_context)
                    self.logger.info(f"Successfully loaded kubeconfig for GKE project context: {resolved_context}")
                else:
                    try:
                        kubernetes.config.load_incluster_config()
                        self.logger.info("Successfully loaded in-cluster configuration.")
                    except kubernetes.config.ConfigException:
                        self.logger.info("In-cluster config not found. Falling back to default kubeconfig context.")
                        kubernetes.config.load_kube_config()
                        self.logger.info("Successfully loaded default kubeconfig context.")

                configuration = kubernetes.client.Configuration.get_default_copy()
                if self._insecure:
                    configuration.verify_ssl = False
                    configuration.assert_hostname = False

                self._api_client = kubernetes.client.ApiClient(configuration)
                self._core_v1 = kubernetes.client.CoreV1Api(self._api_client)
                self._apps_v1 = kubernetes.client.AppsV1Api(self._api_client)
                self._batch_v1 = kubernetes.client.BatchV1Api(self._api_client)

            except Exception as e:
                identifier = self._context or self._gke_project or "in-cluster/default"
                error_msg = f"Failed to initialize Kubernetes client for {identifier}: {e}"
                self.logger.error(error_msg)
                raise KubernetesControllerException(error_msg) from e

    def _ensure_gke_auth_plugin_on_path(self) -> None:
        """Ensure ``gke-gcloud-auth-plugin`` is discoverable on PATH.

        Resolution order:
            1. Already on PATH (``shutil.which`` finds it) → nothing to do.
            2. Scan existing PATH entries for a directory whose path contains
               ``google-cloud-sdk`` and derive the SDK ``bin/`` directory.
            3. Check ``CLOUDSDK_ROOT_DIR`` / ``GCLOUD_SDK_PATH`` env vars.
            4. Log a warning if none of the above succeed.
        """
        if shutil.which("gke-gcloud-auth-plugin"):
            return

        for path_entry in os.environ.get("PATH", "").split(os.pathsep):
            if "google-cloud-sdk" in path_entry:
                sdk_root = pathlib.Path(path_entry)
                while sdk_root.name and sdk_root.name != "google-cloud-sdk":
                    sdk_root = sdk_root.parent
                if sdk_root.name == "google-cloud-sdk":
                    gcloud_bin = str(sdk_root / "bin")
                    if gcloud_bin not in os.environ["PATH"]:
                        os.environ["PATH"] += os.pathsep + gcloud_bin
                        self.logger.info(f"Added {gcloud_bin} to PATH for gke-gcloud-auth-plugin")
                    return

        sdk_root_env = os.environ.get("CLOUDSDK_ROOT_DIR") or os.environ.get("GCLOUD_SDK_PATH")
        if sdk_root_env:
            gcloud_bin = os.path.join(sdk_root_env, "bin")
            os.environ["PATH"] += os.pathsep + gcloud_bin
            self.logger.info(f"Added {gcloud_bin} to PATH for gke-gcloud-auth-plugin")
            return

        self.logger.warning(
            "gke-gcloud-auth-plugin not found on PATH and could not locate "
            "google-cloud-sdk in PATH entries or environment variables. GKE authentication may fail."
        )

    def get_kube_context(self) -> str:
        """Pick the first Kubernetes context containing the GCP Project ID.

        Returns:
            The matching context name string.

        Raises:
            KubernetesControllerException: If no matching context is found.
        """
        try:
            contexts, _ = kubernetes.config.list_kube_config_contexts()
        except kubernetes.config.config_exception.ConfigException as e:
            raise KubernetesControllerException(
                f"Could not get kubernetes contexts for GKE project {self._gke_project}"
            ) from e

        for ctx in contexts:
            ctx_name = str(ctx.get("name", ""))
            if ctx_name.startswith("gke_"):
                parts = ctx_name.split("_")
                if len(parts) > 1 and self._gke_project == parts[1]:
                    return ctx_name
            elif self._gke_project and self._gke_project in ctx_name:
                return ctx_name

        raise KubernetesControllerException(
            f'The context for GKE project "{self._gke_project}" does not exist in the kubeconfig file.'
        )

    # ------------------------------------------------------------------
    # Generic helpers — eliminate per-resource-type boilerplate
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_match_labels(selector: V1LabelSelector, workload_name: str) -> dict[str, str]:
        """Extract ``match_labels`` from a Kubernetes label selector.

        Args:
            selector: The ``V1LabelSelector`` from a workload spec.
            workload_name: Human-readable workload identifier for error messages.

        Returns:
            A non-empty dict of label key/value pairs.

        Raises:
            KubernetesControllerException: If the selector has no ``match_labels``.
        """
        match_labels = selector.match_labels or {}
        if not match_labels:
            raise KubernetesControllerException(f"{workload_name} has no selector")
        return match_labels

    @staticmethod
    def _labels_to_selector(match_labels: dict[str, str]) -> str:
        """Convert a label dict to a comma-separated Kubernetes label selector string."""
        return ",".join(f"{k}={v}" for k, v in match_labels.items())

    def _list_workloads(
        self,
        list_namespaced: Callable[..., Any],
        list_all: Callable[..., Any],
        namespace: str | None,
        resource_label: str,
    ) -> dict[str, Any]:
        """Generic helper to list Kubernetes resources, namespaced or cluster-wide.

        Consolidates the duplicated pattern shared by ``get_deployments``,
        ``get_stateful_sets``, ``get_daemon_sets``, ``get_jobs``, and
        ``get_cron_jobs``.

        Args:
            list_namespaced: Bound method for namespaced listing (e.g. ``list_namespaced_deployment``).
            list_all: Bound method for cluster-wide listing (e.g. ``list_deployment_for_all_namespaces``).
            namespace: Target namespace, or ``None`` for all namespaces.
            resource_label: Human-readable resource type for error messages.

        Returns:
            Dict mapping ``"namespace/name"`` to the Kubernetes resource object.

        Raises:
            KubernetesControllerException: On API errors.
        """
        try:
            if namespace:
                ret = list_namespaced(namespace=namespace)
                return {f"{namespace}/{item.metadata.name}": item for item in ret.items}
            ret = list_all()
            return {f"{item.metadata.namespace}/{item.metadata.name}": item for item in ret.items}
        except Exception as e:
            raise KubernetesControllerException(f"Failed to get {resource_label}: {e}") from e

    def list_pods_for_workload(
        self,
        workload_name: str,
        namespace: str,
        workload_obj: Any,
        limit: int = 100,
        timeout: int = 30,
    ) -> list[V1Pod]:
        """List pods owned by an in-memory Deployment / StatefulSet / DaemonSet.

        Raises:
            KubernetesControllerException: If the workload has no selector.
        """
        spec = getattr(workload_obj, "spec", None)
        selector = getattr(spec, "selector", None) if spec is not None else None
        if selector is None:
            raise KubernetesControllerException(f"{workload_name} has no spec.selector")

        match_labels = self._extract_match_labels(selector, workload_name)
        # match_expressions cannot be reproduced from cached match_labels alone;
        # bypass the namespace pod cache for those workloads.
        has_match_expressions = bool(getattr(selector, "match_expressions", None))
        return self._list_pods_with_selector(
            namespace=namespace,
            label_selector=self._labels_to_selector(match_labels),
            limit=limit,
            timeout=timeout,
            match_labels=match_labels,
            skip_cache=has_match_expressions,
        )

    # ------------------------------------------------------------------
    # Deployment methods
    # ------------------------------------------------------------------

    def get_deployments(self, namespace: str | None = None) -> dict[str, V1Deployment]:
        """Fetch all Deployments in the given namespace or cluster-wide."""
        return self._list_workloads(
            self.apps_v1.list_namespaced_deployment,
            self.apps_v1.list_deployment_for_all_namespaces,
            namespace,
            "Deployments",
        )

    def list_all_replica_sets(
        self,
        namespace: str,
        *,
        page_size: int = 200,
        label_selector: str | None = None,
    ) -> list[V1ReplicaSet]:
        """List every ReplicaSet in ``namespace`` via server-side pagination.

        Raises:
            KubernetesControllerException: If any page request fails.
        """
        items: list[V1ReplicaSet] = []
        continue_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"namespace": namespace, "limit": page_size}
            if continue_token:
                kwargs["_continue"] = continue_token
            if label_selector:
                kwargs["label_selector"] = label_selector
            try:
                resp = self.apps_v1.list_namespaced_replica_set(**kwargs)
            except Exception as e:
                raise KubernetesControllerException(f"Failed to list ReplicaSets in {namespace}: {e}") from e
            items.extend(resp.items)
            continue_token = resp.metadata._continue
            if not continue_token:
                break
        return items

    def seed_deployment_replica_set_cache(self, namespace: str) -> None:
        """Cache ``namespace``'s ReplicaSets grouped by owning Deployment name.

        Cached per discovery cycle to avoid an N+1 namespace list per Deployment.
        On failure, leaves the cache empty so callers fall back to per-Deployment lookup.
        """
        try:
            replica_sets = self.list_all_replica_sets(namespace=namespace)
        except KubernetesControllerException as e:
            self.logger.warning(f"Failed to seed ReplicaSet cache for {namespace}: {e}")
            return

        grouped: dict[str, list[V1ReplicaSet]] = {}
        for rs in replica_sets:
            for owner in rs.metadata.owner_references or []:
                if owner.kind == WorkloadType.DEPLOYMENT:
                    grouped.setdefault(owner.name, []).append(rs)

        with self._rs_cache_lock:
            self._deployment_rs_cache[namespace] = grouped

    def clear_deployment_replica_set_cache(self, namespace: str | None = None) -> None:
        """Clear the per-cycle ReplicaSet cache (one namespace, or all when ``None``)."""
        with self._rs_cache_lock:
            if namespace is None:
                self._deployment_rs_cache.clear()
            else:
                self._deployment_rs_cache.pop(namespace, None)

    def get_deployment_latest_revision_info(self, deployment_name: str, namespace: str) -> RevisionInfo:
        """Return the pod-template-hash and revision of the newest ReplicaSet for ``deployment_name``.

        Uses the per-cycle ReplicaSet cache when seeded; otherwise falls back
        to a one-shot paginated namespace list.
        """
        with self._rs_cache_lock:
            namespace_cache = self._deployment_rs_cache.get(namespace)

        if namespace_cache is not None:
            replica_sets: list[V1ReplicaSet] = namespace_cache.get(deployment_name, [])
        else:
            try:
                replica_sets = self.list_all_replica_sets(namespace=namespace)
            except KubernetesControllerException as e:
                self.logger.warning(f"Failed to list replica sets for {deployment_name}: {e}")
                return RevisionInfo()

        latest_rs = None
        for rs in replica_sets:
            owners = rs.metadata.owner_references or []
            if any(owner.kind == WorkloadType.DEPLOYMENT and owner.name == deployment_name for owner in owners) and (
                latest_rs is None or rs.metadata.creation_timestamp > latest_rs.metadata.creation_timestamp
            ):
                latest_rs = rs

        if not latest_rs:
            return RevisionInfo()

        pod_template_hash = latest_rs.metadata.labels.get("pod-template-hash", "")
        annotations = latest_rs.metadata.annotations or {}
        revision_str = annotations.get("deployment.kubernetes.io/revision")
        revision_number = int(revision_str) if revision_str and revision_str.isdigit() else None
        return RevisionInfo(hash=pod_template_hash, number=revision_number)

    # ------------------------------------------------------------------
    # StatefulSet methods
    # ------------------------------------------------------------------

    def get_stateful_sets(self, namespace: str | None = None) -> dict[str, V1StatefulSet]:
        """Fetch all StatefulSets in the given namespace or cluster-wide."""
        return self._list_workloads(
            self.apps_v1.list_namespaced_stateful_set,
            self.apps_v1.list_stateful_set_for_all_namespaces,
            namespace,
            "StatefulSets",
        )

    def get_stateful_set_latest_revision_info(self, stateful_set_name: str, namespace: str) -> RevisionInfo:
        """Retrieve revision information for a StatefulSet.

        Args:
            stateful_set_name: Name of the StatefulSet.
            namespace: Kubernetes namespace.

        Returns:
            ``RevisionInfo`` populated with update/current revision hashes, partition, and strategy.
        """
        try:
            sts = self.apps_v1.read_namespaced_stateful_set(name=stateful_set_name, namespace=namespace)
        except Exception as e:
            self.logger.warning(f"Failed to read StatefulSet {stateful_set_name} for revision info: {e}")
            return RevisionInfo()

        update_strategy = sts.spec.update_strategy
        strategy_type = update_strategy.type if update_strategy else "RollingUpdate"
        partition = 0
        if update_strategy and strategy_type == "RollingUpdate":
            rolling_update = update_strategy.rolling_update
            if rolling_update and rolling_update.partition is not None:
                partition = rolling_update.partition

        return RevisionInfo(
            hash=sts.status.update_revision or "",
            current_hash=sts.status.current_revision or "",
            partition=partition,
            strategy=strategy_type,
        )

    # ------------------------------------------------------------------
    # DaemonSet methods
    # ------------------------------------------------------------------

    def get_daemon_sets(self, namespace: str | None = None) -> dict[str, V1DaemonSet]:
        """Fetch all DaemonSets in the given namespace or cluster-wide."""
        return self._list_workloads(
            self.apps_v1.list_namespaced_daemon_set,
            self.apps_v1.list_daemon_set_for_all_namespaces,
            namespace,
            "DaemonSets",
        )

    # ------------------------------------------------------------------
    # Job / CronJob methods
    # ------------------------------------------------------------------

    def get_jobs(self, namespace: str | None = None) -> dict[str, V1Job]:
        """Fetch all Jobs in the given namespace or cluster-wide."""
        return self._list_workloads(
            self.batch_v1.list_namespaced_job,
            self.batch_v1.list_job_for_all_namespaces,
            namespace,
            "Jobs",
        )

    def get_cron_jobs(self, namespace: str | None = None) -> dict[str, V1CronJob]:
        """Fetch all CronJobs in the given namespace or cluster-wide."""
        return self._list_workloads(
            self.batch_v1.list_namespaced_cron_job,
            self.batch_v1.list_cron_job_for_all_namespaces,
            namespace,
            "CronJobs",
        )

    def list_pods_by_job(self, job_name: str, namespace: str, limit: int = 100, timeout: int = 30) -> list[V1Pod]:
        """List pods managed by a Job.

        Jobs may not have ``match_labels`` on their selector; falls back to
        ``controller-uid`` from the Job's own labels.
        """
        try:
            job = self.batch_v1.read_namespaced_job(name=job_name, namespace=namespace)
        except Exception as e:
            raise KubernetesControllerException(f"Could not read Job {job_name}: {e}") from e

        match_labels = job.spec.selector.match_labels or {}
        if not match_labels:
            controller_uid = job.metadata.labels.get("controller-uid")
            if controller_uid:
                match_labels = {"controller-uid": controller_uid}
            else:
                raise KubernetesControllerException(f"Job {job_name} has no selector")

        label_selector = self._labels_to_selector(match_labels)
        return self._list_pods_with_selector(
            namespace=namespace,
            label_selector=label_selector,
            limit=limit,
            timeout=timeout,
            match_labels=match_labels,
        )

    # ------------------------------------------------------------------
    # Pod listing with pagination
    # ------------------------------------------------------------------

    def list_all_pods(
        self,
        namespace: str,
        *,
        page_size: int = 200,
    ) -> list[V1Pod]:
        """List every pod in ``namespace`` via server-side pagination.

        Raises:
            KubernetesControllerException: If any page request fails.
        """
        items: list[V1Pod] = []
        continue_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"namespace": namespace, "limit": page_size}
            if continue_token:
                kwargs["_continue"] = continue_token
            try:
                resp = self.core_v1.list_namespaced_pod(**kwargs)
            except Exception as e:
                raise KubernetesControllerException(f"Failed to list pods in {namespace}: {e}") from e
            items.extend(resp.items)
            continue_token = resp.metadata._continue
            if not continue_token:
                break
        return items

    def seed_namespace_pod_cache(self, namespace: str) -> None:
        """Cache every pod in ``namespace`` so per-workload lookups stay in memory.

        Cached per discovery cycle. On failure, leaves the cache empty so
        callers fall back to the per-workload API path.
        """
        try:
            pods = self.list_all_pods(namespace=namespace)
        except KubernetesControllerException as e:
            self.logger.warning(f"Failed to seed namespace pod cache for {namespace}: {e}")
            return

        with self._namespace_pod_cache_lock:
            self._namespace_pod_cache[namespace] = pods

    def clear_namespace_pod_cache(self, namespace: str | None = None) -> None:
        """Clear the per-cycle namespace pod cache (one namespace, or all when ``None``)."""
        with self._namespace_pod_cache_lock:
            if namespace is None:
                self._namespace_pod_cache.clear()
            else:
                self._namespace_pod_cache.pop(namespace, None)

    def _list_pods_with_selector(
        self,
        namespace: str,
        label_selector: str,
        limit: int,
        timeout: int,
        match_labels: dict[str, str],
        skip_cache: bool = False,
    ) -> list[V1Pod]:
        """List pods matching ``label_selector`` with pagination and timeout.

        Uses the per-cycle namespace pod cache when seeded. ``skip_cache=True``
        forces the API path — required when the workload selector has
        ``match_expressions`` (which the cached ``match_labels`` filter cannot
        reproduce server-side semantics for).
        """
        if not skip_cache:
            with self._namespace_pod_cache_lock:
                cached_pods = self._namespace_pod_cache.get(namespace)
            if cached_pods is not None:
                return [
                    p
                    for p in cached_pods
                    if all((p.metadata.labels or {}).get(k) == v for k, v in match_labels.items())
                ]

        start = time.time()
        pods: list[V1Pod] = []
        _continue: str | None = None

        while time.time() - start < timeout:
            try:
                ret = self.core_v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=label_selector,
                    _continue=_continue,
                    limit=limit,
                )
                pods.extend(ret.items)
                _continue = ret.metadata._continue
                if not _continue:
                    break
            except Exception as e:
                self.logger.warning(f"Error listing pods with selector {label_selector}: {e}")
                time.sleep(1)
                if time.time() - start >= timeout:
                    break

        return pods
