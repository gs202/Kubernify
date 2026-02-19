"""Kubernify — Kubernetes deployment version verification.

Verify that deployed workloads in a Kubernetes cluster match a given version
manifest with deep stability auditing.
"""

import logging

from kubernify._version import __version__
from kubernify.models import VerificationReport, VerificationStatus

__all__ = ["VerificationReport", "VerificationStatus", "__version__"]

logging.getLogger(__name__).addHandler(logging.NullHandler())
