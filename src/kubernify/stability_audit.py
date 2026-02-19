"""Stability auditing for Kubernetes workloads in Kubernify.

Performs convergence, revision-consistency, pod-health, scheduling, and
job-completion checks against discovered workloads.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from kubernetes.client import V1DaemonSet, V1Job, V1Pod

from .kubernetes_controller import KubernetesController
from .models import (
    KubernetesWorkload,
    StabilityAuditResult,
    WorkloadInspectionResult,
    WorkloadType,
)


class StabilityAuditor:
    def __init__(self, k8s_controller: KubernetesController) -> None:
        self.logger = logging.getLogger(__name__)
        self.k8s_controller = k8s_controller

    @staticmethod
    def check_controller_convergence(workload: KubernetesWorkload) -> bool:
        """Checks if observedGeneration >= generation."""
        if not hasattr(workload, "metadata") or not hasattr(workload.metadata, "generation"):
            return True
        if not hasattr(workload, "status") or workload.status is None:
            return False
        if not hasattr(workload.status, "observed_generation") or workload.status.observed_generation is None:
            return False
        return workload.status.observed_generation >= workload.metadata.generation

    @staticmethod
    def check_revision_consistency(pods: list[V1Pod], expected_revision_hash: str, workload_type: str) -> list[str]:
        """Checks if the pod's revision hash matches expected_revision_hash."""
        errors = []
        if not expected_revision_hash:
            return ["Expected revision hash is missing"]

        for pod in pods:
            labels = pod.metadata.labels or {}
            actual_hash = None
            if workload_type == WorkloadType.DEPLOYMENT:
                actual_hash = labels.get("pod-template-hash")
            elif workload_type in [WorkloadType.STATEFUL_SET, WorkloadType.DAEMON_SET]:
                actual_hash = labels.get("controller-revision-hash")

            if (
                workload_type in [WorkloadType.DEPLOYMENT, WorkloadType.STATEFUL_SET, WorkloadType.DAEMON_SET]
                and actual_hash != expected_revision_hash
            ):
                errors.append(f"Pod {pod.metadata.name} has hash {actual_hash}, expected {expected_revision_hash}")

        return errors

    @staticmethod
    def check_pod_health(pod: V1Pod, restart_threshold: int = 3, min_uptime_sec: int = 0) -> list[str]:
        """Checks pod health (Ready, not terminating, restarts, uptime)."""
        errors = []
        pod_name = pod.metadata.name

        if pod.metadata.deletion_timestamp is not None:
            return [f"Pod {pod_name} is terminating"]

        ready_cond = next((c for c in (pod.status.conditions or []) if c.type == "Ready"), None)
        if not ready_cond or ready_cond.status != "True":
            errors.append(f"Pod {pod_name} is not Ready")

        for status in pod.status.container_statuses or []:
            if status.restart_count >= restart_threshold:
                errors.append(f"Container {status.name} in pod {pod_name} has {status.restart_count} restarts")
            if status.state and status.state.waiting:
                reason = status.state.waiting.reason
                if reason in ["ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff"]:
                    errors.append(f"Container {status.name} in pod {pod_name} is in {reason}")

        if min_uptime_sec > 0:
            start_time = pod.status.start_time
            if start_time:
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
                uptime = (datetime.now(timezone.utc) - start_time).total_seconds()
                if uptime < min_uptime_sec:
                    errors.append(f"Pod {pod_name} uptime {uptime:.1f}s < {min_uptime_sec}s")
            else:
                errors.append(f"Pod {pod_name} has not started yet")

        return errors

    @staticmethod
    def verify_daemon_set_scheduling(daemon_set: V1DaemonSet) -> list[str]:
        """Checks DaemonSet scheduling status."""
        errors = []
        status = daemon_set.status
        if not status:
            return ["DaemonSet status is missing"]

        desired = status.desired_number_scheduled or 0
        available = status.number_available or 0
        updated = status.updated_number_scheduled or 0

        if available < desired:
            errors.append(f"DaemonSet available pods {available} < desired {desired}")
        if updated < desired:
            errors.append(f"DaemonSet updated pods {updated} < desired {desired}")

        return errors

    @staticmethod
    def verify_job_status(job: V1Job) -> list[str]:
        """Checks Job completion status."""
        errors = []
        status = job.status
        if not status:
            return ["Job status is missing"]

        if (status.succeeded or 0) < 1:
            errors.append("Job has not succeeded yet")

        failed = status.failed or 0
        backoff_limit = job.spec.backoff_limit if job.spec and job.spec.backoff_limit is not None else 6
        if failed > backoff_limit:
            errors.append(f"Job failed count {failed} > backoffLimit {backoff_limit}")

        return errors

    def _get_workload_object(self, name: str, namespace: str, workload_type: str) -> KubernetesWorkload | None:
        """Helper to fetch the actual Kubernetes object."""
        try:
            if workload_type == WorkloadType.DEPLOYMENT:
                return self.k8s_controller._apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
            elif workload_type == WorkloadType.STATEFUL_SET:
                return self.k8s_controller._apps_v1.read_namespaced_stateful_set(name=name, namespace=namespace)
            elif workload_type == WorkloadType.DAEMON_SET:
                return self.k8s_controller._apps_v1.read_namespaced_daemon_set(name=name, namespace=namespace)
            elif workload_type == WorkloadType.JOB:
                return self.k8s_controller._batch_v1.read_namespaced_job(name=name, namespace=namespace)
            elif workload_type == WorkloadType.CRON_JOB:
                return self.k8s_controller._batch_v1.read_namespaced_cron_job(name=name, namespace=namespace)
        except Exception as e:
            self.logger.warning(f"Failed to fetch {workload_type} {name}: {e}")
        return None

    def audit_workload(
        self,
        workload_info: WorkloadInspectionResult,
        restart_threshold: int = 3,
        min_uptime_sec: int = 0,
    ) -> StabilityAuditResult:
        """Orchestrates all stability checks.

        Args:
            workload_info: Inspection result containing workload metadata and pods.
            restart_threshold: Maximum acceptable restart count per container.
            min_uptime_sec: Minimum pod uptime in seconds.

        Returns:
            StabilityAuditResult with convergence, revision, health, scheduling, and job status.
        """
        name = workload_info.name
        namespace = workload_info.namespace
        w_type = workload_info.type
        pods = workload_info.pods
        latest_revision = workload_info.latest_revision

        result = StabilityAuditResult()

        if not name or not namespace or not w_type:
            result.errors.append("Invalid workload info provided")
            return result

        workload_obj = self._get_workload_object(name=name, namespace=namespace, workload_type=w_type)
        if not workload_obj:
            result.errors.append(f"Could not fetch workload object {name}")
            return result

        # 1. Convergence
        if w_type in [WorkloadType.DEPLOYMENT, WorkloadType.STATEFUL_SET, WorkloadType.DAEMON_SET]:
            result.converged = self.check_controller_convergence(workload=workload_obj)
            if not result.converged:
                result.errors.append("Workload not converged (observedGeneration < generation)")
        else:
            result.converged = True

        # 2. Revision Consistency
        if w_type in [WorkloadType.DEPLOYMENT, WorkloadType.STATEFUL_SET, WorkloadType.DAEMON_SET]:
            if latest_revision and latest_revision.hash:
                rev_errors = self.check_revision_consistency(
                    pods=pods,
                    expected_revision_hash=latest_revision.hash,
                    workload_type=w_type,
                )
                if not rev_errors:
                    result.revision_consistent = True
                else:
                    result.errors.extend(rev_errors)
            else:
                result.errors.append("Could not determine latest revision hash")
        else:
            result.revision_consistent = True

        # 3. Pod Health
        pod_errors = []
        for pod in pods:
            pod_errors.extend(
                self.check_pod_health(pod=pod, restart_threshold=restart_threshold, min_uptime_sec=min_uptime_sec),
            )

        if not pod_errors:
            result.pods_healthy = True
        else:
            result.errors.extend(pod_errors)

        # 4. DaemonSet Scheduling
        if w_type == WorkloadType.DAEMON_SET:
            ds_errors = self.verify_daemon_set_scheduling(daemon_set=workload_obj)
            if not ds_errors:
                result.scheduling_complete = True
            else:
                result.errors.extend(ds_errors)
        else:
            result.scheduling_complete = True

        # 5. Job Status
        if w_type == WorkloadType.JOB:
            job_errors = self.verify_job_status(job=workload_obj)
            if not job_errors:
                result.job_complete = True
            else:
                result.errors.extend(job_errors)
        else:
            result.job_complete = True

        return result
