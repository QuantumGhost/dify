"""IM app config resolution for phase-1 HITL foundations.

This module only resolves deployment-global self-built app context for the
Feishu demo slice. Future provider integrations should prefer official SDKs for
provider-specific auth, transport, and callback handling.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field

from configs import dify_config
from models.im_integration import IMInstallMode, IMProvider, IMScopeType


class IMAppConfigStatus(enum.StrEnum):
    CONFIGURED = "configured"
    MISSING = "missing"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


class IMTokenStatus(enum.StrEnum):
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class IMEventMode(enum.StrEnum):
    LONG_CONNECTION = "long_connection"
    WEBHOOK = "webhook"


class IMAppContext(BaseModel):
    provider: IMProvider
    install_mode: IMInstallMode
    scope_type: IMScopeType
    scope_id: str
    status: IMAppConfigStatus
    token_status: IMTokenStatus
    event_mode: IMEventMode | None = None
    app_id: str | None = None
    app_secret: str | None = None
    app_secret_configured: bool = False
    verification_token: str | None = None
    encrypt_key: str | None = None
    provider_workspace_id: str | None = None
    errors: list[str] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)


def resolve_im_app_context(*, provider: IMProvider, tenant_id: str) -> IMAppContext:
    """Resolve the phase-1 IM app context for one provider and workspace."""

    _ = tenant_id
    if provider != IMProvider.FEISHU:
        return IMAppContext(
            provider=provider,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            status=IMAppConfigStatus.UNSUPPORTED,
            token_status=IMTokenStatus.NOT_APPLICABLE,
            errors=[f"provider {provider.value} is not supported in phase-1 resolver"],
        )

    errors: list[str] = []
    event_mode = IMEventMode(dify_config.LARK_EVENT_MODE) if dify_config.LARK_EVENT_MODE else None
    if not dify_config.LARK_APP_ID:
        errors.append("missing LARK_APP_ID")
    if not dify_config.LARK_APP_SECRET:
        errors.append("missing LARK_APP_SECRET")
    if event_mode is None:
        errors.append("missing LARK_EVENT_MODE")
    elif event_mode != IMEventMode.LONG_CONNECTION:
        errors.append("phase-1 demo requires LARK_EVENT_MODE=long_connection")

    status = IMAppConfigStatus.CONFIGURED
    if any(error.startswith("missing") for error in errors):
        status = IMAppConfigStatus.MISSING
    elif errors:
        status = IMAppConfigStatus.INVALID

    return IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=status,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        event_mode=event_mode,
        app_id=dify_config.LARK_APP_ID,
        app_secret=dify_config.LARK_APP_SECRET,
        app_secret_configured=bool(dify_config.LARK_APP_SECRET),
        verification_token=dify_config.LARK_VERIFICATION_TOKEN,
        encrypt_key=dify_config.LARK_ENCRYPT_KEY,
        errors=errors,
    )
