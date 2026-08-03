"""Provider-specific immutable configuration, destination, and reference types.

No shared key/value credential bag exists. Secrets are excluded from repr so
typed failures and diagnostics cannot accidentally disclose bound material.
Messaging destinations address exactly one Provider user. The values describe
personal addressing and exact message identity only; event endpoints and
business recipients are intentionally separate.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from core.human_input_v2.entities import IMProvider

from .contracts import _require_non_blank


def _validate_directory_page_size(value: int | None, provider_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{provider_name} directory page size must be an integer")
    if value <= 0:
        raise ValueError(f"{provider_name} directory page size must be positive")


def _extract_https_origin(value: str, *, origin_only: bool, allow_query: bool = False) -> str:
    """Return one canonical HTTPS origin or reject unsafe URL components."""
    try:
        parsed_url = urlsplit(value)
        port = parsed_url.port
    except ValueError as error:
        raise ValueError("service URL must contain a valid HTTPS origin") from error
    if (
        parsed_url.scheme.casefold() != "https"
        or parsed_url.hostname is None
        or parsed_url.username is not None
        or parsed_url.password is not None
        or port not in (None, 443)
        or (parsed_url.query and not allow_query)
        or parsed_url.fragment
        or (origin_only and parsed_url.path not in ("", "/"))
    ):
        raise ValueError("service URL must contain a valid HTTPS origin")
    normalized_host = parsed_url.hostname.encode("idna").decode("ascii").casefold()
    if not normalized_host:
        raise ValueError("service URL must contain a valid HTTPS origin")
    return f"https://{normalized_host}"


@dataclass(frozen=True, slots=True)
class SlackAdapterConfig:
    """Slack API, Webhook signing, and Socket Mode connection material."""

    bot_token: str = field(repr=False)
    signing_secret: str = field(repr=False)
    app_token: str = field(repr=False)
    directory_page_size: int | None = None

    def __post_init__(self) -> None:
        _require_non_blank("Slack bot token", self.bot_token)
        _require_non_blank("Slack signing secret", self.signing_secret)
        _require_non_blank("Slack app token", self.app_token)
        _validate_directory_page_size(self.directory_page_size, "Slack")


@dataclass(frozen=True, slots=True)
class FeishuLarkAdapterConfig:
    """Feishu or Lark app and event transport material."""

    provider: IMProvider
    app_id: str
    app_secret: str = field(repr=False)
    verification_token: str = field(repr=False)
    encrypt_key: str | None = field(repr=False)
    directory_page_size: int | None = None

    def __post_init__(self) -> None:
        if self.provider not in (IMProvider.FEISHU, IMProvider.LARK):
            raise ValueError("Feishu/Lark configuration requires the Feishu or Lark provider")
        _require_non_blank("Feishu/Lark app id", self.app_id)
        _require_non_blank("Feishu/Lark app secret", self.app_secret)
        _require_non_blank("Feishu/Lark verification token", self.verification_token)
        if self.encrypt_key is not None:
            _require_non_blank("Feishu/Lark encrypt key", self.encrypt_key)
        _validate_directory_page_size(self.directory_page_size, "Feishu/Lark")


@dataclass(frozen=True, slots=True)
class DingTalkAdapterConfig:
    """DingTalk tenant-bound API credentials and Directory page-size seam."""

    corp_id: str
    client_id: str
    client_secret: str = field(repr=False)
    directory_page_size: int | None = None

    def __post_init__(self) -> None:
        _require_non_blank("DingTalk corporation id", self.corp_id)
        _require_non_blank("DingTalk client id", self.client_id)
        _require_non_blank("DingTalk client secret", self.client_secret)
        _validate_directory_page_size(self.directory_page_size, "DingTalk")


@dataclass(frozen=True, slots=True)
class WeComAdapterConfig:
    """WeCom corporation and agent API credentials."""

    corp_id: str
    agent_id: str
    corp_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_non_blank("WeCom corporation id", self.corp_id)
        _require_non_blank("WeCom agent id", self.agent_id)
        _require_non_blank("WeCom corporation secret", self.corp_secret)


@dataclass(frozen=True, slots=True)
class MicrosoftTeamsAdapterConfig:
    """Microsoft Entra identity plus approved outbound Connector origins.

    Origins are immutable composition input learned from authenticated
    conversation references or an administrator-controlled allowlist. Inbound
    Activities never mutate this configuration.
    """

    tenant_id: str
    client_id: str
    client_secret: str = field(repr=False)
    bot_app_id: str
    trusted_service_url_origins: tuple[str, ...] = ()
    directory_page_size: int | None = None

    def __post_init__(self) -> None:
        _require_non_blank("Microsoft tenant id", self.tenant_id)
        _require_non_blank("Microsoft client id", self.client_id)
        _require_non_blank("Microsoft client secret", self.client_secret)
        _require_non_blank("Microsoft bot app id", self.bot_app_id)
        if not isinstance(self.trusted_service_url_origins, tuple):
            raise TypeError("Microsoft trusted service URL origins must be a tuple")
        normalized_origins = tuple(
            dict.fromkeys(
                _extract_https_origin(origin, origin_only=True) for origin in self.trusted_service_url_origins
            )
        )
        object.__setattr__(self, "trusted_service_url_origins", normalized_origins)
        _validate_directory_page_size(self.directory_page_size, "Microsoft Teams")


@dataclass(frozen=True, slots=True)
class SlackUserDestination:
    """Slack user address for one direct message."""

    user_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _require_non_blank("Slack user id", self.user_id))


@dataclass(frozen=True, slots=True)
class FeishuUserDestination:
    """Feishu/Lark user identifier with one implemented personal address type."""

    receive_id: str
    receive_id_type: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "receive_id", _require_non_blank("Feishu/Lark receive id", self.receive_id))
        object.__setattr__(
            self,
            "receive_id_type",
            _require_non_blank("Feishu/Lark receive id type", self.receive_id_type),
        )


@dataclass(frozen=True, slots=True)
class DingTalkUserDestination:
    """DingTalk user address for one robot message."""

    user_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _require_non_blank("DingTalk user id", self.user_id))


@dataclass(frozen=True, slots=True)
class WeComUserDestination:
    """WeCom user address for one application message."""

    user_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _require_non_blank("WeCom user id", self.user_id))


@dataclass(frozen=True, slots=True)
class TeamsPersonalConversationDestination:
    """Bot Framework personal conversation and target user for proactive send."""

    service_url: str
    conversation_id: str
    user_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_url", _require_non_blank("Teams service URL", self.service_url))
        object.__setattr__(
            self,
            "conversation_id",
            _require_non_blank("Teams conversation id", self.conversation_id),
        )
        object.__setattr__(self, "user_id", _require_non_blank("Teams user id", self.user_id))


@dataclass(frozen=True, slots=True)
class SlackMessageReference:
    """Exact Slack message locator required for updates."""

    channel_id: str
    message_timestamp: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel_id", _require_non_blank("Slack channel id", self.channel_id))
        object.__setattr__(
            self,
            "message_timestamp",
            _require_non_blank("Slack message timestamp", self.message_timestamp),
        )


@dataclass(frozen=True, slots=True)
class FeishuMessageReference:
    """Exact Feishu/Lark provider message identifier."""

    message_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_id", _require_non_blank("Feishu/Lark message id", self.message_id))


@dataclass(frozen=True, slots=True)
class DingTalkMessageReference:
    """Exact DingTalk user-scoped message locator."""

    user_id: str
    message_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _require_non_blank("DingTalk user id", self.user_id))
        object.__setattr__(self, "message_id", _require_non_blank("DingTalk message id", self.message_id))


@dataclass(frozen=True, slots=True)
class WeComMessageReference:
    """Exact WeCom provider message identifier returned on acceptance."""

    message_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_id", _require_non_blank("WeCom message id", self.message_id))


@dataclass(frozen=True, slots=True)
class TeamsMessageReference:
    """Exact Bot Framework personal conversation activity context for updates."""

    service_url: str
    conversation_id: str
    user_id: str
    activity_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_url", _require_non_blank("Teams service URL", self.service_url))
        object.__setattr__(
            self,
            "conversation_id",
            _require_non_blank("Teams conversation id", self.conversation_id),
        )
        object.__setattr__(self, "user_id", _require_non_blank("Teams user id", self.user_id))
        object.__setattr__(self, "activity_id", _require_non_blank("Teams activity id", self.activity_id))
