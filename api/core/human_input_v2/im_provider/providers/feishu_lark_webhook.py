"""Feishu/Lark Webhook authentication, decryption, and event normalization.

The Webhook role is stateless and shares only the adapter's immutable config.
Challenges are authenticated by their verification token as in the official
SDK. Business events additionally require the official SHA-256 request
signature and a fresh timestamp whenever an encryption key is configured.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError, field_validator

from ..contracts import (
    AuthenticatedIMEvent,
    ImmutableJSONObject,
    WebhookChallenge,
    WebhookDelivery,
    WebhookParseResult,
    WebhookRejected,
    WebhookRequest,
    WebhookResponse,
    freeze_json_value,
)
from ..provider_types import FeishuLarkAdapterConfig

_MAX_REQUEST_AGE_SECONDS = 300
_CARD_ACTION_EVENT_TYPE = "card.action.trigger"
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class _EncryptedEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    encrypt: str | None = None


class _ChallengeEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str | None = None
    token: str | None = None
    challenge: str | None = None


class _EventHeader(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    event_id: str | None = None
    event_type: str
    create_time: str | None = None
    token: str
    tenant_key: str

    @field_validator("event_id", "create_time")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional event header text must not be blank")
        return value

    @field_validator("event_type", "token", "tenant_key")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("event header text must not be blank")
        return value


class _V2EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    schema_: str = Field(alias="schema")
    header: _EventHeader
    event: dict[str, JsonValue]

    @field_validator("schema_", mode="before")
    @classmethod
    def validate_schema(cls, value: object) -> object:
        if value != "2.0":
            raise ValueError("event schema must be 2.0")
        return value


def _header(request: WebhookRequest, name: str) -> str | None:
    normalized_name = name.casefold()
    for header_name, header_value in request.headers:
        if header_name.casefold() == normalized_name:
            return header_value
    return None


def _response(status_code: int, body: dict[str, JsonValue]) -> WebhookResponse:
    return WebhookResponse(
        status_code,
        (("content-type", "application/json; charset=utf-8"),),
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(),
    )


def _decrypt(ciphertext: str, encrypt_key: str) -> bytes:
    encrypted_bytes = base64.b64decode(ciphertext, validate=True)
    block_size_bytes = algorithms.AES.block_size // 8
    if len(encrypted_bytes) < block_size_bytes * 2 or len(encrypted_bytes) % block_size_bytes != 0:
        raise ValueError("encrypted envelope length is invalid")
    digest = hashes.Hash(hashes.SHA256())
    digest.update(encrypt_key.encode())
    key = digest.finalize()
    iv = encrypted_bytes[:block_size_bytes]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded_plaintext = decryptor.update(encrypted_bytes[block_size_bytes:]) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    return unpadder.update(padded_plaintext) + unpadder.finalize()


def _event_time(create_time: str | None) -> datetime | None:
    if create_time is None:
        return None
    timestamp_milliseconds = int(create_time)
    return datetime.fromtimestamp(timestamp_milliseconds / 1000, tz=UTC)


class _FeishuLarkWebhookClient:
    """Stateless Webhook role bound to one immutable adapter config."""

    _config: FeishuLarkAdapterConfig

    def __init__(self, config: FeishuLarkAdapterConfig) -> None:
        self._config = config

    def parse_webhook(self, request: WebhookRequest) -> WebhookParseResult:
        if request.method != "POST":
            return WebhookRejected(_response(405, {"msg": "method_not_allowed"}))
        try:
            request_envelope = _EncryptedEnvelope.model_validate_json(request.body)
        except ValidationError:
            return WebhookRejected(_response(400, {"msg": "invalid_payload"}))

        encrypted = request_envelope.encrypt is not None
        plaintext = request.body
        if encrypted:
            if self._config.encrypt_key is None:
                return WebhookRejected(_response(401, {"msg": "invalid_encryption"}))
            try:
                plaintext = _decrypt(request_envelope.encrypt or "", self._config.encrypt_key)
            except (binascii.Error, UnicodeError, ValueError):
                return WebhookRejected(_response(401, {"msg": "invalid_encryption"}))
        try:
            provider_envelope = _JSON_OBJECT_ADAPTER.validate_json(plaintext)
            challenge = _ChallengeEnvelope.model_validate(provider_envelope)
        except ValidationError:
            status_code = 401 if encrypted else 400
            return WebhookRejected(_response(status_code, {"msg": "invalid_payload"}))
        if challenge.type == "url_verification":
            if challenge.token != self._config.verification_token or not challenge.challenge:
                return WebhookRejected(_response(401, {"msg": "invalid_token"}))
            return WebhookChallenge(_response(200, {"challenge": challenge.challenge}))

        try:
            event_envelope = _V2EventEnvelope.model_validate(provider_envelope)
        except ValidationError:
            return WebhookRejected(_response(400, {"msg": "unsupported_payload"}))
        if event_envelope.header.token != self._config.verification_token:
            return WebhookRejected(_response(401, {"msg": "invalid_token"}))

        signature_facts = self._verify_signature(request)
        if signature_facts is None:
            return WebhookRejected(_response(401, {"msg": "invalid_signature"}))
        if event_envelope.header.event_type != _CARD_ACTION_EVENT_TYPE:
            return WebhookRejected(_response(400, {"msg": "unsupported_payload"}))
        signature, replay_expires_at = signature_facts
        try:
            provider_event_time = _event_time(event_envelope.header.create_time)
            event = AuthenticatedIMEvent(
                provider=self._config.provider,
                provider_tenant_id=event_envelope.header.tenant_key,
                provider_event_id=event_envelope.header.event_id,
                provider_event_time=provider_event_time,
                received_at=request.received_at,
                provider_event_type=event_envelope.header.event_type,
                provider_payload=ImmutableJSONObject(
                    tuple((key, freeze_json_value(value)) for key, value in event_envelope.event.items())
                ),
            )
        except (OSError, OverflowError, ValueError):
            return WebhookRejected(_response(400, {"msg": "invalid_payload"}))

        replay_identity = (
            f"event:{event.provider_tenant_id}:{event.provider_event_id}"
            if event.provider_event_id is not None
            else f"request:{signature}:{hashlib.sha256(request.body).hexdigest()}"
        )
        replay_key = hashlib.sha256(replay_identity.encode()).hexdigest()
        return WebhookDelivery(
            event=event,
            accepted_response=_response(200, {}),
            retry_response=_response(500, {"msg": "retry"}),
            replay_key=replay_key,
            replay_expires_at=replay_expires_at,
        )

    def _verify_signature(self, request: WebhookRequest) -> tuple[str, datetime] | None:
        if self._config.encrypt_key is None:
            signature = hashlib.sha256(request.body).hexdigest()
            return signature, request.received_at + timedelta(seconds=_MAX_REQUEST_AGE_SECONDS)
        timestamp_value = _header(request, "x-lark-request-timestamp")
        nonce = _header(request, "x-lark-request-nonce")
        supplied_signature = _header(request, "x-lark-signature")
        if timestamp_value is None or nonce is None or supplied_signature is None:
            return None
        try:
            timestamp = int(timestamp_value)
            replay_expires_at = datetime.fromtimestamp(timestamp + _MAX_REQUEST_AGE_SECONDS, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
        if abs(request.received_at.timestamp() - timestamp) > _MAX_REQUEST_AGE_SECONDS:
            return None
        signature_material = (
            timestamp_value.encode() + nonce.encode() + self._config.encrypt_key.encode() + request.body
        )
        expected_signature = hashlib.sha256(signature_material).hexdigest()
        if not hmac.compare_digest(expected_signature, supplied_signature):
            return None
        return supplied_signature, replay_expires_at


def create_feishu_lark_webhook_client(config: FeishuLarkAdapterConfig) -> _FeishuLarkWebhookClient:
    return _FeishuLarkWebhookClient(config)
