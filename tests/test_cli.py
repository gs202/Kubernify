"""Unit tests for the CLI argument parsing and helper functions in kubernify.cli."""

from __future__ import annotations

import argparse
import logging
from unittest.mock import MagicMock, mock_open, patch

import pytest

from kubernify.cli import (
    _get_current_namespace,
    _parse_comma_list,
    _setup_logging,
    build_reverse_alias_map,
    load_component_aliases,
    load_manifest,
    parse_args,
    run_verification,
)

# ---------------------------------------------------------------------------
# Argument parsing tests
# ---------------------------------------------------------------------------


class TestParseArgs:
    """Tests for CLI argument parsing via ``parse_args``."""

    def test_parse_args_with_context(self) -> None:
        """Verify --context sets args.context correctly."""
        args = parse_args(
            [
                "--context",
                "my-cluster-context",
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
            ]
        )

        assert args.context == "my-cluster-context"
        assert args.gke_project is None

    def test_parse_args_with_gke_project(self) -> None:
        """Verify --gke-project sets args.gke_project correctly."""
        args = parse_args(
            [
                "--gke-project",
                "my-gcp-project",
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
            ]
        )

        assert args.gke_project == "my-gcp-project"
        assert args.context is None

    def test_parse_args_context_and_gke_project_mutually_exclusive(self) -> None:
        """Verify --context and --gke-project together raises SystemExit."""
        with pytest.raises(SystemExit):
            parse_args(
                [
                    "--context",
                    "my-context",
                    "--gke-project",
                    "my-project",
                    "--manifest",
                    '{"backend": "v1.0.0"}',
                    "--anchor",
                    "my-app",
                ]
            )

    def test_parse_args_anchor_required(self) -> None:
        """Verify missing --anchor raises SystemExit."""
        with pytest.raises(SystemExit):
            parse_args(
                [
                    "--manifest",
                    '{"backend": "v1.0.0"}',
                ]
            )

    def test_parse_args_manifest_required(self) -> None:
        """Verify missing --manifest raises SystemExit."""
        with pytest.raises(SystemExit):
            parse_args(
                [
                    "--anchor",
                    "my-app",
                ]
            )

    def test_parse_args_defaults(self) -> None:
        """Verify default values for timeout, restart_threshold, and other flags."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
            ]
        )

        assert args.timeout == 300
        assert args.restart_threshold == 3
        assert args.min_uptime == 0
        assert args.allow_zero_replicas is False
        assert args.dry_run is False
        assert args.include_statefulsets is False
        assert args.include_daemonsets is False
        assert args.include_jobs is False


# ---------------------------------------------------------------------------
# Namespace resolution tests
# ---------------------------------------------------------------------------


class TestGetCurrentNamespace:
    """Tests for ``_get_current_namespace`` resolution logic."""

    def test_get_current_namespace_from_kubeconfig(self) -> None:
        """Verify namespace is read from kubeconfig active context."""
        mock_active_context = {
            "context": {"namespace": "production"},
        }
        with patch("kubernetes.config.list_kube_config_contexts", return_value=([], mock_active_context)):
            result = _get_current_namespace()

        assert result == "production"

    def test_get_current_namespace_in_cluster(self) -> None:
        """Verify namespace is read from in-cluster service account file."""
        with (
            patch("kubernetes.config.list_kube_config_contexts", side_effect=Exception("no kubeconfig")),
            patch("builtins.open", mock_open(read_data="kube-system\n")),
        ):
            result = _get_current_namespace()

        assert result == "kube-system"

    def test_get_current_namespace_fallback(self) -> None:
        """Verify fallback to 'default' when both kubeconfig and in-cluster fail."""
        with (
            patch("kubernetes.config.list_kube_config_contexts", side_effect=Exception("no kubeconfig")),
            patch("builtins.open", side_effect=FileNotFoundError),
        ):
            result = _get_current_namespace()

        assert result == "default"


# ---------------------------------------------------------------------------
# Logging setup tests
# ---------------------------------------------------------------------------


class TestSetupLogging:
    """Tests for ``_setup_logging`` configuration."""

    def test_setup_logging(self) -> None:
        """Verify _setup_logging configures root logger with basicConfig."""
        with patch("logging.basicConfig") as mock_basic_config:
            _setup_logging()

        mock_basic_config.assert_called_once()
        call_kwargs = mock_basic_config.call_args[1]
        assert call_kwargs["level"] == logging.INFO


# ---------------------------------------------------------------------------
# Manifest loading tests
# ---------------------------------------------------------------------------


class TestLoadManifest:
    """Tests for ``load_manifest`` JSON parsing."""

    def test_load_manifest_valid(self) -> None:
        """Verify valid JSON string is parsed correctly."""
        result = load_manifest('{"backend": "v1.2.3", "frontend": "v1.2.4"}')

        assert result == {"backend": "v1.2.3", "frontend": "v1.2.4"}

    def test_load_manifest_empty(self) -> None:
        """Verify ValueError is raised on empty string."""
        with pytest.raises(ValueError, match="must not be empty"):
            load_manifest("")

    def test_load_manifest_invalid_json(self) -> None:
        """Verify ValueError is raised on invalid JSON."""
        with pytest.raises(ValueError, match="not valid JSON"):
            load_manifest("{invalid json}")


# ---------------------------------------------------------------------------
# _parse_comma_list tests
# ---------------------------------------------------------------------------


class TestParseCommaList:
    """Tests for ``_parse_comma_list`` helper."""

    def test_parse_comma_list_none(self) -> None:
        """Verify None input returns empty list."""
        result = _parse_comma_list(None)

        assert result == []

    def test_parse_comma_list_empty_string(self) -> None:
        """Verify empty string returns empty list."""
        result = _parse_comma_list("")

        assert result == []

    def test_parse_comma_list_single_item(self) -> None:
        """Verify single item is returned as a one-element list."""
        result = _parse_comma_list("frontend")

        assert result == ["frontend"]

    def test_parse_comma_list_multiple_items(self) -> None:
        """Verify multiple comma-separated items are split correctly."""
        result = _parse_comma_list("frontend, backend, api")

        assert result == ["frontend", "backend", "api"]

    def test_parse_comma_list_strips_whitespace(self) -> None:
        """Verify leading/trailing whitespace is stripped from each item."""
        result = _parse_comma_list("  frontend ,  backend  ,api  ")

        assert result == ["frontend", "backend", "api"]

    def test_parse_comma_list_skips_empty_segments(self) -> None:
        """Verify empty segments from trailing commas are excluded."""
        result = _parse_comma_list("frontend,,backend,")

        assert result == ["frontend", "backend"]


# ---------------------------------------------------------------------------
# Explicit flag value parsing tests
# ---------------------------------------------------------------------------


class TestParseArgsExplicitValues:
    """Tests for CLI flags with explicitly provided values."""

    def test_parse_args_namespace_explicit(self) -> None:
        """Verify --namespace sets args.namespace to the provided value."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--namespace",
                "staging",
            ]
        )

        assert args.namespace == "staging"

    def test_parse_args_timeout_explicit(self) -> None:
        """Verify --timeout sets args.timeout to the provided value."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--timeout",
                "600",
            ]
        )

        assert args.timeout == 600

    def test_parse_args_restart_threshold_explicit(self) -> None:
        """Verify --restart-threshold sets args.restart_threshold to the provided value."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--restart-threshold",
                "10",
            ]
        )

        assert args.restart_threshold == 10

    def test_parse_args_min_uptime_explicit(self) -> None:
        """Verify --min-uptime sets args.min_uptime to the provided value."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--min-uptime",
                "60",
            ]
        )

        assert args.min_uptime == 60

    def test_parse_args_allow_zero_replicas_flag(self) -> None:
        """Verify --allow-zero-replicas sets the flag to True."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--allow-zero-replicas",
            ]
        )

        assert args.allow_zero_replicas is True

    def test_parse_args_dry_run_flag(self) -> None:
        """Verify --dry-run sets the flag to True."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--dry-run",
            ]
        )

        assert args.dry_run is True

    def test_parse_args_include_statefulsets_flag(self) -> None:
        """Verify --include-statefulsets sets the flag to True."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--include-statefulsets",
            ]
        )

        assert args.include_statefulsets is True

    def test_parse_args_no_include_statefulsets_flag(self) -> None:
        """Verify --no-include-statefulsets sets the flag to False."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--no-include-statefulsets",
            ]
        )

        assert args.include_statefulsets is False

    def test_parse_args_include_daemonsets_flag(self) -> None:
        """Verify --include-daemonsets sets the flag to True."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--include-daemonsets",
            ]
        )

        assert args.include_daemonsets is True

    def test_parse_args_no_include_daemonsets_flag(self) -> None:
        """Verify --no-include-daemonsets sets the flag to False."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--no-include-daemonsets",
            ]
        )

        assert args.include_daemonsets is False

    def test_parse_args_include_jobs_flag(self) -> None:
        """Verify --include-jobs sets the flag to True."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--include-jobs",
            ]
        )

        assert args.include_jobs is True

    def test_parse_args_no_include_jobs_flag(self) -> None:
        """Verify --no-include-jobs sets the flag to False."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--no-include-jobs",
            ]
        )

        assert args.include_jobs is False

    def test_parse_args_required_workloads(self) -> None:
        """Verify --required-workloads stores the raw comma-separated string."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--required-workloads",
                "frontend, api",
            ]
        )

        assert args.required_workloads == "frontend, api"

    def test_parse_args_skip_containers(self) -> None:
        """Verify --skip-containers stores the raw comma-separated string."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--skip-containers",
                "redis, sidecar",
            ]
        )

        assert args.skip_containers == "redis, sidecar"


# ---------------------------------------------------------------------------
# run_verification tests (dry-run and timeout)
# ---------------------------------------------------------------------------


class TestRunVerification:
    """Tests for ``run_verification`` execution flow."""

    def test_dry_run_passes_when_all_versions_match(self) -> None:
        """Verify --dry-run exits with 0 when all versions match and workloads are stable."""
        args = argparse.Namespace(
            manifest='{"backend": "v1.2.3"}',
            context="test-context",
            gke_project=None,
            namespace="default",
            anchor="my-app",
            timeout=300,
            restart_threshold=3,
            min_uptime=0,
            allow_zero_replicas=False,
            dry_run=True,
            include_statefulsets=False,
            include_daemonsets=False,
            include_jobs=False,
            required_workloads=None,
            skip_containers=None,
            component_aliases=None,
        )

        mock_controller = MagicMock()
        mock_discovery = MagicMock()
        mock_auditor = MagicMock()

        # Build a mock pod with the expected image
        mock_pod = MagicMock()
        mock_pod.metadata.name = "backend-pod-xyz"
        mock_pod.metadata.namespace = "default"
        mock_pod.metadata.labels = {"app": "backend", "pod-template-hash": "abc12"}
        mock_pod.metadata.deletion_timestamp = None
        mock_pod.spec.node_name = "node-1"
        mock_pod.spec.containers = [MagicMock(image="registry.example.com/org/my-app/backend:v1.2.3")]
        mock_pod.spec.init_containers = None
        mock_pod.status.phase = "Running"
        mock_pod.status.pod_ip = "10.0.0.1"
        mock_pod.status.start_time = "2025-01-01T00:00:00Z"

        from kubernify.models import RevisionInfo, StabilityAuditResult, WorkloadInspectionResult

        workload = WorkloadInspectionResult(
            name="backend-deployment",
            type="Deployment",
            namespace="default",
            latest_revision=RevisionInfo(hash="abc12"),
            pods=[mock_pod],
            pod_spec=mock_pod.spec,
        )

        mock_discovery.discover_cluster_state.return_value = ([workload], [])
        mock_auditor.audit_workload.return_value = StabilityAuditResult(
            converged=True,
            revision_consistent=True,
            pods_healthy=True,
            scheduling_complete=True,
            job_complete=True,
            errors=[],
        )

        with (
            patch("kubernify.cli.KubernetesController", return_value=mock_controller),
            patch("kubernify.cli.WorkloadDiscovery", return_value=mock_discovery),
            patch("kubernify.cli.StabilityAuditor", return_value=mock_auditor),
        ):
            exit_code = run_verification(args=args)

        assert exit_code == 0

    def test_dry_run_fails_on_version_mismatch(self) -> None:
        """Verify --dry-run exits with 1 when a version mismatch is detected."""
        args = argparse.Namespace(
            manifest='{"backend": "v2.0.0"}',
            context="test-context",
            gke_project=None,
            namespace="default",
            anchor="my-app",
            timeout=300,
            restart_threshold=3,
            min_uptime=0,
            allow_zero_replicas=False,
            dry_run=True,
            include_statefulsets=False,
            include_daemonsets=False,
            include_jobs=False,
            required_workloads=None,
            skip_containers=None,
            component_aliases=None,
        )

        mock_controller = MagicMock()
        mock_discovery = MagicMock()
        mock_auditor = MagicMock()

        mock_pod = MagicMock()
        mock_pod.metadata.name = "backend-pod-xyz"
        mock_pod.metadata.namespace = "default"
        mock_pod.metadata.labels = {"app": "backend", "pod-template-hash": "abc12"}
        mock_pod.metadata.deletion_timestamp = None
        mock_pod.spec.node_name = "node-1"
        mock_pod.spec.containers = [MagicMock(image="registry.example.com/org/my-app/backend:v1.2.3")]
        mock_pod.spec.init_containers = None
        mock_pod.status.phase = "Running"
        mock_pod.status.pod_ip = "10.0.0.1"
        mock_pod.status.start_time = "2025-01-01T00:00:00Z"

        from kubernify.models import RevisionInfo, StabilityAuditResult, WorkloadInspectionResult

        workload = WorkloadInspectionResult(
            name="backend-deployment",
            type="Deployment",
            namespace="default",
            latest_revision=RevisionInfo(hash="abc12"),
            pods=[mock_pod],
            pod_spec=mock_pod.spec,
        )

        mock_discovery.discover_cluster_state.return_value = ([workload], [])
        mock_auditor.audit_workload.return_value = StabilityAuditResult(
            converged=True,
            revision_consistent=True,
            pods_healthy=True,
            scheduling_complete=True,
            job_complete=True,
            errors=[],
        )

        with (
            patch("kubernify.cli.KubernetesController", return_value=mock_controller),
            patch("kubernify.cli.WorkloadDiscovery", return_value=mock_discovery),
            patch("kubernify.cli.StabilityAuditor", return_value=mock_auditor),
        ):
            exit_code = run_verification(args=args)

        assert exit_code == 1

    def test_timeout_returns_exit_code_2(self) -> None:
        """Verify run_verification returns exit code 2 when timeout is exceeded."""
        args = argparse.Namespace(
            manifest='{"backend": "v1.2.3"}',
            context="test-context",
            gke_project=None,
            namespace="default",
            anchor="my-app",
            timeout=5,
            restart_threshold=3,
            min_uptime=0,
            allow_zero_replicas=False,
            dry_run=False,
            include_statefulsets=False,
            include_daemonsets=False,
            include_jobs=False,
            required_workloads=None,
            skip_containers=None,
            component_aliases=None,
        )

        mock_controller = MagicMock()
        mock_discovery = MagicMock()
        mock_auditor = MagicMock()

        # First call returns start_time=0, second call returns past-timeout value.
        # Use a counter so that the logging module's internal time.time() calls
        # (which also hit this mock) always get a valid numeric value.
        call_count = 0

        def _fake_time() -> float:
            nonlocal call_count
            call_count += 1
            # First call is start_time (returns 0), all subsequent return 100
            # which exceeds the 5-second timeout.
            if call_count == 1:
                return 0.0
            return 100.0

        with (
            patch("kubernify.cli.KubernetesController", return_value=mock_controller),
            patch("kubernify.cli.WorkloadDiscovery", return_value=mock_discovery),
            patch("kubernify.cli.StabilityAuditor", return_value=mock_auditor),
            patch("kubernify.cli.time.time", side_effect=_fake_time),
        ):
            exit_code = run_verification(args=args)

        assert exit_code == 2


# ---------------------------------------------------------------------------
# Component aliases tests
# ---------------------------------------------------------------------------


class TestLoadComponentAliases:
    """Tests for ``load_component_aliases``."""

    def test_none_returns_empty_dict(self) -> None:
        """Verify None input returns empty dict."""
        result = load_component_aliases(None)

        assert result == {}

    def test_empty_string_returns_empty_dict(self) -> None:
        """Verify empty string returns empty dict."""
        result = load_component_aliases("")

        assert result == {}

    def test_valid_json_parsed(self) -> None:
        """Verify valid JSON string is parsed into a dict."""
        result = load_component_aliases('{"foo": "bar-baz"}')

        assert result == {"foo": "bar-baz"}

    def test_multiple_aliases(self) -> None:
        """Verify multiple aliases are parsed correctly."""
        result = load_component_aliases('{"foo": "bar-baz", "my-comp": "server"}')

        assert result == {"foo": "bar-baz", "my-comp": "server"}

    def test_invalid_json_raises_value_error(self) -> None:
        """Verify invalid JSON raises ValueError."""
        with pytest.raises(ValueError, match="not valid JSON"):
            load_component_aliases("{invalid json}")

    def test_non_object_json_raises_value_error(self) -> None:
        """Verify non-object JSON raises ValueError."""
        with pytest.raises(ValueError, match="must be a JSON object"):
            load_component_aliases('["foo", "bar-baz"]')

    def test_values_coerced_to_strings(self) -> None:
        """Verify non-string keys and values are coerced to strings."""
        result = load_component_aliases('{"foo": 123}')

        assert result == {"foo": "123"}


class TestBuildReverseAliasMap:
    """Tests for ``build_reverse_alias_map``."""

    def test_basic_reverse_mapping(self) -> None:
        """Verify aliases are inverted correctly."""
        aliases = {"foo": "bar-baz"}
        manifest = {"foo": "v1.0.0", "backend": "v2.0.0"}

        result = build_reverse_alias_map(aliases=aliases, manifest=manifest)

        assert result == {"bar-baz": "foo"}

    def test_multiple_aliases_reversed(self) -> None:
        """Verify multiple aliases are all inverted."""
        aliases = {"foo": "bar-baz", "my-comp": "server"}
        manifest = {"foo": "v1.0.0", "my-comp": "v2.0.0"}

        result = build_reverse_alias_map(aliases=aliases, manifest=manifest)

        assert result == {"bar-baz": "foo", "server": "my-comp"}

    def test_empty_aliases_returns_empty(self) -> None:
        """Verify empty aliases returns empty dict."""
        result = build_reverse_alias_map(aliases={}, manifest={"backend": "v1.0.0"})

        assert result == {}

    def test_duplicate_image_name_raises_value_error(self) -> None:
        """Verify two manifest keys aliasing to the same image name raises ValueError."""
        aliases = {"foo": "bar-baz", "foo2": "bar-baz"}
        manifest = {"foo": "v1.0.0", "foo2": "v2.0.0"}

        with pytest.raises(ValueError, match="Duplicate component alias"):
            build_reverse_alias_map(aliases=aliases, manifest=manifest)

    def test_alias_key_not_in_manifest_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Verify alias key not in manifest logs a warning but does not raise."""
        aliases = {"nonexistent": "bar-baz"}
        manifest = {"backend": "v1.0.0"}

        with caplog.at_level(logging.WARNING):
            result = build_reverse_alias_map(aliases=aliases, manifest=manifest)

        assert result == {"bar-baz": "nonexistent"}
        assert "not present in the manifest" in caplog.text


class TestParseArgsComponentAliases:
    """Tests for ``--component-aliases`` CLI argument parsing."""

    def test_component_aliases_default_is_none(self) -> None:
        """Verify --component-aliases defaults to None when not provided."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
            ]
        )

        assert args.component_aliases is None

    def test_component_aliases_parsed(self) -> None:
        """Verify --component-aliases is stored as the raw JSON string."""
        args = parse_args(
            [
                "--manifest",
                '{"backend": "v1.0.0"}',
                "--anchor",
                "my-app",
                "--component-aliases",
                '{"foo": "bar-baz"}',
            ]
        )

        assert args.component_aliases == '{"foo": "bar-baz"}'
