from datetime import datetime

from pydantic import BaseModel, ConfigDict

from models.im_integration import (
    IMBindingSessionStatus,
    IMBindingStatus,
    IMInstallMode,
    IMProvider,
    IMScopeType,
)


class IMBindingRecord(BaseModel):
    id: str
    account_id: str
    provider: IMProvider
    install_mode: IMInstallMode
    scope_type: IMScopeType
    scope_id: str
    provider_workspace_id: str
    provider_user_id: str
    provider_union_id: str | None = None
    provider_user_display_name: str | None = None
    provider_user_avatar_url: str | None = None
    status: IMBindingStatus

    model_config = ConfigDict(frozen=True)


class IMBindingSessionRecord(BaseModel):
    id: str
    account_id: str
    provider: IMProvider
    install_mode: IMInstallMode
    scope_type: IMScopeType
    scope_id: str
    token: str
    status: IMBindingSessionStatus
    expires_at: datetime

    model_config = ConfigDict(frozen=True)
