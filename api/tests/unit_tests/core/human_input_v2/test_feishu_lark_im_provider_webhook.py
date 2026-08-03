"""Feishu and Lark Webhook tests with independently generated crypto fixtures."""

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
from pydantic import TypeAdapter

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

_ENCRYPT_KEY = "encrypt-test"
_VERIFICATION_TOKEN = "verification-test"
_TIMESTAMP = 1_787_000_000
_NOW = datetime.fromtimestamp(_TIMESTAMP, tz=UTC)
_FIXTURE_IV = b"fixture-iv-00001"


def _config(
    *,
    encrypt_key: str | None = _ENCRYPT_KEY,
    verification_token: str = _VERIFICATION_TOKEN,
) -> FeishuLarkAdapterConfig:
    return FeishuLarkAdapterConfig(
        provider=IMProvider.FEISHU,
        app_id="cli_test",
        app_secret="secret-test",
        verification_token=verification_token,
        encrypt_key=encrypt_key,
    )


@dataclass
class _RecordingSink(IMEventSink):
    acceptance: EventAcceptance
    events: list[AuthenticatedIMEvent] = field(default_factory=list)

    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        self.events.append(event)
        return self.acceptance


class _FailingSink(IMEventSink):
    @override
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance:
        raise RuntimeError("sink failed")


def _encrypt_fixture(plaintext: bytes, *, encrypt_key: str = _ENCRYPT_KEY) -> str:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(encrypt_key.encode())
    key = digest.finalize()
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_plaintext = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(_FIXTURE_IV)).encryptor()
    ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()
    return base64.b64encode(_FIXTURE_IV + ciphertext).decode()


def _event_body(
    *,
    event_id: str | None = "event-1",
    verification_token: str = _VERIFICATION_TOKEN,
    tenant_key: str = "tenant-key",
) -> bytes:
    header: dict[str, str] = {
        "event_type": "card.action.trigger",
        "create_time": str((_TIMESTAMP - 1) * 1000),
        "token": verification_token,
        "app_id": "cli_test",
        "tenant_key": tenant_key,
    }
    if event_id is not None:
        header["event_id"] = event_id
    return json.dumps(
        {
            "schema": "2.0",
            "header": header,
            "event": {
                "operator": {"tenant_key": tenant_key, "open_id": "ou-sender"},
                "token": "action-token",
                "action": {"tag": "button", "value": {"decision": "approve"}},
                "context": {"open_message_id": "om-message", "open_chat_id": "oc-chat"},
            },
        },
        separators=(",", ":"),
    ).encode()


def _signed_request(
    body: bytes,
    *,
    timestamp: int = _TIMESTAMP,
    nonce: str = "nonce-test",
    encrypt_key: str = _ENCRYPT_KEY,
    received_at: datetime = _NOW,
    signature_override: str | None = None,
) -> WebhookRequest:
    signature = hashlib.sha256(str(timestamp).encode() + nonce.encode() + encrypt_key.encode() + body).hexdigest()
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


def _encrypted_request(plaintext: bytes, *, encrypt_key: str = _ENCRYPT_KEY) -> WebhookRequest:
    body = json.dumps(
        {"encrypt": _encrypt_fixture(plaintext, encrypt_key=encrypt_key)},
        separators=(",", ":"),
    ).encode()
    return _signed_request(body, encrypt_key=encrypt_key)


def _card_action_request(
    plaintext: bytes,
    *,
    timestamp: int = _TIMESTAMP,
    nonce: str = "card-action-nonce",
    received_at: datetime = _NOW,
) -> WebhookRequest:
    body = json.dumps(
        {"encrypt": _encrypt_fixture(plaintext)},
        separators=(",", ":"),
    ).encode()
    signature_material = str(timestamp).encode() + nonce.encode() + _VERIFICATION_TOKEN.encode() + body
    signature = hashlib.sha1(signature_material, usedforsecurity=False).hexdigest()
    return WebhookRequest(
        method="POST",
        headers=(
            ("X-Lark-Request-Timestamp", str(timestamp)),
            ("X-Lark-Request-Nonce", nonce),
            ("X-Lark-Signature", signature),
        ),
        query=(),
        body=body,
        received_at=received_at,
    )


def test_feishu_webhook_authenticates_challenge_without_calling_sink() -> None:
    valid_body = json.dumps(
        {"type": "url_verification", "token": _VERIFICATION_TOKEN, "challenge": "challenge-1"},
        separators=(",", ":"),
    ).encode()
    invalid_body = json.dumps(
        {"type": "url_verification", "token": "wrong-token", "challenge": "challenge-1"},
        separators=(",", ":"),
    ).encode()
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())

    valid = adapter.webhook_events.handle(
        WebhookRequest("POST", (), (), valid_body, _NOW),
        sink,
    )
    invalid = adapter.webhook_events.handle(
        WebhookRequest("POST", (), (), invalid_body, _NOW),
        sink,
    )

    assert valid.status_code == 200
    assert TypeAdapter(dict[str, str]).validate_json(valid.body) == {"challenge": "challenge-1"}
    assert invalid.status_code == 401
    assert sink.events == []

    adapter.close()


@pytest.mark.parametrize(
    ("acceptance", "expected_status"),
    [(EventAcceptance.ACCEPTED, 200), (EventAcceptance.RETRY, 500)],
)
def test_feishu_webhook_decrypts_authenticated_event_and_maps_sink_acceptance(
    acceptance: EventAcceptance,
    expected_status: int,
) -> None:
    sink = _RecordingSink(acceptance)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(_encrypted_request(_event_body()), sink)

    assert result.status_code == expected_status
    expected_body = b"{}" if acceptance is EventAcceptance.ACCEPTED else b'{"msg":"retry"}'
    assert result.body == expected_body
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.provider is IMProvider.FEISHU
    assert event.provider_tenant_id == "tenant-key"
    assert event.provider_event_id == "event-1"
    assert event.provider_event_time == datetime.fromtimestamp(_TIMESTAMP - 1, tz=UTC)
    assert event.received_at == _NOW
    assert event.provider_event_type == "card.action.trigger"
    assert thaw_json_value(event.provider_payload) == {
        "operator": {"tenant_key": "tenant-key", "open_id": "ou-sender"},
        "token": "action-token",
        "action": {"tag": "button", "value": {"decision": "approve"}},
        "context": {"open_message_id": "om-message", "open_chat_id": "oc-chat"},
    }

    adapter.close()


def test_feishu_webhook_accepts_signed_plaintext_event() -> None:
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(_signed_request(_event_body()), sink)

    assert result.status_code == 200
    assert len(sink.events) == 1

    adapter.close()


def test_feishu_webhook_accepts_official_card_action_signature() -> None:
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(_card_action_request(_event_body()), sink)

    assert result.status_code == 200
    assert len(sink.events) == 1

    adapter.close()


def test_feishu_webhook_without_encrypt_key_uses_verification_token_and_event_replay_key() -> None:
    provider_envelope = TypeAdapter(dict[str, object]).validate_json(_event_body())
    header = TypeAdapter(dict[str, object]).validate_python(provider_envelope["header"])
    del header["create_time"]
    provider_envelope["header"] = header
    request = WebhookRequest(
        "POST",
        (),
        (),
        json.dumps(provider_envelope, separators=(",", ":")).encode(),
        _NOW,
    )
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config(encrypt_key=None))

    first = adapter.webhook_events.handle(request, sink)
    replay = adapter.webhook_events.handle(request, sink)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert len(sink.events) == 1
    assert sink.events[0].provider_event_time is None

    adapter.close()


@pytest.mark.parametrize(
    "rejection_kind",
    [
        "missing_headers",
        "stale_timestamp",
        "wrong_signature",
        "tampered_body",
        "wrong_encrypt_key",
        "wrong_verification_token",
    ],
)
def test_feishu_webhook_rejects_unauthenticated_event_without_sink(
    rejection_kind: str,
) -> None:
    plaintext = _event_body(
        verification_token="wrong-token" if rejection_kind == "wrong_verification_token" else _VERIFICATION_TOKEN
    )
    encrypted_request = _encrypted_request(
        plaintext,
        encrypt_key="fixture-other-key" if rejection_kind == "wrong_encrypt_key" else _ENCRYPT_KEY,
    )
    if rejection_kind == "missing_headers":
        request = WebhookRequest("POST", (), (), encrypted_request.body, _NOW)
    elif rejection_kind == "stale_timestamp":
        request = _signed_request(
            encrypted_request.body,
            timestamp=_TIMESTAMP,
            received_at=_NOW + timedelta(seconds=301),
        )
    elif rejection_kind == "wrong_signature":
        request = _signed_request(encrypted_request.body, signature_override="invalid")
    elif rejection_kind == "tampered_body":
        request = WebhookRequest(
            encrypted_request.method,
            encrypted_request.headers,
            encrypted_request.query,
            encrypted_request.body + b" ",
            encrypted_request.received_at,
        )
    else:
        request = encrypted_request
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(request, sink)

    assert result.status_code == 401
    assert sink.events == []

    adapter.close()


@pytest.mark.parametrize(
    "invalid_envelope",
    [
        json.dumps({"encrypt": base64.b64encode(b"too-short").decode()}).encode(),
        json.dumps({"encrypt": _encrypt_fixture(b"[]")}).encode(),
    ],
    ids=("invalid_ciphertext_length", "decrypted_non_object"),
)
def test_feishu_webhook_rejects_invalid_encrypted_envelopes(
    invalid_envelope: bytes,
) -> None:
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(_signed_request(invalid_envelope), sink)

    assert result.status_code == 401
    assert sink.events == []

    adapter.close()


def test_feishu_webhook_rejects_encrypted_event_without_bound_key() -> None:
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config(encrypt_key=None))

    result = adapter.webhook_events.handle(_encrypted_request(_event_body()), sink)

    assert result.status_code == 401
    assert sink.events == []

    adapter.close()


@pytest.mark.parametrize(
    ("header_field", "invalid_value"),
    [
        ("event_id", " "),
        ("tenant_key", " "),
        ("create_time", str(10**30)),
    ],
)
def test_feishu_webhook_rejects_invalid_event_header_without_sink(
    header_field: str,
    invalid_value: str,
) -> None:
    provider_envelope = TypeAdapter(dict[str, object]).validate_json(_event_body())
    header = TypeAdapter(dict[str, object]).validate_python(provider_envelope["header"])
    header[header_field] = invalid_value
    provider_envelope["header"] = header
    request = _signed_request(json.dumps(provider_envelope, separators=(",", ":")).encode())
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(request, sink)

    assert result.status_code == 400
    assert sink.events == []

    adapter.close()


def test_feishu_webhook_rejects_non_numeric_request_timestamp() -> None:
    signed_request = _signed_request(_event_body())
    request = WebhookRequest(
        signed_request.method,
        tuple(
            (name, "not-a-timestamp") if name == "X-Lark-Request-Timestamp" else (name, value)
            for name, value in signed_request.headers
        ),
        signed_request.query,
        signed_request.body,
        signed_request.received_at,
    )
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(request, sink)

    assert result.status_code == 401
    assert sink.events == []

    adapter.close()


def test_feishu_webhook_remembers_only_accepted_replays() -> None:
    request = _encrypted_request(_event_body())
    sink = _RecordingSink(EventAcceptance.RETRY)
    adapter = FeishuLarkAdapter(_config())

    retry = adapter.webhook_events.handle(request, sink)
    sink.acceptance = EventAcceptance.ACCEPTED
    accepted = adapter.webhook_events.handle(request, sink)
    replay = adapter.webhook_events.handle(request, sink)

    assert retry.status_code == 500
    assert accepted.status_code == 200
    assert replay.status_code == 200
    assert len(sink.events) == 2

    adapter.close()


def test_feishu_webhook_does_not_synthesize_missing_event_id() -> None:
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(_signed_request(_event_body(event_id=None)), sink)

    assert result.status_code == 200
    assert sink.events[0].provider_event_id is None

    adapter.close()


def test_feishu_webhook_sink_failure_returns_retry_response() -> None:
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(_signed_request(_event_body()), _FailingSink())

    assert result.status_code == 500
    assert result.body == b'{"msg":"retry"}'

    adapter.close()


def test_feishu_webhook_rejects_non_v2_event_schema_without_sink() -> None:
    provider_envelope = TypeAdapter(dict[str, object]).validate_json(_event_body())
    provider_envelope["schema"] = "1.0"
    request = _signed_request(json.dumps(provider_envelope, separators=(",", ":")).encode())
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(request, sink)

    assert result.status_code == 400
    assert sink.events == []

    adapter.close()


@pytest.mark.parametrize(
    ("webhook_request", "expected_status"),
    [
        (WebhookRequest("GET", (), (), b"", _NOW), 405),
        (WebhookRequest("POST", (), (), b"not-json", _NOW), 400),
    ],
)
def test_feishu_webhook_rejects_invalid_request_shape_without_sink(
    webhook_request: WebhookRequest,
    expected_status: int,
) -> None:
    sink = _RecordingSink(EventAcceptance.ACCEPTED)
    adapter = FeishuLarkAdapter(_config())

    result = adapter.webhook_events.handle(webhook_request, sink)

    assert result.status_code == expected_status
    assert sink.events == []

    adapter.close()
