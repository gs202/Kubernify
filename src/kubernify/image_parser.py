"""Container image reference parser for Kubernify.

Implements the Repository-Relative First-Segment Extraction strategy to parse
container image references into structured components. Handles Docker Hub
normalization and nested image paths.
"""

from __future__ import annotations

from .models import ImageReference

# Docker Hub host aliases that should be normalized
_DOCKER_HUB_HOSTS: frozenset[str] = frozenset({
    "docker.io",
    "index.docker.io",
    "registry-1.docker.io",
})

_DOCKER_HUB_CANONICAL: str = "docker.io"


def _has_registry_host(first_segment: str) -> bool:
    """Determine whether the first path segment is a registry host."""
    return "." in first_segment or ":" in first_segment


def _normalize_docker_hub(registry: str | None, path_segments: list[str]) -> tuple[str | None, list[str]]:
    """Normalize Docker Hub registry references and implicit namespaces."""
    # Normalize Docker Hub host aliases
    if registry and registry in _DOCKER_HUB_HOSTS:
        registry = _DOCKER_HUB_CANONICAL

    # Docker Hub with single-segment path implies library/ namespace
    is_docker_hub = registry is None or registry == _DOCKER_HUB_CANONICAL
    if is_docker_hub and len(path_segments) == 1:
        path_segments = ["library", path_segments[0]]

    return registry, path_segments


def parse_image_reference(image: str, repository_anchor: str) -> ImageReference:
    """Parse a container image reference into structured components."""
    if not image or not image.strip():
        raise ValueError("Image reference must not be empty")

    image = image.strip()

    # Step 1: Strip any @-suffix (e.g. pinned hash) before parsing
    working = image
    if "@" in working:
        working = working[:working.index("@")]

    # Step 2: Extract tag from the last path segment
    segments = working.split("/")
    last_segment = segments[-1]

    if ":" in last_segment:
        name_part, version = last_segment.rsplit(":", 1)
        segments[-1] = name_part
    else:
        version = "latest"

    # Step 3: Determine registry host
    registry: str | None = None
    path_segments: list[str]

    if len(segments) > 1 and _has_registry_host(segments[0]):
        registry = segments[0]
        path_segments = segments[1:]
    else:
        path_segments = segments

    # Step 4: Docker Hub normalization
    registry, path_segments = _normalize_docker_hub(registry=registry, path_segments=path_segments)

    # Step 5: Find repository anchor and extract component
    component: str
    sub_image: str | None = None

    try:
        anchor_index = path_segments.index(repository_anchor)
        component_segments = path_segments[anchor_index + 1:]

        if not component_segments:
            # Anchor is the last segment — use it as component (edge case)
            component = repository_anchor
        else:
            component = component_segments[0]
            if len(component_segments) > 1:
                sub_image = "/".join(component_segments[1:])
    except ValueError:
        # Fallback: anchor not found — use last path segment as component
        component = path_segments[-1]

    return ImageReference(
        component=component,
        version=version,
        sub_image=sub_image,
        full_image=image,
        registry=registry,
    )
