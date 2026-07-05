"""Phase-1 IM-specific services package.

Workspace-scoped Contact lifecycle helpers live outside this package so IM
delivery code can depend on Contact services without owning the concept.
"""

from .service import BindingCompletionCallbackResult, HumanInputIMService

__all__ = ["BindingCompletionCallbackResult", "HumanInputIMService"]
