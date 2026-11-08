import sys
import warnings

import verilore.errors as _impl

warnings.warn(
    "import verilore instead of verilore_errors; removed in v0.12",
    DeprecationWarning,
    stacklevel=2,
)

# Aliasing sys.modules keeps private names and monkeypatch targets identical to
# importing verilore.errors directly.
sys.modules[__name__] = _impl
