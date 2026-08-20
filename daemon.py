"""Import compatibility for the retired daemon module.

The operational runtime now lives in :mod:`app.runtime.manager`.  This module
exists only because the repository's current CI still imports ``daemon`` as a
smoke check; it intentionally contains no legacy daemon loop.
"""

from app.runtime.manager import RuntimeManager

__all__ = ["RuntimeManager"]
