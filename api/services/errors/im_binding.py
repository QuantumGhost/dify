class IMBindingValidationError(ValueError):
    """Service-layer validation error for IM binding use cases."""


class IMProviderCallbackVerificationError(IMBindingValidationError):
    """Provider callback failed signature/challenge verification."""


class IMProviderTransportError(RuntimeError):
    """Provider send or card-update transport failed after local validation."""
