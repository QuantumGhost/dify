import logging

import pytest

from models.im_delivery import IMMessageCardStatus
from models.im_integration import IMProvider
from services.human_input_im.card_update_compensation_service import (
    IMCardUpdateCompensationRequest,
    LoggingIMCardUpdateCompensationQueue,
)


def test_logging_card_update_compensation_queue_logs_identifiers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = IMCardUpdateCompensationRequest(
        correlation_id="correlation-1",
        provider=IMProvider.FEISHU,
        provider_message_id="message-1",
        target_status=IMMessageCardStatus.SUBMITTED,
        last_provider_event_id="event-1",
        metadata={"form_id": "form-1", "recipient_id": "recipient-1"},
    )

    with caplog.at_level(logging.INFO, logger="services.human_input_im.card_update_compensation_service"):
        LoggingIMCardUpdateCompensationQueue().enqueue(request)

    assert "Queued IM card update compensation placeholder" in caplog.text
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.correlation_id == "correlation-1"
    assert record.provider == IMProvider.FEISHU.value
    assert record.provider_message_id == "message-1"
    assert record.provider_event_id == "event-1"
    assert record.target_card_status == IMMessageCardStatus.SUBMITTED.value
    assert record.form_id == "form-1"
    assert record.recipient_id == "recipient-1"
