# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""Top-level ``verilore`` package.

The wheel ships exactly one importable namespace, ``verilore`` (plus the two
one-release shims ``verilore_sdk`` and ``verilore_errors``). The public surface
lives in the submodules -- ``verilore.sdk``, ``verilore.errors``, ``verilore.api``,
``verilore.cli``, ``verilore.mcp_server``, ``verilore.pack``, ``verilore.proof``,
``verilore.proof_cli``, ``verilore.receipt``, ``verilore.runtime`` -- and the
names below are re-exported lazily so that ``import verilore`` itself pulls in
none of httpx, fastapi, sqlalchemy, onnxruntime, or the api/cli surfaces.

    from verilore import Verilore

is the documented import. The top-level ``verilore_sdk`` and ``verilore_errors``
modules remain as deprecated shims for v0.11.
"""

from __future__ import annotations

import importlib.metadata
import sys

try:  # The distribution is installed (editable or wheel) in every real environment.
    __version__ = importlib.metadata.version("verilore")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.11.0"

#: Lazy public names -> the submodule that defines them. Imported on first access.
_LAZY = {
    # From verilore.sdk.
    "DEFAULT_CORPUS": "verilore.sdk",
    "CorpusNotFoundError": "verilore.sdk",
    "DatabaseUnavailableError": "verilore.sdk",
    "MemoryClient": "verilore.sdk",
    "MemoryClientError": "verilore.sdk",
    "MemoryResult": "verilore.sdk",
    "Verilore": "verilore.sdk",
    "VeriloreAuthenticationError": "verilore.sdk",
    "VeriloreConflictError": "verilore.sdk",
    "VeriloreError": "verilore.sdk",
    "VeriloreInternalError": "verilore.sdk",
    "VeriloreNotFoundError": "verilore.sdk",
    "VeriloreTransportError": "verilore.sdk",
    "VeriloreUnauthorizedError": "verilore.sdk",
    "VeriloreValidationError": "verilore.sdk",
    "ProviderAuthenticationError": "verilore.sdk",
    "ProviderError": "verilore.sdk",
    "ProviderIncompatibleModelError": "verilore.sdk",
    "ProviderMalformedResponseError": "verilore.sdk",
    "ProviderRateLimitError": "verilore.sdk",
    "ProviderRefusedError": "verilore.sdk",
    "ProviderTimeoutError": "verilore.sdk",
    "ProviderUnavailableError": "verilore.sdk",
    "ReceiptError": "verilore.sdk",
    "SyncSummary": "verilore.sdk",
    "verify_receipt": "verilore.sdk",
    "verify_response_receipt": "verilore.sdk",
    "verify_trust": "verilore.sdk",
    # From verilore.errors.
    "COMPONENTS": "verilore.errors",
    "AuthenticationError": "verilore.errors",
    "ConflictError": "verilore.errors",
    "DatabaseSchemaError": "verilore.errors",
    "InternalError": "verilore.errors",
    "NotFoundError": "verilore.errors",
    "RequestId": "verilore.errors",
    "TransportError": "verilore.errors",
    "UnauthorizedError": "verilore.errors",
    "ValidationError": "verilore.errors",
    "classify_provider_error": "verilore.errors",
    "envelope": "verilore.errors",
    "new_request_id": "verilore.errors",
}


def __getattr__(name: str):
    """Lazy attribute access: import a submodule only when one of its names is used."""
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = sys.modules.get(submodule)
    if module is None:
        module = __import__(submodule, fromlist=[name])
    value = getattr(module, name)
    # Cache on the package so subsequent lookups skip the import.
    setattr(sys.modules[__name__], name, value)
    return value


def __dir__() -> list[str]:
    return sorted(list(globals()) + list(_LAZY))
