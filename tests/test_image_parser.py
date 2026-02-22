"""Unit tests for the image_parser module.

Tests the ``parse_image_reference()`` function against all documented image
formats including anchored registry images, Docker Hub images, and edge cases.
"""

from __future__ import annotations

import pytest

from kubernify.image_parser import parse_image_reference

# ---------------------------------------------------------------------------
# Standard anchored image patterns (from specification table)
# ---------------------------------------------------------------------------


class TestAnchoredImages:
    """Tests for standard anchored repository image references."""

    @pytest.mark.parametrize(
        ("image", "expected_component", "expected_sub_image", "expected_version"),
        [
            pytest.param(
                "registry.example.com/my-org/my-app/backend:1.2.3",
                "backend",
                None,
                "1.2.3",
                id="simple-backend",
            ),
            pytest.param(
                "registry.example.com/my-org/my-app/frontend:1.2.4",
                "frontend",
                None,
                "1.2.4",
                id="simple-frontend",
            ),
            pytest.param(
                "registry.example.com/my-org/my-app/portal/internal/server:v8.13.0",
                "portal",
                "internal/server",
                "v8.13.0",
                id="nested-portal-server",
            ),
            pytest.param(
                "registry.example.com/my-org/my-app/portal/internal/init-svc:v8.13.0",
                "portal",
                "internal/init-svc",
                "v8.13.0",
                id="nested-portal-init",
            ),
            pytest.param(
                "registry.example.com/my-org/my-app/plugins/plugins-hub:2.0.0",
                "plugins",
                "plugins-hub",
                "2.0.0",
                id="nested-plugins-hub",
            ),
            pytest.param(
                "registry.example.com/my-org/my-app/bar-baz:1.5.0",
                "bar-baz",
                None,
                "1.5.0",
                id="bar-baz",
            ),
            pytest.param(
                "registry.example.com/my-org/my-app/analytics-rocksdb:2.0.1",
                "analytics-rocksdb",
                None,
                "2.0.1",
                id="analytics-rocksdb",
            ),
        ],
    )
    def test_anchored_images(
        self,
        image: str,
        expected_component: str,
        expected_sub_image: str | None,
        expected_version: str,
    ) -> None:
        """Verify parsing of standard anchored registry images.

        Args:
            image: The full image reference string.
            expected_component: Expected component name after anchor extraction.
            expected_sub_image: Expected sub-image path or None.
            expected_version: Expected version/tag string.
        """
        result = parse_image_reference(image=image, repository_anchor="my-app")

        assert result.component == expected_component
        assert result.sub_image == expected_sub_image
        assert result.version == expected_version
        assert result.full_image == image
        assert result.registry == "registry.example.com"

    def test_anchor_without_registry(self) -> None:
        """Verify parsing when anchor is present without registry prefix."""
        result = parse_image_reference(image="my-app/backend:1.2.3", repository_anchor="my-app")

        assert result.component == "backend"
        assert result.sub_image is None
        assert result.version == "1.2.3"
        assert result.registry is None


# ---------------------------------------------------------------------------
# Docker Hub images (fallback behavior — no anchor match)
# ---------------------------------------------------------------------------


class TestDockerHubImages:
    """Tests for Docker Hub image references with various formats."""

    def test_bare_image_no_tag(self) -> None:
        """Verify bare image name defaults to latest tag."""
        result = parse_image_reference(image="redis", repository_anchor="my-app")

        assert result.component == "redis"
        assert result.version == "latest"
        assert result.sub_image is None

    def test_bare_image_with_tag(self) -> None:
        """Verify bare image with explicit tag."""
        result = parse_image_reference(image="redis:alpine", repository_anchor="my-app")

        assert result.component == "redis"
        assert result.version == "alpine"
        assert result.sub_image is None

    def test_bare_image_with_numeric_tag(self) -> None:
        """Verify bare image with numeric tag."""
        result = parse_image_reference(image="nginx:1.21", repository_anchor="my-app")

        assert result.component == "nginx"
        assert result.version == "1.21"
        assert result.sub_image is None

    def test_explicit_docker_io_registry(self) -> None:
        """Verify explicit docker.io registry with library namespace."""
        result = parse_image_reference(image="docker.io/library/redis:7.0", repository_anchor="my-app")

        assert result.component == "redis"
        assert result.version == "7.0"
        assert result.registry == "docker.io"
        assert result.sub_image is None

    def test_index_docker_io_normalization(self) -> None:
        """Verify index.docker.io is normalized to docker.io."""
        result = parse_image_reference(image="index.docker.io/library/nginx:latest", repository_anchor="my-app")

        assert result.component == "nginx"
        assert result.version == "latest"
        assert result.registry == "docker.io"
        assert result.sub_image is None


# ---------------------------------------------------------------------------
# Non-Docker-Hub third-party registries
# ---------------------------------------------------------------------------


class TestThirdPartyRegistries:
    """Tests for non-Docker-Hub registry image references."""

    def test_gcr_io_registry(self) -> None:
        """Verify gcr.io registry images use last-segment fallback."""
        result = parse_image_reference(image="gcr.io/google-containers/pause:3.2", repository_anchor="my-app")

        assert result.component == "pause"
        assert result.version == "3.2"
        assert result.registry == "gcr.io"
        assert result.sub_image is None


# ---------------------------------------------------------------------------
# @-suffix stripping (e.g. pinned hashes)
# ---------------------------------------------------------------------------


class TestAtSuffixStripping:
    """Tests that @-suffixes are stripped before parsing."""

    def test_tag_with_at_suffix_keeps_tag(self) -> None:
        """Verify image with both tag and @-suffix extracts only the tag."""
        result = parse_image_reference(
            image="registry.example.com/my-org/my-app/backend:1.2.3@sha256:abc123",
            repository_anchor="my-app",
        )

        assert result.component == "backend"
        assert result.version == "1.2.3"
        assert result.sub_image is None
        assert result.registry == "registry.example.com"

    def test_at_suffix_only_defaults_to_latest(self) -> None:
        """Verify image with @-suffix but no tag defaults to 'latest'."""
        result = parse_image_reference(
            image="registry.example.com/my-org/my-app/backend@sha256:abc123",
            repository_anchor="my-app",
        )

        assert result.component == "backend"
        assert result.version == "latest"
        assert result.sub_image is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_string_raises_value_error(self) -> None:
        """Verify empty string input raises ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            parse_image_reference(image="", repository_anchor="my-app")

    def test_whitespace_only_raises_value_error(self) -> None:
        """Verify whitespace-only input raises ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            parse_image_reference(image="   ", repository_anchor="my-app")

    def test_image_with_leading_trailing_whitespace(self) -> None:
        """Verify leading/trailing whitespace is stripped before parsing."""
        result = parse_image_reference(image="  redis:alpine  ", repository_anchor="my-app")

        assert result.component == "redis"
        assert result.version == "alpine"

    def test_non_matching_anchor_fallback(self) -> None:
        """Verify fallback to last segment when anchor is not found."""
        result = parse_image_reference(
            image="registry.example.com/some-project/other-repo/my-service:3.0.0",
            repository_anchor="my-app",
        )

        assert result.component == "my-service"
        assert result.version == "3.0.0"
        assert result.sub_image is None
        assert result.registry == "registry.example.com"

    def test_custom_repository_anchor(self) -> None:
        """Verify custom repository_anchor parameter works correctly."""
        result = parse_image_reference(
            image="registry.example.com/project/my-repo/service:2.0.0",
            repository_anchor="my-repo",
        )

        assert result.component == "service"
        assert result.version == "2.0.0"
        assert result.sub_image is None

    def test_docker_hub_implicit_library_namespace(self) -> None:
        """Verify single-segment Docker Hub images get library/ prepended."""
        result = parse_image_reference(image="redis", repository_anchor="my-app")

        # The library/ prefix is added internally for normalization,
        # but the component should still be the image name
        assert result.component == "redis"
        assert result.version == "latest"

    def test_docker_hub_explicit_namespace(self) -> None:
        """Verify Docker Hub images with explicit namespace (not library)."""
        result = parse_image_reference(image="bitnami/redis:7.0", repository_anchor="my-app")

        assert result.component == "redis"
        assert result.version == "7.0"
        assert result.registry is None

    def test_full_image_preserved(self) -> None:
        """Verify the full_image field always contains the original input."""
        original = "registry.example.com/my-org/my-app/backend:1.2.3"
        result = parse_image_reference(image=original, repository_anchor="my-app")

        assert result.full_image == original

    def test_at_suffix_with_docker_hub_image(self) -> None:
        """Verify @-suffix is stripped from Docker Hub images."""
        result = parse_image_reference(image="redis@sha256:deadbeef", repository_anchor="my-app")

        assert result.component == "redis"
        assert result.version == "latest"

    def test_port_based_registry(self) -> None:
        """Verify port-based registry hosts are detected correctly."""
        result = parse_image_reference(image="localhost:5000/my-app:1.0.0", repository_anchor="other-anchor")

        assert result.component == "my-app"
        assert result.version == "1.0.0"
        assert result.registry == "localhost:5000"

    def test_nested_path_with_at_suffix(self) -> None:
        """Verify nested anchored path with @-suffix strips it and keeps tag."""
        result = parse_image_reference(
            image="registry.example.com/my-org/my-app/portal/internal/server:v8.13.0@sha256:abc",
            repository_anchor="my-app",
        )

        assert result.component == "portal"
        assert result.sub_image == "internal/server"
        assert result.version == "v8.13.0"

    def test_registry_1_docker_io_normalization(self) -> None:
        """Verify registry-1.docker.io is normalized to docker.io."""
        result = parse_image_reference(
            image="registry-1.docker.io/library/alpine:3.18",
            repository_anchor="my-app",
        )

        assert result.component == "alpine"
        assert result.version == "3.18"
        assert result.registry == "docker.io"
