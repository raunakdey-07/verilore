import sys
import warnings

import verilore.sdk as _impl

warnings.warn(
    "import verilore instead of verilore_sdk; removed in v0.12",
    DeprecationWarning,
    stacklevel=2,
)

# Aliasing sys.modules keeps private names and monkeypatch targets identical to
# importing verilore.sdk directly.
sys.modules[__name__] = _impl
