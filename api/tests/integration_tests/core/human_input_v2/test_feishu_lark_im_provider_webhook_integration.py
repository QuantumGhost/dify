"""Receiver integration and independent crypto fixtures for Feishu/Lark Webhook."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import override

import pytest
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import JsonValue, TypeAdapter

from core.human_input_v2.entities import IMProvider
from core.human_input_v2.im_provider import (
    AuthenticatedIMEvent,
    EventAcceptance,
    FeishuLarkAdapter,
    FeishuLarkAdapterConfig,
    IMEventSink,
    WebhookRequest,
    thaw_json_value,
)

_ENCRYPT_KEY = "integration-encrypt-key"
_VERIFICATION_TOKEN = "integration-verification-token"
_TIMESTAMP = 1_787_000_000
_NOW = datetime.fromtimestamp(_TIMESTAMP, tz=UTC)
_FIXTURE_IV = b"fixture-iv-00001"


def _config(*, encrypt_key: str | None = _ENCRYPT_KEY) -> FeishuLarkAdapterConfig:
    return FeishuLarkAdapterConfig(
        provider=IMProvider.FEISHU,
        app_id="cli_integration",
        app_secret="integration-secret",
        verification_token=_VERIFICATION_TOKEN,
        encrypt_key=encrypt_key,
    )


@dataclass(slots=True)
class _Sink(IMEventSink):
    acceptance: EventAcceptance
    error: Exception | None = None
    events: list[AuthenticatedIMEvent] = field(default_factory=list)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        if self.error is not None:
            raise self.error
        return self.acceptance


def _event_body(
    *,
    event_id: str | None = "event-1",
    create_time: str | None = str((_TIMESTAMP - 1) * 1000),
    verification_token: str = _VERIFICATION_TOKEN,
) -> bytes:
    header: dict[str, str] = {
        "event_type": "card.action.trigger",
        "token": verification_token,
        "app_id": "cli_integration",
        "tenant_key": "tenant-key",
    }
    if event_id is not None:
        header["event_id"] = event_id
    if create_time is not None:
        header["create_time"] = create_time
    return json.dumps(
        {
            "schema": "2.0",
            "header": header,
            "event": {
                "operator": {"tenant_key": "tenant-key", "open_id": "ou-sender"},
                "token": "action-token",
                "action": {"tag": "button", "value": {"decision": "approve"}},
                "context": {"open_message_id": "om-message", "open_chat_id": "oc-chat"},
            },
        },
        separators=(",", ":"),
    ).encode()


def _encrypt_fixture(plaintext: bytes, *, encrypt_key: str = _ENCRYPT_KEY) -> str:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(encrypt_key.encode())
    key = digest.finalize()
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_plaintext = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(_FIXTURE_IV)).encryptor()
    ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()
    return base64.b64encode(_FIXTURE_IV + ciphertext).decode()


def _signed_request(
    body: bytes,
    *,
    timestamp: int = _TIMESTAMP,
    nonce: str = "integration-nonce",
    received_at: datetime = _NOW,
    signature_override: str | None = None,
) -> WebhookRequest:
    signature = hashlib.sha256(str(timestamp).encode() + nonce.encode() + _ENCRYPT_KEY.encode() + body).hexdigest()
    return WebhookRequest(
        method="POST",
        headers=(
            ("X-Lark-Request-Timestamp", str(timestamp)),
            ("X-Lark-Request-Nonce", nonce),
            ("X-Lark-Signature", signature_override or signature),
        ),
        query=(),
        body=body,
        received_at=received_at,
    )


def _encrypted_body(plaintext: bytes, *, encrypt_key: str = _ENCRYPT_KEY) -> bytes:
    return json.dumps(
        {"encrypt": _encrypt_fixture(plaintext, encrypt_key=encrypt_key)},
        separators=(",", ":"),
    ).encode()


def _encrypted_request(
    plaintext: bytes, *, event_timestamp: int = _TIMESTAMP, nonce: str = "integration-nonce"
) -> WebhookRequest:
    body = _encrypted_body(plaintext)
    return _signed_request(
        body,
        timestamp=event_timestamp,
        nonce=nonce,
        received_at=datetime.fromtimestamp(event_timestamp, tz=UTC),
    )


def test_feishu_lark_webhook_crypto_ack_replay_and_close_lifecycle() -> None:
    adapter = FeishuLarkAdapter(_config())
    challenge_body = json.dumps(
        {"type": "url_verification", "token": _VERIFICATION_TOKEN, "challenge": "challenge-1"},
        separators=(",", ":"),
    ).encode()
    challenge_sink = _Sink(EventAcceptance.ACCEPTED)
    challenge = adapter.webhook_events.handle(
        WebhookRequest("POST", (), (), challenge_body, _NOW),
        challenge_sink,
    )

    accepted_body = _event_body(event_id="event-accepted")
    accepted_sink = _Sink(EventAcceptance.ACCEPTED)
    accepted = adapter.webhook_events.handle(_encrypted_request(accepted_body), accepted_sink)
    replay_sink = _Sink(EventAcceptance.ACCEPTED)
    replay = adapter.webhook_events.handle(
        _encrypted_request(accepted_body, event_timestamp=_TIMESTAMP + 1, nonce="replay-nonce"),
        replay_sink,
    )

    retry_request = _encrypted_request(_event_body(event_id="event-retry"))
    retry_sink = _Sink(EventAcceptance.RETRY)
    retry = adapter.webhook_events.handle(retry_request, retry_sink)
    retry_sink.acceptance = EventAcceptance.ACCEPTED
    accepted_redelivery = adapter.webhook_events.handle(retry_request, retry_sink)
    accepted_replay = adapter.webhook_events.handle(retry_request, retry_sink)

    failing_sink = _Sink(EventAcceptance.ACCEPTED, RuntimeError("storage unavailable"))
    failed = adapter.webhook_events.handle(
        _encrypted_request(_event_body(event_id="event-failure")),
        failing_sink,
    )

    assert challenge.status_code == 200
    assert challenge_sink.events == []
    assert accepted.status_code == 200
    assert accepted_sink.events[0].provider_event_id == "event-accepted"
    assert replay.status_code == 200
    assert replay_sink.events == []
    assert retry.status_code == 500
    assert accepted_redelivery.status_code == 200
    assert accepted_replay.status_code == 200
    assert len(retry_sink.events) == 2
    assert failed.status_code == 500

    adapter.close()
    closed = adapter.webhook_events.handle(_encrypted_request(accepted_body), _Sink(EventAcceptance.ACCEPTED))
    assert closed.status_code == 503


def test_feishu_lark_plaintext_webhook_preserves_nested_payload_without_synthesizing_identity() -> None:
    provider_envelope = TypeAdapter(dict[str, JsonValue]).validate_json(_event_body(event_id=None, create_time=None))
    provider_envelope["event"] = {
        "primitive": None,
        "members": ["value", 1, True, {"nested": "fact"}],
    }
    body = json.dumps(provider_envelope, separators=(",", ":")).encode()
    sink = _Sink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config(encrypt_key=None))

    result = adapter.webhook_events.handle(WebhookRequest("POST", (), (), body, _NOW), sink)

    assert result.status_code == 200
    assert sink.events[0].provider_event_id is None
    assert sink.events[0].provider_event_time is None
    assert thaw_json_value(sink.events[0].provider_payload) == {
        "primitive": None,
        "members": ["value", 1, True, {"nested": "fact"}],
    }
    adapter.close()


@pytest.mark.parametrize(
    "rejection_kind",
    [
        "method",
        "invalid_json",
        "encrypted_without_key",
        "invalid_base64",
        "short_ciphertext",
        "wrong_encrypt_key",
        "invalid_encrypted_plaintext",
        "wrong_challenge_token",
        "missing_challenge",
        "wrong_schema",
        "blank_event_id",
        "blank_event_type",
        "wrong_event_token",
        "missing_signature_headers",
        "invalid_timestamp",
        "stale_timestamp",
        "wrong_signature",
        "invalid_event_time",
    ],
)
def test_feishu_lark_webhook_rejects_invalid_crypto_or_payload_before_sink(
    rejection_kind: str,
) -> None:
    adapter = FeishuLarkAdapter(
        _config(encrypt_key=None if rejection_kind == "encrypted_without_key" else _ENCRYPT_KEY)
    )
    if rejection_kind == "method":
        request = WebhookRequest("GET", (), (), b"{}", _NOW)
    elif rejection_kind == "invalid_json":
        request = WebhookRequest("POST", (), (), b"not-json", _NOW)
    elif rejection_kind == "invalid_base64":
        request = _signed_request(b'{"encrypt":"not@base64"}')
    elif rejection_kind == "short_ciphertext":
        body = json.dumps({"encrypt": base64.b64encode(_FIXTURE_IV).decode()}).encode()
        request = _signed_request(body)
    elif rejection_kind == "wrong_encrypt_key":
        request = _signed_request(_encrypted_body(_event_body(), encrypt_key="different-key"))
    elif rejection_kind == "invalid_encrypted_plaintext":
        request = _signed_request(_encrypted_body(b"not-json"))
    elif rejection_kind in {"wrong_challenge_token", "missing_challenge"}:
        challenge = {
            "type": "url_verification",
            "token": "wrong-token" if rejection_kind == "wrong_challenge_token" else _VERIFICATION_TOKEN,
            "challenge": None if rejection_kind == "missing_challenge" else "challenge-1",
        }
        request = WebhookRequest("POST", (), (), json.dumps(challenge).encode(), _NOW)
    else:
        provider_envelope = TypeAdapter(dict[str, JsonValue]).validate_json(_event_body())
        header = TypeAdapter(dict[str, JsonValue]).validate_python(provider_envelope["header"])
        if rejection_kind == "wrong_schema":
            provider_envelope["schema"] = "1.0"
        elif rejection_kind == "blank_event_id":
            header["event_id"] = " "
        elif rejection_kind == "blank_event_type":
            header["event_type"] = " "
        elif rejection_kind == "wrong_event_token":
            header["token"] = "wrong-token"
        elif rejection_kind == "invalid_event_time":
            header["create_time"] = "not-a-timestamp"
        provider_envelope["header"] = header
        body = json.dumps(provider_envelope, separators=(",", ":")).encode()
        if rejection_kind == "encrypted_without_key":
            request = _signed_request(_encrypted_body(body))
        elif rejection_kind == "missing_signature_headers":
            request = WebhookRequest("POST", (), (), body, _NOW)
        elif rejection_kind == "invalid_timestamp":
            request = WebhookRequest(
                "POST",
                (
                    ("X-Lark-Request-Timestamp", "invalid"),
                    ("X-Lark-Request-Nonce", "nonce"),
                    ("X-Lark-Signature", "invalid"),
                ),
                (),
                body,
                _NOW,
            )
        elif rejection_kind == "stale_timestamp":
            request = _signed_request(body, received_at=_NOW + timedelta(seconds=301))
        elif rejection_kind == "wrong_signature":
            request = _signed_request(body, signature_override="invalid")
        else:
            request = _signed_request(body)
    sink = _Sink(EventAcceptance.ACCEPTED)

    result = adapter.webhook_events.handle(request, sink)

    assert result.status_code in {400, 401, 405}
    assert sink.events == []
    adapter.close()
