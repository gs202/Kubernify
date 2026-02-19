"""Kubernetes workload discovery for Kubernify.

Discovers, inspects, and collects metadata for all relevant workload types
(Deployments, StatefulSets, DaemonSets, Jobs, CronJobs) in a given namespace.
"""

from __future__ import annotations

import concurrent.futures
import logging
from collections.abc import Callable

from kubernetes.client import V1Pod

from .kubernetes_controller import KubernetesController, KubernetesControllerException
from .models import (
    DEFAULT_THREAD_POOL_WORKERS,
    KubernetesWorkload,
    RevisionInfo,
    WorkloadInspectionResult,
    WorkloadType,
)


class WorkloadDiscovery:
    def __init__(
        self,
        k8s_controller: KubernetesController,
        include_statefulsets: bool = True,
        include_daemonsets: bool = True,
        include_jobs: bool = True
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.k8s_controller = k8s_controller

        # Mapping workload types to their fetch methods
        self._fetch_methods: dict[WorkloadType, Callable[..., dict[str, KubernetesWorkload]]] = {
            WorkloadType.DEPLOYMENT: self.k8s_controller.get_deployments,
        }
        if include_statefulsets:
            self._fetch_methods[WorkloadType.STATEFUL_SET] = self.k8s_controller.get_stateful_sets
        if include_daemonsets:
            self._fetch_methods[WorkloadType.DAEMON_SET] = self.k8s_controller.get_daemon_sets
        if include_jobs:
            self._fetch_methods[WorkloadType.JOB] = self.k8s_controller.get_jobs
            self._fetch_methods[WorkloadType.CRON_JOB] = self.k8s_controller.get_cron_jobs

        # Mapping workload types to their pod listing methods
        self._pod_methods: dict[WorkloadType, Callable[..., list[V1Pod]]] = {
            WorkloadType.DEPLOYMENT: self.k8s_controller.list_pods_by_deployment,
        }
        if include_statefulsets:
            self._pod_methods[WorkloadType.STATEFUL_SET] = self.k8s_controller.list_pods_by_stateful_set
        if include_daemonsets:
            self._pod_methods[WorkloadType.DAEMON_SET] = self.k8s_controller.list_pods_by_daemon_set
        if include_jobs:
            self._pod_methods[WorkloadType.JOB] = self.k8s_controller.list_pods_by_job

        # Mapping workload types to their revision info methods
        self._revision_methods: dict[WorkloadType, Callable[[str, str], RevisionInfo]] = {
            WorkloadType.DEPLOYMENT: self.k8s_controller.get_deployment_latest_revision_info,
        }
        if include_statefulsets:
            self._revision_methods[WorkloadType.STATEFUL_SET] = (
                self.k8s_controller.get_stateful_set_latest_revision_info
            )

    def fetch_all_workloads(self, namespace: str) -> dict[WorkloadType, list[KubernetesWorkload]]:
        """Fetches all relevant workloads from the cluster."""
        workloads: dict[WorkloadType, list[KubernetesWorkload]] = {}

        for w_type, fetch_method in self._fetch_methods.items():
            try:
                items = fetch_method(namespace=namespace)
                workloads[w_type] = list(items.values())
                self.logger.info(f"Fetching {len(items.values())} {w_type}s")
            except Exception as e:
                self.logger.error(f"Failed to fetch {w_type}s: {e}")
                raise

        return workloads

    def inspect_workload(
        self,
        workload_name: str,
        workload_type: str,
        namespace: str,
        workload_obj: KubernetesWorkload | None = None,
    ) -> WorkloadInspectionResult:
        """Gathers detailed info for a single workload."""
        result = WorkloadInspectionResult(name=workload_name, type=workload_type, namespace=namespace)

        # Extract PodSpec
        if workload_obj:
            try:
                if workload_type == WorkloadType.CRON_JOB:
                    result.pod_spec = workload_obj.spec.job_template.spec.template.spec
                elif hasattr(workload_obj, "spec") and hasattr(workload_obj.spec, "template"):
                    result.pod_spec = workload_obj.spec.template.spec
            except AttributeError:
                self.logger.warning(f"Could not extract pod_spec from {workload_name}")

        # Get Latest Revision
        if workload_type in self._revision_methods:
            try:
                result.latest_revision = self._revision_methods[workload_type](workload_name, namespace)
            except Exception as e:
                self.logger.warning(f"Failed to get revision for {workload_name}: {e}")

        # Special handling for DaemonSet revision
        if workload_type == WorkloadType.DAEMON_SET:
            result.latest_revision = self._get_daemonset_revision(workload_name=workload_name, namespace=namespace)

        # Get Pods
        if workload_type in self._pod_methods:
            try:
                result.pods = self._pod_methods[workload_type](workload_name, namespace)
            except KubernetesControllerException:
                result.pods = []
            except Exception as e:
                self.logger.error(f"Error listing pods for {workload_name}: {e}")
                raise

        return result

    def _get_daemonset_revision(self, workload_name: str, namespace: str) -> RevisionInfo | None:
        """Helper to extract DaemonSet revision from pod template labels."""
        try:
            ds = self.k8s_controller._apps_v1.read_namespaced_daemon_set(name=workload_name, namespace=namespace)
            labels = ds.spec.template.metadata.labels or {}
            revision_hash = labels.get('controller-revision-hash', '')
            if revision_hash:
                return RevisionInfo(hash=revision_hash)
            self.logger.warning(f"DaemonSet {workload_name} pod template has no 'controller-revision-hash' label")
        except Exception as e:
            self.logger.warning(f"Failed to get DaemonSet revision for {workload_name}: {e}")

    def discover_cluster_state(
        self, namespace: str, skip_patterns: list[str] | None = None,
    ) -> tuple[list[WorkloadInspectionResult], list[str]]:
        """Orchestrates the discovery of all workloads and their details.

        Args:
            namespace: Kubernetes namespace to discover workloads in.
            skip_patterns: Optional list of substring patterns; workloads whose name
                matches any pattern are excluded from inspection entirely.

        Returns:
            Tuple of (inspection_results, skipped_workload_names).
        """
        self.logger.info(f"Discover cluster state for {namespace}")
        all_workloads = self.fetch_all_workloads(namespace=namespace)
        inspection_results = []
        skipped_workloads: list[str] = []
        patterns = skip_patterns or []

        tasks = []
        for workload_type, workloads in all_workloads.items():
            for workload in workloads:
                workload_name = workload.metadata.name
                # Skip workloads whose name matches any skip pattern
                if patterns and any(p in workload_name for p in patterns):
                    self.logger.info(f"Skipping inspection of workload {workload_name} (matched skip pattern)")
                    skipped_workloads.append(workload_name)
                    continue
                tasks.append({
                    "workload_name": workload_name,
                    "workload_type": workload_type,
                    "namespace": namespace,
                    "workload_obj": workload
                })

        total_workloads = len(tasks)
        with concurrent.futures.ThreadPoolExecutor(max_workers=DEFAULT_THREAD_POOL_WORKERS) as executor:
            future_to_task = {executor.submit(self.inspect_workload, **task): task for task in tasks}

            for idx, future in enumerate(concurrent.futures.as_completed(future_to_task), start=1):
                task = future_to_task[future]
                workload_name = task["workload_name"]
                try:
                    result = future.result()
                    self.logger.info(f"Workload {workload_name} inspected {idx}/{total_workloads}")
                    inspection_results.append(result)
                except Exception as e:
                    self.logger.error(f"Failed to inspect workload {workload_name}: {e}")
                    # Add a partial result to indicate failure
                    inspection_results.append(WorkloadInspectionResult(
                        name=workload_name,
                        type=task["workload_type"],
                        namespace=namespace,
                        latest_revision=None,
                        pods=[],
                        pod_spec=None,
                        error=str(e)
                    ))

        return inspection_results, skipped_workloads
