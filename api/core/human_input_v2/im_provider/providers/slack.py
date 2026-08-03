"""Slack Web API and Block Kit action boundary owned by ``SlackAdapter``.

The client uses the adapter-bound bot token for Web API calls and never
replays side-effecting messaging requests. Webhook replay evidence is retained
only after sink acceptance by the adapter root. Socket Mode remains a distinct
role because its lifecycle differs from the stateless Web API client.
Credential checks distinguish throttling and upstream failures from confirmed
Slack token rejection.

The Socket Mode transport is pinned to ``slack-sdk==3.43.0``. That version's
public ``SocketModeClient.close()`` closes the active session, app monitor,
message processor, and worker pool but neither terminates the active session
state nor stops ``current_session_runner``.
The relevant pinned sources are:
https://github.com/slackapi/python-slack-sdk/blob/v3.43.0/slack_sdk/socket_mode/builtin/client.py
and
https://github.com/slackapi/python-slack-sdk/blob/v3.43.0/slack_sdk/socket_mode/builtin/connection.py
and
https://github.com/slackapi/python-slack-sdk/blob/v3.43.0/slack_sdk/socket_mode/interval_runner.py
The private lifecycle wrapper below is the only code allowed to depend on that
session state and the runner's ``event`` and ``thread`` fields. It uses a
bounded join instead of ``IntervalRunner.shutdown()``, whose join has no
timeout. Any SDK upgrade must revalidate this maintenance boundary against the
pinned implementation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, RLock
from typing import Literal, Protocol, cast
from urllib.parse import parse_qsl

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError, field_validator
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.builtin.client import SocketModeClient as _PinnedSocketModeClient
from slack_sdk.socket_mode.client import BaseSocketModeClient
from slack_sdk.socket_mode.listeners import SocketModeRequestListener
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient
from typing_extensions import TypedDict

from core.helper.ssrf_proxy import create_ssrf_protected_client
from core.human_input_v2.entities import IMProvider

from ..client_roles import _ProviderClientContext
from ..contracts import (
    AuthenticatedIMEvent,
    CardActionKind,
    CardAssessment,
    CardIntent,
    CredentialTestResult,
    CredentialTestSuccess,
    DestinationTestResult,
    DirectoryEntry,
    DirectoryReadResult,
    DirectorySnapshot,
    EventAcceptance,
    ImmutableJSONObject,
    MessageAccepted,
    MessageResult,
    OpaqueMetadata,
    OperationFailure,
    OperationFailureCode,
    PermissionFact,
    StopSignal,
    StreamRunResult,
    WebhookDelivery,
    WebhookParseResult,
    WebhookRejected,
    WebhookRequest,
    WebhookResponse,
    freeze_json_value,
)
from ..provider_types import SlackAdapterConfig, SlackMessageReference, SlackUserDestination

_SLACK_API_ROOT = "https://slack.com/api"
_SLACK_REQUIRED_SCOPES = ("chat:write", "users:read")
_SLACK_OPTIONAL_SCOPES = ("users:read.email",)
_SLACK_AUTHENTICATION_ERRORS = frozenset(
    {"account_inactive", "invalid_auth", "not_authed", "token_expired", "token_revoked"}
)
_HTTP_TIMEOUT_SECONDS = 10.0
_DIRECTORY_PAGE_LIMIT = 200
_MAX_DIRECTORY_RATE_LIMIT_RETRIES = 3
_MAX_SLACK_ACTION_COUNT = 25
_SLACK_BUTTON_VALUE_MAX_UTF8_BYTES = 2000
_SLACK_SUBMIT_VALUE_VERSION = 1
_SLACK_STALE_UPDATE_ERRORS = frozenset({"cant_update_message", "edit_window_closed", "message_not_found"})
_SLACK_SIGNATURE_VERSION = "v0"
_SLACK_MAX_REQUEST_AGE_SECONDS = 300
_SLACK_BLOCK_ACTIONS_EVENT_TYPE = "block_actions"
_SLACK_INTERACTIVE_REQUEST_TYPE = "interactive"
_STREAM_STOP_POLL_SECONDS = 0.1
_STREAM_RUNNER_CLOSE_TIMEOUT_SECONDS = 10.0
_STREAM_RUN_CLOSE_TIMEOUT_SECONDS = 1.0
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])

logger = logging.getLogger(__name__)

type _SlackSocketModeRequestListener = (
    SocketModeRequestListener | Callable[[BaseSocketModeClient, SocketModeRequest], None]
)


class _SlackAuthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    ok: bool
    team_id: str | None = None
    error: str | None = None


class _SlackUserProfile(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    display_name: str = ""
    real_name: str = ""
    email: str | None = None


class _SlackUser(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    deleted: bool = False
    name: str = ""
    real_name: str = ""
    profile: _SlackUserProfile

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Slack user id must not be blank")
        return value


class _SlackResponseMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    next_cursor: str = ""


class _SlackUsersResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    ok: bool
    members: tuple[_SlackUser, ...] = ()
    response_metadata: _SlackResponseMetadata = Field(default_factory=_SlackResponseMetadata)
    error: str | None = None


class _SlackUserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    ok: bool
    user: _SlackUser | None = None
    error: str | None = None
    needed: str | None = None


class _SlackMessageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    ok: bool
    channel: str | None = None
    ts: str | None = None
    error: str | None = None


class _SlackInteractiveTeam(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Slack interactive team id must not be blank")
        return value


class _SlackInteractiveEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: Literal["block_actions"]
    team: _SlackInteractiveTeam


class _SlackTextMessagePayload(TypedDict):
    channel: str
    text: str


def _encode_submit_action_value(action_value: str, metadata: OpaqueMetadata) -> str | OperationFailure:
    """Encode one submit envelope without exceeding Slack's UTF-8 wire limit."""
    encoded_value = json.dumps(
        {
            "v": _SLACK_SUBMIT_VALUE_VERSION,
            "action_value": action_value,
            "metadata": metadata.as_dict(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(encoded_value.encode("utf-8")) > _SLACK_BUTTON_VALUE_MAX_UTF8_BYTES:
        return OperationFailure(
            IMProvider.SLACK,
            OperationFailureCode.RENDERING,
            "Slack submit action value exceeds the 2000-byte UTF-8 limit",
        )
    return encoded_value


def _render_card_blocks(intent: CardIntent, metadata: OpaqueMetadata) -> list[JsonValue] | OperationFailure:
    blocks: list[JsonValue] = []
    if intent.title is not None:
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": intent.title}})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": intent.body}})
    if intent.facts:
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*{fact_name}*\n{fact_value}"} for fact_name, fact_value in intent.facts
                ],
            }
        )
    if intent.actions:
        action_elements: list[JsonValue] = []
        for action in intent.actions:
            button: dict[str, JsonValue] = {
                "type": "button",
                "action_id": action.action_id,
                "text": {"type": "plain_text", "text": action.label},
            }
            if action.kind is CardActionKind.OPEN_URL:
                button["url"] = action.value
            else:
                submit_value = _encode_submit_action_value(action.value, metadata)
                if isinstance(submit_value, OperationFailure):
                    return submit_value
                button["value"] = submit_value
            action_elements.append(button)
        blocks.append({"type": "actions", "elements": action_elements})
    return blocks


def _webhook_response(status_code: int, body: bytes) -> WebhookResponse:
    return WebhookResponse(
        status_code=status_code,
        headers=(("content-type", "application/json; charset=utf-8"),),
        body=body,
    )


def _request_header(request: WebhookRequest, name: str) -> str | None:
    normalized_name = name.casefold()
    for header_name, header_value in request.headers:
        if header_name.casefold() == normalized_name:
            return header_value
    return None


def _build_http_client(config: SlackAdapterConfig) -> httpx.Client:
    return create_ssrf_protected_client(
        verify=True,
        headers={"authorization": f"Bearer {config.bot_token}"},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )


class _SlackProviderClient:
    """Slack API roles sharing one owned HTTP connection pool."""

    _config: SlackAdapterConfig
    _http_client: httpx.Client

    def __init__(self, config: SlackAdapterConfig, http_client: httpx.Client) -> None:
        self._config = config
        self._http_client = http_client

    def test_credentials(self) -> CredentialTestResult:
        try:
            response = self._http_client.post(f"{_SLACK_API_ROOT}/auth.test")
        except httpx.RequestError:
            return OperationFailure(
                IMProvider.SLACK, OperationFailureCode.PROVIDER, "Slack authentication request failed"
            )
        if response.status_code == 429:
            return OperationFailure(
                IMProvider.SLACK, OperationFailureCode.RATE_LIMITED, "Slack rate limited the authentication request"
            )
        if response.status_code >= 500:
            return OperationFailure(
                IMProvider.SLACK, OperationFailureCode.PROVIDER, "Slack authentication service failed"
            )
        try:
            auth_response = _SlackAuthResponse.model_validate_json(response.content)
        except ValidationError:
            return OperationFailure(
                IMProvider.SLACK, OperationFailureCode.PROVIDER, "Slack authentication response was invalid"
            )

        if auth_response.error in _SLACK_AUTHENTICATION_ERRORS:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.AUTHENTICATION,
                "Slack rejected the bound bot token",
            )
        if response.status_code >= 400 or not auth_response.ok:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.PROVIDER,
                "Slack rejected the authentication request",
            )
        if auth_response.team_id is None or not auth_response.team_id.strip():
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.TENANT_IDENTIFICATION,
                "Slack authentication did not identify a workspace",
            )

        granted_scopes = {
            scope.strip() for scope in response.headers.get("x-oauth-scopes", "").split(",") if scope.strip()
        }
        missing_scopes = tuple(scope for scope in _SLACK_REQUIRED_SCOPES if scope not in granted_scopes)
        if missing_scopes:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.MISSING_PERMISSION,
                f"Slack token is missing required scopes: {', '.join(missing_scopes)}",
            )
        confirmed_scopes = _SLACK_REQUIRED_SCOPES + tuple(
            scope for scope in _SLACK_OPTIONAL_SCOPES if scope in granted_scopes
        )
        return CredentialTestSuccess(
            provider=IMProvider.SLACK,
            provider_tenant_id=auth_response.team_id,
            permissions=tuple(PermissionFact(name=scope, granted=True) for scope in confirmed_scopes),
        )

    def read_directory(self) -> DirectoryReadResult:
        credential_result = self.test_credentials()
        if isinstance(credential_result, OperationFailure):
            return credential_result

        directory_entries: list[DirectoryEntry] = []
        next_cursor: str | None = None
        while True:
            query_parameters = {"limit": str(self._config.directory_page_size or _DIRECTORY_PAGE_LIMIT)}
            if next_cursor is not None:
                query_parameters["cursor"] = next_cursor
            rate_limit_retries = 0
            while True:
                try:
                    response = self._http_client.get(
                        f"{_SLACK_API_ROOT}/users.list",
                        params=query_parameters,
                    )
                except httpx.RequestError:
                    return OperationFailure(
                        IMProvider.SLACK,
                        OperationFailureCode.DIRECTORY_INCOMPLETE,
                        "Slack directory request failed before the snapshot completed",
                    )
                if response.status_code != 429:
                    break
                retry_after = response.headers.get("retry-after", "")
                try:
                    retry_after_seconds = int(retry_after)
                except ValueError:
                    retry_after_seconds = -1
                if retry_after_seconds < 0 or rate_limit_retries >= _MAX_DIRECTORY_RATE_LIMIT_RETRIES:
                    return OperationFailure(
                        IMProvider.SLACK,
                        OperationFailureCode.DIRECTORY_INCOMPLETE,
                        "Slack directory remained rate limited before the snapshot completed",
                    )
                rate_limit_retries += 1
                time.sleep(retry_after_seconds)

            try:
                users_response = _SlackUsersResponse.model_validate_json(response.content)
            except ValidationError:
                return OperationFailure(
                    IMProvider.SLACK,
                    OperationFailureCode.DIRECTORY_INCOMPLETE,
                    "Slack directory response was invalid",
                )
            if response.status_code >= 400 or not users_response.ok:
                return OperationFailure(
                    IMProvider.SLACK,
                    OperationFailureCode.DIRECTORY_INCOMPLETE,
                    "Slack directory request was rejected before the snapshot completed",
                )

            for slack_user in users_response.members:
                display_name = (
                    slack_user.profile.display_name.strip()
                    or slack_user.profile.real_name.strip()
                    or slack_user.real_name.strip()
                    or slack_user.name.strip()
                    or slack_user.id
                )
                email = slack_user.profile.email.strip() if slack_user.profile.email else None
                directory_entries.append(
                    DirectoryEntry(
                        provider_user_id=slack_user.id,
                        display_name=display_name,
                        email=email or None,
                        available=not slack_user.deleted,
                    )
                )

            next_cursor = users_response.response_metadata.next_cursor.strip() or None
            if next_cursor is None:
                return DirectorySnapshot(
                    provider=IMProvider.SLACK,
                    provider_tenant_id=credential_result.provider_tenant_id,
                    entries=tuple(directory_entries),
                )

    def test_destination(self, destination: SlackUserDestination) -> DestinationTestResult:
        try:
            response = self._http_client.get(
                f"{_SLACK_API_ROOT}/users.info",
                params={"user": destination.user_id},
            )
            destination_response = _SlackUserResponse.model_validate_json(response.content)
        except httpx.RequestError:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.PROVIDER,
                "Slack destination check request failed",
            )
        except ValidationError:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.PROVIDER,
                "Slack destination check response was invalid",
            )
        if destination_response.error == "missing_scope":
            scope_description = (destination_response.needed or "").strip() or "users:read"
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.MISSING_PERMISSION,
                f"Slack token is missing destination scope: {scope_description}",
            )
        if (
            response.status_code >= 400
            or not destination_response.ok
            or destination_response.user is None
            or destination_response.user.id != destination.user_id
            or destination_response.user.deleted
        ):
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.DESTINATION_UNREACHABLE,
                "Slack user is not reachable by the bound app",
            )
        return None

    def send_text(
        self,
        destination: SlackUserDestination,
        body: str,
    ) -> MessageResult[SlackMessageReference]:
        request_body = _SlackTextMessagePayload(channel=destination.user_id, text=body)
        return self._send_message("chat.postMessage", request_body, expected_reference=None)

    def assess_card(self, intent: CardIntent) -> CardAssessment:
        if len(intent.actions) > _MAX_SLACK_ACTION_COUNT:
            return CardAssessment(
                representable=False,
                reason=f"Slack supports at most {_MAX_SLACK_ACTION_COUNT} actions in one actions block",
            )
        return CardAssessment(representable=True, reason=None)

    def send_card(
        self,
        destination: SlackUserDestination,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[SlackMessageReference]:
        assessment = self.assess_card(intent)
        if not assessment.representable:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.RENDERING,
                assessment.reason or "Slack cannot represent the card intent",
            )
        blocks = _render_card_blocks(intent, metadata)
        if isinstance(blocks, OperationFailure):
            return blocks
        request_body: dict[str, JsonValue] = {
            "channel": destination.user_id,
            "text": intent.fallback_text,
            "blocks": blocks,
        }
        return self._send_message("chat.postMessage", request_body, expected_reference=None)

    def update_card(
        self,
        reference: SlackMessageReference,
        intent: CardIntent,
        metadata: OpaqueMetadata,
    ) -> MessageResult[SlackMessageReference]:
        assessment = self.assess_card(intent)
        if not assessment.representable:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.RENDERING,
                assessment.reason or "Slack cannot represent the card intent",
            )
        blocks = _render_card_blocks(intent, metadata)
        if isinstance(blocks, OperationFailure):
            return blocks
        request_body: dict[str, JsonValue] = {
            "channel": reference.channel_id,
            "ts": reference.message_timestamp,
            "text": intent.fallback_text,
            "blocks": blocks,
        }
        return self._send_message("chat.update", request_body, expected_reference=reference)

    def _send_message(
        self,
        method_name: str,
        request_body: _SlackTextMessagePayload | dict[str, JsonValue],
        *,
        expected_reference: SlackMessageReference | None,
    ) -> MessageResult[SlackMessageReference]:
        try:
            response = self._http_client.post(
                f"{_SLACK_API_ROOT}/{method_name}",
                json=request_body,
            )
        except httpx.RequestError:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.AMBIGUOUS,
                "Slack message request failed with an ambiguous outcome",
            )
        try:
            message_response = _SlackMessageResponse.model_validate_json(response.content)
        except ValidationError:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.AMBIGUOUS,
                "Slack message response was invalid and the outcome is ambiguous",
            )
        if response.status_code == 429:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.RATE_LIMITED,
                "Slack rate limited the message request",
            )
        if method_name == "chat.update" and message_response.error in _SLACK_STALE_UPDATE_ERRORS:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.STALE_REFERENCE,
                "Slack no longer accepts the exact message reference",
            )
        if response.status_code >= 400 or not message_response.ok:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.PROVIDER,
                "Slack rejected the message request",
            )
        if not message_response.channel or not message_response.ts:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.AMBIGUOUS,
                "Slack accepted the request without an exact message reference",
            )
        response_reference = SlackMessageReference(
            channel_id=message_response.channel,
            message_timestamp=message_response.ts,
        )
        if expected_reference is not None and response_reference != expected_reference:
            return OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.AMBIGUOUS,
                "Slack update response did not preserve the requested message reference",
            )
        return MessageAccepted(
            reference=response_reference,
            provider_request_id=response.headers.get("x-slack-req-id"),
        )

    def parse_webhook(self, request: WebhookRequest) -> WebhookParseResult:
        if request.method != "POST":
            return WebhookRejected(_webhook_response(405, b'{"error":"method_not_allowed"}'))
        request_timestamp = _request_header(request, "x-slack-request-timestamp")
        supplied_signature = _request_header(request, "x-slack-signature")
        if request_timestamp is None or supplied_signature is None:
            return WebhookRejected(_webhook_response(401, b'{"error":"invalid_signature"}'))
        try:
            timestamp = int(request_timestamp)
        except ValueError:
            return WebhookRejected(_webhook_response(401, b'{"error":"invalid_signature"}'))
        if abs(request.received_at.timestamp() - timestamp) > _SLACK_MAX_REQUEST_AGE_SECONDS:
            return WebhookRejected(_webhook_response(401, b'{"error":"stale_request"}'))

        signature_base = f"{_SLACK_SIGNATURE_VERSION}:{request_timestamp}:".encode() + request.body
        expected_signature = (
            f"{_SLACK_SIGNATURE_VERSION}="
            + hmac.new(self._config.signing_secret.encode(), signature_base, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(expected_signature, supplied_signature):
            return WebhookRejected(_webhook_response(401, b'{"error":"invalid_signature"}'))

        content_type = (_request_header(request, "content-type") or "").partition(";")[0].strip().casefold()
        if content_type != "application/x-www-form-urlencoded":
            return WebhookRejected(_webhook_response(400, b'{"error":"unsupported_payload"}'))
        return self._parse_form_webhook(request, supplied_signature, timestamp)

    def _parse_form_webhook(
        self,
        request: WebhookRequest,
        signature: str,
        timestamp: int,
    ) -> WebhookParseResult:
        try:
            form_fields = tuple(
                parse_qsl(
                    request.body.decode("utf-8"),
                    keep_blank_values=True,
                    strict_parsing=True,
                )
            )
            if len(form_fields) != len({field_name for field_name, _ in form_fields}):
                raise ValueError("Slack form fields must be unique")
            provider_form = dict(form_fields)
        except (UnicodeDecodeError, ValueError):
            return WebhookRejected(_webhook_response(400, b'{"error":"invalid_payload"}'))

        interactive_payload = provider_form.get("payload")
        if interactive_payload is None:
            return WebhookRejected(_webhook_response(400, b'{"error":"unsupported_payload"}'))
        return self._parse_interactive_webhook(
            request,
            interactive_payload,
            signature,
            timestamp,
        )

    def _parse_interactive_webhook(
        self,
        request: WebhookRequest,
        interactive_payload: str,
        signature: str,
        timestamp: int,
    ) -> WebhookParseResult:
        try:
            provider_payload = _JSON_OBJECT_ADAPTER.validate_json(interactive_payload)
            envelope = _SlackInteractiveEnvelope.model_validate(provider_payload)
        except (ValueError, ValidationError):
            return WebhookRejected(_webhook_response(400, b'{"error":"invalid_payload"}'))
        event = AuthenticatedIMEvent(
            provider=IMProvider.SLACK,
            provider_tenant_id=envelope.team.id,
            provider_event_id=None,
            provider_event_time=None,
            received_at=request.received_at,
            provider_event_type=_SLACK_BLOCK_ACTIONS_EVENT_TYPE,
            provider_payload=ImmutableJSONObject(
                tuple((key, freeze_json_value(value)) for key, value in provider_payload.items())
            ),
        )
        return WebhookDelivery(
            event=event,
            accepted_response=_webhook_response(200, b""),
            retry_response=_webhook_response(503, b'{"error":"retry"}'),
            replay_key=self._webhook_replay_key(envelope.team.id, None, signature),
            replay_expires_at=datetime.fromtimestamp(timestamp + _SLACK_MAX_REQUEST_AGE_SECONDS, tz=UTC),
        )

    @staticmethod
    def _webhook_replay_key(team_id: str, event_id: str | None, signature: str) -> str:
        replay_identity = f"event:{team_id}:{event_id}" if event_id is not None else f"request:{signature}"
        return hashlib.sha256(replay_identity.encode()).hexdigest()

    def close(self) -> None:
        self._http_client.close()


class _SlackStreamSDKClient(Protocol):
    """Typed public lifecycle exposed by Slack's official Socket Mode SDK."""

    socket_mode_request_listeners: _SlackSocketModeRequestListeners

    def connect(self) -> None: ...

    def send_socket_mode_response(self, response: SocketModeResponse) -> None: ...

    def close(self) -> None: ...


class _SlackSocketModeRequestListeners(Protocol):
    """Append-only listener view shared by the SDK list and test clients."""

    def append(self, listener: _SlackSocketModeRequestListener, /) -> None: ...


class _SlackPinnedSocketModeClientLifecycle:
    """Public client view plus the exact 3.43.0 runner shutdown boundary.

    ``close`` terminates the active session state before delegating documented
    resource cleanup to the official client, then boundedly joins the omitted
    session runner. It reasserts termination after the public close because the
    runner target can race by resetting the state while it starts. A timeout
    leaves the runner reference intact and raises so the adapter-owned resource
    remains available to the existing retryable close lifecycle.
    """

    socket_mode_request_listeners: _SlackSocketModeRequestListeners
    _client: _PinnedSocketModeClient

    def __init__(self, client: _PinnedSocketModeClient) -> None:
        self._client = client
        self.socket_mode_request_listeners = client.socket_mode_request_listeners

    def connect(self) -> None:
        self._client.connect()

    def send_socket_mode_response(self, response: SocketModeResponse) -> None:
        self._client.send_socket_mode_response(response)

    def close(self) -> None:
        session_runner = self._client.current_session_runner
        runner_thread = session_runner.thread
        if runner_thread is None:
            self._client.close()
            session_runner.event.set()
            return
        session_state = self._client.current_session_state
        session_state.terminated = True
        session_runner.event.set()
        try:
            self._client.close()
        finally:
            session_state.terminated = True
        runner_thread.join(timeout=_STREAM_RUNNER_CLOSE_TIMEOUT_SECONDS)
        if runner_thread.is_alive():
            raise RuntimeError("Slack Socket Mode session runner did not stop before the close deadline")


class _SlackSocketModeEventListener:
    """Normalize Block Kit actions and retain Socket Mode ACK ownership."""

    _accept: Callable[[AuthenticatedIMEvent], EventAcceptance]

    def __init__(self, accept: Callable[[AuthenticatedIMEvent], EventAcceptance]) -> None:
        self._accept = accept

    def __call__(self, client: BaseSocketModeClient, request: SocketModeRequest) -> None:
        authenticated_event = self._normalize_business_delivery(request)
        if authenticated_event is None:
            return
        if self._accept(authenticated_event) is EventAcceptance.ACCEPTED:
            cast(_SlackStreamSDKClient, client).send_socket_mode_response(
                SocketModeResponse(envelope_id=request.envelope_id),
            )

    @staticmethod
    def _normalize_business_delivery(request: SocketModeRequest) -> AuthenticatedIMEvent | None:
        try:
            if request.type != _SLACK_INTERACTIVE_REQUEST_TYPE:
                return None
            request_payload = _JSON_OBJECT_ADAPTER.validate_python(request.payload)
            interactive = _SlackInteractiveEnvelope.model_validate(request_payload)
        except ValidationError:
            return None

        return AuthenticatedIMEvent(
            provider=IMProvider.SLACK,
            provider_tenant_id=interactive.team.id,
            provider_event_id=None,
            provider_event_time=None,
            received_at=datetime.now(UTC),
            provider_event_type=_SLACK_BLOCK_ACTIONS_EVENT_TYPE,
            provider_payload=ImmutableJSONObject(
                tuple((key, freeze_json_value(value)) for key, value in request_payload.items())
            ),
        )


class _SlackStreamClientRole:
    """Root-owned Socket Mode lifecycle isolated from stateless Web API calls.

    ``_state_lock`` protects run/close state and the active public client view;
    ``_client_close_lock`` serializes external close with the run-finally path.
    The active client is cleared only after successful cleanup so a bounded
    close failure remains available to the adapter context's retry lifecycle
    and blocks a later run from replacing the resource. ``_initializing``
    covers the ownership window before the client is published and while its
    listener/connect stop primitive is not yet safe for external cleanup.
    ``_run_complete`` prevents a successful SDK close from being mistaken for
    completion of the thread that still owns the published client.
    """

    _config: SlackAdapterConfig
    _state_lock: RLock
    _running: bool
    _initializing: bool
    _closed: bool
    _stream_client: _SlackStreamSDKClient | None
    _stream_client_closed: bool
    _client_close_lock: RLock
    _run_complete: Event

    def __init__(self, config: SlackAdapterConfig) -> None:
        self._config = config
        self._state_lock = RLock()
        self._running = False
        self._initializing = False
        self._closed = False
        self._stream_client = None
        self._stream_client_closed = False
        self._client_close_lock = RLock()
        self._run_complete = Event()
        self._run_complete.set()

    def run_stream(
        self,
        accept: Callable[[AuthenticatedIMEvent], EventAcceptance],
        stop: StopSignal,
    ) -> StreamRunResult:
        if stop.is_set():
            return None
        with self._state_lock:
            if self._closed:
                return OperationFailure(IMProvider.SLACK, OperationFailureCode.CLOSED, "Slack STREAM client is closed")
            if self._running:
                return OperationFailure(
                    IMProvider.SLACK,
                    OperationFailureCode.PROVIDER,
                    "Slack STREAM client is already running",
                )
            if self._stream_client is not None:
                return OperationFailure(
                    IMProvider.SLACK,
                    OperationFailureCode.PROVIDER,
                    "Slack STREAM client cleanup is incomplete",
                )
            self._running = True
            self._initializing = True
            self._run_complete.clear()

        stream_client: _SlackStreamSDKClient | None = None
        run_result: StreamRunResult = None
        try:
            stream_client = _build_slack_stream_sdk_client(self._config)
            with self._state_lock:
                self._stream_client = stream_client
                self._stream_client_closed = False
                close_requested = self._closed
            if close_requested:
                run_result = OperationFailure(
                    IMProvider.SLACK,
                    OperationFailureCode.CLOSED,
                    "Slack STREAM client is closed",
                )
            else:
                stream_client.socket_mode_request_listeners.append(_SlackSocketModeEventListener(accept))
                with self._state_lock:
                    close_requested = self._closed
                if not close_requested:
                    stream_client.connect()
                    with self._state_lock:
                        self._initializing = False
                        close_requested = self._closed
                    while not stop.is_set() and not close_requested:
                        with self._state_lock:
                            close_requested = self._closed
                        if not close_requested:
                            time.sleep(_STREAM_STOP_POLL_SECONDS)
        except Exception:
            logger.exception("Slack Socket Mode client stopped unexpectedly")
            run_result = OperationFailure(
                IMProvider.SLACK,
                OperationFailureCode.PROVIDER,
                "Slack STREAM client failed",
            )
        finally:
            try:
                if stream_client is not None:
                    self._close_stream_client(stream_client)
            except Exception:
                logger.exception("Slack Socket Mode client cleanup failed")
                if run_result is None:
                    run_result = OperationFailure(
                        IMProvider.SLACK,
                        OperationFailureCode.PROVIDER,
                        "Slack STREAM client cleanup failed",
                    )
            finally:
                with self._state_lock:
                    self._initializing = False
                    self._running = False
                    if self._stream_client_closed:
                        self._stream_client = None
                        self._stream_client_closed = False
                    self._run_complete.set()
        return run_result

    def close(self) -> None:
        """Suppress new runs and confirm the active SDK owner has exited."""
        with self._state_lock:
            self._closed = True
            initializing = self._initializing
            running = self._running
            stream_client = self._stream_client
        if initializing:
            raise RuntimeError("Slack STREAM cleanup must be retried after initialization finishes")
        if stream_client is not None:
            self._close_stream_client(stream_client)
        if running and not self._run_complete.wait(timeout=_STREAM_RUN_CLOSE_TIMEOUT_SECONDS):
            raise RuntimeError("Slack STREAM run did not finish before the close deadline")

    def _close_stream_client(self, stream_client: _SlackStreamSDKClient) -> None:
        with self._client_close_lock:
            with self._state_lock:
                if self._stream_client is not stream_client:
                    return
                if self._stream_client_closed:
                    return
            stream_client.close()
            with self._state_lock:
                if self._stream_client is stream_client:
                    self._stream_client_closed = True
                    if not self._running:
                        self._stream_client = None
                        self._stream_client_closed = False


def _build_slack_stream_sdk_client(config: SlackAdapterConfig) -> _SlackStreamSDKClient:
    client = SocketModeClient(
        app_token=config.app_token,
        web_client=WebClient(token=config.bot_token),
        auto_reconnect_enabled=True,
        concurrency=1,
    )
    if isinstance(client, _PinnedSocketModeClient):
        return _SlackPinnedSocketModeClientLifecycle(client)
    return cast(_SlackStreamSDKClient, client)


def create_slack_client_context(
    config: SlackAdapterConfig,
) -> _ProviderClientContext[SlackUserDestination, SlackMessageReference]:
    client = _SlackProviderClient(config, _build_http_client(config))
    stream = _SlackStreamClientRole(config)
    return _ProviderClientContext(
        credentials=client,
        directory=client,
        messaging=client,
        card=client,
        webhook=client,
        stream=stream,
        owned_resources=(client, stream),
    )
