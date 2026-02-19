"""Unit tests for the CLI argument parsing and helper functions in kubernify.cli."""

from __future__ import annotations

import logging
from unittest.mock import mock_open, patch

import pytest

from kubernify.cli import _get_current_namespace, _setup_logging, load_manifest, parse_args

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
