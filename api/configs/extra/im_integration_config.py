from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class IMIntegrationConfig(BaseSettings):
    """Deployment-global IM integration settings for phase-1 demos and bootstrap."""

    LARK_APP_ID: str | None = Field(
        default=None,
        description="Feishu/Lark self-built app ID for phase-1 IM integration.",
    )
    LARK_APP_SECRET: str | None = Field(
        default=None,
        description="Feishu/Lark self-built app secret for phase-1 IM integration.",
    )
    LARK_EVENT_MODE: Literal["long_connection", "webhook"] | None = Field(
        default=None,
        description="Feishu/Lark event transport mode. Phase-1 demo requires long_connection.",
    )
    LARK_VERIFICATION_TOKEN: str | None = Field(
        default=None,
        description="Feishu/Lark callback verification token for signed webhook/challenge validation.",
    )
    LARK_ENCRYPT_KEY: str | None = Field(
        default=None,
        description="Feishu/Lark callback encrypt key for signed webhook/challenge validation.",
    )
