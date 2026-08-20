"""Import compatibility for the retired global daemon state tracker.

Run-scoped state is now owned by :class:`app.runtime.state.RunState`.
"""

from app.runtime.state import RunState

__all__ = ["RunState"]
