"""Phase-1 IM-specific services package.

Workspace-scoped Contact lifecycle helpers live outside this package so IM
delivery code can depend on Contact services without owning the concept.
"""

from .card_update_compensation_service import (
    IMCardUpdateCompensationQueue,
    IMCardUpdateCompensationRequest,
    IMCardUpdateCompensationService,
)
from .message_status_service import IMMessageCorrelationStatusService
from .service import BindingCompletionCallbackResult, HumanInputIMService
from .submission_result_service import HumanInputIMSubmissionResultService

__all__ = [
    "BindingCompletionCallbackResult",
    "HumanInputIMService",
    "HumanInputIMSubmissionResultService",
    "IMCardUpdateCompensationQueue",
    "IMCardUpdateCompensationRequest",
    "IMCardUpdateCompensationService",
    "IMMessageCorrelationStatusService",
]
