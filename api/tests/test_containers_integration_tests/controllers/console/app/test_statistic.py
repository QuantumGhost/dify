"""Controller integration tests for console statistic routes."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from core.app.entities.app_invoke_entities import InvokeFrom
from models.enums import ConversationFromSource, FeedbackFromSource, FeedbackRating
from models.model import AppMode, Conversation, Message, MessageFeedback
from tests.test_containers_integration_tests.controllers.console.helpers import (
    authenticate_console_client,
    create_console_account_and_tenant,
    create_console_app,
)


def test_daily_message_statistic_groups_by_local_date_and_excludes_debugger_messages(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    account.timezone = "Asia/Tokyo"
    db_session_with_containers.commit()

    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    other_app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 14, 0, 0),
        updated_at=datetime(2024, 1, 1, 14, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()
    other_conversation = Conversation(
        app_id=other_app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=other_app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 14, 0, 0),
        updated_at=datetime(2024, 1, 1, 14, 0, 0),
    )
    db_session_with_containers.add(other_conversation)
    db_session_with_containers.commit()

    message_1 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 14, 30, 0),
        updated_at=datetime(2024, 1, 1, 14, 30, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_1)
    db_session_with_containers.commit()
    message_2 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 15, 30, 0),
        updated_at=datetime(2024, 1, 1, 15, 30, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_2)
    db_session_with_containers.commit()
    message_3 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 1, 0, 0),
        updated_at=datetime(2024, 1, 2, 1, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_3)
    db_session_with_containers.commit()
    message_4 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.DEBUGGER,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 16, 0, 0),
        updated_at=datetime(2024, 1, 1, 16, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_4)
    db_session_with_containers.commit()
    message_5 = Message(
        app_id=other_app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=other_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 14, 30, 0),
        updated_at=datetime(2024, 1, 1, 14, 30, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_5)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-messages",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [
            {"date": "2024-01-01", "message_count": 1},
            {"date": "2024-01-02", "message_count": 2},
        ]
    }


def test_daily_message_statistic_applies_start_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_6 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 23, 59, 0),
        updated_at=datetime(2024, 1, 1, 23, 59, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_6)
    db_session_with_containers.commit()
    message_7 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_7)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-messages?start=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "message_count": 1}]}


def test_daily_message_statistic_applies_end_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_8 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_8)
    db_session_with_containers.commit()
    message_9 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_9)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-messages?end=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-01", "message_count": 1}]}


def test_daily_message_statistic_applies_start_and_end_filters_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_10 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 23, 59, 0),
        updated_at=datetime(2024, 1, 1, 23, 59, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_10)
    db_session_with_containers.commit()
    message_11 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 8, 0, 0),
        updated_at=datetime(2024, 1, 2, 8, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_11)
    db_session_with_containers.commit()
    message_12 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 0, 0, 0),
        updated_at=datetime(2024, 1, 3, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_12)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-messages?start=2024-01-02 00:00&end=2024-01-03 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "message_count": 1}]}


def test_daily_conversation_statistic_counts_distinct_conversations_per_message_date(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    other_app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    conversation_one = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation_one)
    db_session_with_containers.commit()
    conversation_two = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 1, 0, 0),
        updated_at=datetime(2024, 1, 1, 1, 0, 0),
    )
    db_session_with_containers.add(conversation_two)
    db_session_with_containers.commit()
    other_conversation = Conversation(
        app_id=other_app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=other_app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(other_conversation)
    db_session_with_containers.commit()

    message_13 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_one.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 9, 0, 0),
        updated_at=datetime(2024, 1, 1, 9, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_13)
    db_session_with_containers.commit()
    message_14 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_one.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_14)
    db_session_with_containers.commit()
    message_15 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_two.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 11, 0, 0),
        updated_at=datetime(2024, 1, 1, 11, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_15)
    db_session_with_containers.commit()
    message_16 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_one.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 9, 0, 0),
        updated_at=datetime(2024, 1, 2, 9, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_16)
    db_session_with_containers.commit()
    message_17 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_two.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.DEBUGGER,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_17)
    db_session_with_containers.commit()
    message_18 = Message(
        app_id=other_app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=other_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 9, 0, 0),
        updated_at=datetime(2024, 1, 1, 9, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_18)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-conversations",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [
            {"date": "2024-01-01", "conversation_count": 2},
            {"date": "2024-01-02", "conversation_count": 1},
        ]
    }


def test_daily_conversation_statistic_applies_start_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    conversation_one = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation_one)
    db_session_with_containers.commit()
    conversation_two = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
    )
    db_session_with_containers.add(conversation_two)
    db_session_with_containers.commit()

    message_19 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_one.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_19)
    db_session_with_containers.commit()
    message_20 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_two.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_20)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-conversations?start=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "conversation_count": 1}]}


def test_daily_conversation_statistic_applies_end_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    conversation_one = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation_one)
    db_session_with_containers.commit()
    conversation_two = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
    )
    db_session_with_containers.add(conversation_two)
    db_session_with_containers.commit()

    message_21 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_one.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_21)
    db_session_with_containers.commit()
    message_22 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_two.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_22)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-conversations?end=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-01", "conversation_count": 1}]}


def test_daily_conversation_statistic_applies_start_and_end_filters_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    conversation_one = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation_one)
    db_session_with_containers.commit()
    conversation_two = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
    )
    db_session_with_containers.add(conversation_two)
    db_session_with_containers.commit()
    conversation_three = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 0, 0, 0),
        updated_at=datetime(2024, 1, 3, 0, 0, 0),
    )
    db_session_with_containers.add(conversation_three)
    db_session_with_containers.commit()

    message_23 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_one.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_23)
    db_session_with_containers.commit()
    message_24 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_two.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 10, 0, 0),
        updated_at=datetime(2024, 1, 2, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_24)
    db_session_with_containers.commit()
    message_25 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation_three.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 0, 0, 0),
        updated_at=datetime(2024, 1, 3, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_25)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-conversations?start=2024-01-02 00:00&end=2024-01-03 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "conversation_count": 1}]}


def test_daily_terminals_statistic_counts_distinct_non_null_end_users_per_date(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    other_app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()
    other_conversation = Conversation(
        app_id=other_app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=other_app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(other_conversation)
    db_session_with_containers.commit()

    first_end_user = str(uuid4())
    second_end_user = str(uuid4())

    message_26 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=first_end_user,
        from_account_id=None,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_26)
    db_session_with_containers.commit()
    message_27 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=first_end_user,
        from_account_id=None,
        created_at=datetime(2024, 1, 1, 11, 0, 0),
        updated_at=datetime(2024, 1, 1, 11, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_27)
    db_session_with_containers.commit()
    message_28 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=second_end_user,
        from_account_id=None,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_28)
    db_session_with_containers.commit()
    message_29 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=None,
        created_at=datetime(2024, 1, 1, 13, 0, 0),
        updated_at=datetime(2024, 1, 1, 13, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_29)
    db_session_with_containers.commit()
    message_30 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=second_end_user,
        from_account_id=None,
        created_at=datetime(2024, 1, 2, 9, 0, 0),
        updated_at=datetime(2024, 1, 2, 9, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_30)
    db_session_with_containers.commit()
    message_31 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.DEBUGGER,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=str(uuid4()),
        from_account_id=None,
        created_at=datetime(2024, 1, 1, 14, 0, 0),
        updated_at=datetime(2024, 1, 1, 14, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_31)
    db_session_with_containers.commit()
    message_32 = Message(
        app_id=other_app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=other_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=str(uuid4()),
        from_account_id=None,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_32)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-end-users",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [
            {"date": "2024-01-01", "terminal_count": 2},
            {"date": "2024-01-02", "terminal_count": 1},
        ]
    }


def test_daily_terminals_statistic_applies_start_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_33 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=str(uuid4()),
        from_account_id=None,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_33)
    db_session_with_containers.commit()
    included_end_user = str(uuid4())
    message_34 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=included_end_user,
        from_account_id=None,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_34)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-end-users?start=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "terminal_count": 1}]}


def test_daily_terminals_statistic_applies_end_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_35 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=str(uuid4()),
        from_account_id=None,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_35)
    db_session_with_containers.commit()
    message_36 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=str(uuid4()),
        from_account_id=None,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_36)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-end-users?end=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-01", "terminal_count": 1}]}


def test_daily_terminals_statistic_applies_start_and_end_filters_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_37 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=str(uuid4()),
        from_account_id=None,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_37)
    db_session_with_containers.commit()
    message_38 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=str(uuid4()),
        from_account_id=None,
        created_at=datetime(2024, 1, 2, 10, 0, 0),
        updated_at=datetime(2024, 1, 2, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_38)
    db_session_with_containers.commit()
    message_39 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=str(uuid4()),
        from_account_id=None,
        created_at=datetime(2024, 1, 3, 0, 0, 0),
        updated_at=datetime(2024, 1, 3, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_39)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-end-users?start=2024-01-02 00:00&end=2024-01-03 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "terminal_count": 1}]}


def test_daily_token_cost_statistic_sums_tokens_and_total_price_per_date(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    other_app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()
    other_conversation = Conversation(
        app_id=other_app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=other_app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(other_conversation)
    db_session_with_containers.commit()

    message_40 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=3,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=7,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_40)
    db_session_with_containers.commit()
    message_41 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=11,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=13,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.02"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 11, 0, 0),
        updated_at=datetime(2024, 1, 1, 11, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_41)
    db_session_with_containers.commit()
    message_42 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=4,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=6,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.03"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 9, 0, 0),
        updated_at=datetime(2024, 1, 2, 9, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_42)
    db_session_with_containers.commit()
    message_43 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=100,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=100,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("9.99"),
        currency="USD",
        invoke_from=InvokeFrom.DEBUGGER,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_43)
    db_session_with_containers.commit()
    message_44 = Message(
        app_id=other_app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=other_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=100,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=100,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("9.99"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_44)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/token-costs",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [
            {"date": "2024-01-01", "token_count": 34, "total_price": "0.03", "currency": "USD"},
            {"date": "2024-01-02", "token_count": 10, "total_price": "0.03", "currency": "USD"},
        ]
    }


def test_daily_token_cost_statistic_applies_start_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_45 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=5,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=5,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 23, 59, 0),
        updated_at=datetime(2024, 1, 1, 23, 59, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_45)
    db_session_with_containers.commit()
    message_46 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=6,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=4,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.02"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_46)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/token-costs?start=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [{"date": "2024-01-02", "token_count": 10, "total_price": "0.02", "currency": "USD"}]
    }


def test_daily_token_cost_statistic_applies_end_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_47 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=5,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=5,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 23, 59, 0),
        updated_at=datetime(2024, 1, 1, 23, 59, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_47)
    db_session_with_containers.commit()
    message_48 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=6,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=4,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.02"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_48)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/token-costs?end=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [{"date": "2024-01-01", "token_count": 10, "total_price": "0.01", "currency": "USD"}]
    }


def test_daily_token_cost_statistic_applies_start_and_end_filters_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_49 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=5,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=5,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_49)
    db_session_with_containers.commit()
    message_50 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=6,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=4,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.02"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 12, 0, 0),
        updated_at=datetime(2024, 1, 2, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_50)
    db_session_with_containers.commit()
    message_51 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=7,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=3,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.03"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 0, 0, 0),
        updated_at=datetime(2024, 1, 3, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_51)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/token-costs?start=2024-01-02 00:00&end=2024-01-03 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [{"date": "2024-01-02", "token_count": 10, "total_price": "0.02", "currency": "USD"}]
    }


def test_average_session_interaction_statistic_uses_conversation_creation_date_and_non_debugger_messages(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    account.timezone = "Asia/Tokyo"
    db_session_with_containers.commit()

    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    first_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 15, 30, 0),
        updated_at=datetime(2024, 1, 1, 15, 30, 0),
    )
    db_session_with_containers.add(first_conversation)
    db_session_with_containers.commit()
    second_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 16, 0, 0),
        updated_at=datetime(2024, 1, 1, 16, 0, 0),
    )
    db_session_with_containers.add(second_conversation)
    db_session_with_containers.commit()
    third_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 2, 0, 0),
        updated_at=datetime(2024, 1, 2, 2, 0, 0),
    )
    db_session_with_containers.add(third_conversation)
    db_session_with_containers.commit()
    debugger_only_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 16, 30, 0),
        updated_at=datetime(2024, 1, 1, 16, 30, 0),
    )
    db_session_with_containers.add(debugger_only_conversation)
    db_session_with_containers.commit()

    message_52 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=first_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 4, 0, 0),
        updated_at=datetime(2024, 1, 2, 4, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_52)
    db_session_with_containers.commit()
    message_53 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=first_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 4, 0, 0),
        updated_at=datetime(2024, 1, 3, 4, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_53)
    db_session_with_containers.commit()
    message_54 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=second_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 5, 0, 0),
        updated_at=datetime(2024, 1, 3, 5, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_54)
    db_session_with_containers.commit()
    message_55 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=third_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 10, 0, 0),
        updated_at=datetime(2024, 1, 2, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_55)
    db_session_with_containers.commit()
    message_56 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=third_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 11, 0, 0),
        updated_at=datetime(2024, 1, 2, 11, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_56)
    db_session_with_containers.commit()
    message_57 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=third_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 12, 0, 0),
        updated_at=datetime(2024, 1, 2, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_57)
    db_session_with_containers.commit()
    message_58 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=debugger_only_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.DEBUGGER,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 13, 0, 0),
        updated_at=datetime(2024, 1, 2, 13, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_58)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/average-session-interactions",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [
            {"date": "2024-01-02", "interactions": 1.5},
            {"date": "2024-01-03", "interactions": 3.0},
        ]
    }


def test_average_session_interaction_statistic_applies_start_filter_to_conversation_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    first_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 23, 59, 0),
        updated_at=datetime(2024, 1, 1, 23, 59, 0),
    )
    db_session_with_containers.add(first_conversation)
    db_session_with_containers.commit()
    second_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
    )
    db_session_with_containers.add(second_conversation)
    db_session_with_containers.commit()

    message_59 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=first_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 8, 0, 0),
        updated_at=datetime(2024, 1, 3, 8, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_59)
    db_session_with_containers.commit()
    message_60 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=second_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 9, 0, 0),
        updated_at=datetime(2024, 1, 3, 9, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_60)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/average-session-interactions?start=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "interactions": 1.0}]}


def test_average_session_interaction_statistic_applies_end_filter_to_conversation_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    first_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 23, 59, 0),
        updated_at=datetime(2024, 1, 1, 23, 59, 0),
    )
    db_session_with_containers.add(first_conversation)
    db_session_with_containers.commit()
    second_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
    )
    db_session_with_containers.add(second_conversation)
    db_session_with_containers.commit()

    message_61 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=first_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 8, 0, 0),
        updated_at=datetime(2024, 1, 3, 8, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_61)
    db_session_with_containers.commit()
    message_62 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=second_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 9, 0, 0),
        updated_at=datetime(2024, 1, 3, 9, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_62)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/average-session-interactions?end=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-01", "interactions": 1.0}]}


def test_average_session_interaction_statistic_applies_start_and_end_filters_to_conversation_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    first_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
    )
    db_session_with_containers.add(first_conversation)
    db_session_with_containers.commit()
    second_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 12, 0, 0),
        updated_at=datetime(2024, 1, 2, 12, 0, 0),
    )
    db_session_with_containers.add(second_conversation)
    db_session_with_containers.commit()
    third_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 0, 0, 0),
        updated_at=datetime(2024, 1, 3, 0, 0, 0),
    )
    db_session_with_containers.add(third_conversation)
    db_session_with_containers.commit()

    message_63 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=first_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 8, 0, 0),
        updated_at=datetime(2024, 1, 3, 8, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_63)
    db_session_with_containers.commit()
    message_64 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=second_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 9, 0, 0),
        updated_at=datetime(2024, 1, 3, 9, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_64)
    db_session_with_containers.commit()
    message_65 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=third_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 10, 0, 0),
        updated_at=datetime(2024, 1, 3, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_65)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/average-session-interactions"
        "?start=2024-01-02 00:00&end=2024-01-03 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "interactions": 1.0}]}


def test_user_satisfaction_rate_statistic_counts_only_like_feedback_and_keeps_per_thousand_formula(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    first_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(first_conversation)
    db_session_with_containers.commit()
    second_conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
    )
    db_session_with_containers.add(second_conversation)
    db_session_with_containers.commit()

    first_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=first_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(first_message)
    db_session_with_containers.commit()
    second_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=first_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 11, 0, 0),
        updated_at=datetime(2024, 1, 1, 11, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(second_message)
    db_session_with_containers.commit()
    third_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=first_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(third_message)
    db_session_with_containers.commit()
    fourth_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=second_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 10, 0, 0),
        updated_at=datetime(2024, 1, 2, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(fourth_message)
    db_session_with_containers.commit()
    debugger_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=second_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.DEBUGGER,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 11, 0, 0),
        updated_at=datetime(2024, 1, 2, 11, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(debugger_message)
    db_session_with_containers.commit()

    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=first_conversation.id,
            message_id=first_message.id,
            rating=FeedbackRating.LIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.commit()
    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=first_conversation.id,
            message_id=second_message.id,
            rating=FeedbackRating.LIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.commit()
    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=first_conversation.id,
            message_id=third_message.id,
            rating=FeedbackRating.DISLIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=second_conversation.id,
            message_id=debugger_message.id,
            rating=FeedbackRating.LIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/user-satisfaction-rate",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [
            {"date": "2024-01-01", "rate": 666.67},
            {"date": "2024-01-02", "rate": 0.0},
        ]
    }


def test_user_satisfaction_rate_statistic_applies_start_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    excluded_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(excluded_message)
    db_session_with_containers.commit()
    included_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(included_message)
    db_session_with_containers.commit()
    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=conversation.id,
            message_id=excluded_message.id,
            rating=FeedbackRating.LIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.commit()
    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=conversation.id,
            message_id=included_message.id,
            rating=FeedbackRating.LIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/user-satisfaction-rate?start=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "rate": 1000.0}]}


def test_user_satisfaction_rate_statistic_applies_end_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    included_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(included_message)
    db_session_with_containers.commit()
    excluded_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(excluded_message)
    db_session_with_containers.commit()
    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=conversation.id,
            message_id=included_message.id,
            rating=FeedbackRating.LIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.commit()
    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=conversation.id,
            message_id=excluded_message.id,
            rating=FeedbackRating.LIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/user-satisfaction-rate?end=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-01", "rate": 1000.0}]}


def test_user_satisfaction_rate_statistic_applies_start_and_end_filters_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    before_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(before_message)
    db_session_with_containers.commit()
    included_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 12, 0, 0),
        updated_at=datetime(2024, 1, 2, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(included_message)
    db_session_with_containers.commit()
    after_message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 0, 0, 0),
        updated_at=datetime(2024, 1, 3, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(after_message)
    db_session_with_containers.commit()
    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=conversation.id,
            message_id=before_message.id,
            rating=FeedbackRating.LIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.commit()
    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=conversation.id,
            message_id=included_message.id,
            rating=FeedbackRating.LIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.commit()
    db_session_with_containers.add(
        MessageFeedback(
            app_id=app.id,
            conversation_id=conversation.id,
            message_id=after_message.id,
            rating=FeedbackRating.LIKE,
            from_source=FeedbackFromSource.ADMIN,
            from_account_id=account.id,
        )
    )
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/user-satisfaction-rate?start=2024-01-02 00:00&end=2024-01-03 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "rate": 1000.0}]}


def test_average_response_time_statistic_averages_latency_and_returns_milliseconds(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.COMPLETION)
    other_app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.COMPLETION)

    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()
    other_conversation = Conversation(
        app_id=other_app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=other_app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(other_conversation)
    db_session_with_containers.commit()

    message_66 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.2,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_66)
    db_session_with_containers.commit()
    message_67 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=0.8,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 11, 0, 0),
        updated_at=datetime(2024, 1, 1, 11, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_67)
    db_session_with_containers.commit()
    message_68 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=0.5,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 9, 0, 0),
        updated_at=datetime(2024, 1, 2, 9, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_68)
    db_session_with_containers.commit()
    message_69 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=99.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.DEBUGGER,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_69)
    db_session_with_containers.commit()
    message_70 = Message(
        app_id=other_app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=other_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=99.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_70)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/average-response-time",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [
            {"date": "2024-01-01", "latency": 1000.0},
            {"date": "2024-01-02", "latency": 500.0},
        ]
    }


def test_average_response_time_statistic_applies_start_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.COMPLETION)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_71 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=0.8,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 23, 59, 0),
        updated_at=datetime(2024, 1, 1, 23, 59, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_71)
    db_session_with_containers.commit()
    message_72 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.2,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_72)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/average-response-time?start=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "latency": 1200.0}]}


def test_average_response_time_statistic_applies_end_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.COMPLETION)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_73 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=0.8,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 23, 59, 0),
        updated_at=datetime(2024, 1, 1, 23, 59, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_73)
    db_session_with_containers.commit()
    message_74 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.2,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_74)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/average-response-time?end=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-01", "latency": 800.0}]}


def test_average_response_time_statistic_applies_start_and_end_filters_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.COMPLETION)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_75 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=0.8,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_75)
    db_session_with_containers.commit()
    message_76 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.2,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 10, 0, 0),
        updated_at=datetime(2024, 1, 2, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_76)
    db_session_with_containers.commit()
    message_77 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.4,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 0, 0, 0),
        updated_at=datetime(2024, 1, 3, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_77)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/average-response-time?start=2024-01-02 00:00&end=2024-01-03 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "latency": 1200.0}]}


def test_tokens_per_second_statistic_uses_answer_tokens_sum_over_latency_sum_and_handles_zero_latency(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    other_app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()
    other_conversation = Conversation(
        app_id=other_app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=other_app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(other_conversation)
    db_session_with_containers.commit()

    message_78 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=40,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=2.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_78)
    db_session_with_containers.commit()
    message_79 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=20,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 11, 0, 0),
        updated_at=datetime(2024, 1, 1, 11, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_79)
    db_session_with_containers.commit()
    message_80 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=5,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=0.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 9, 0, 0),
        updated_at=datetime(2024, 1, 2, 9, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_80)
    db_session_with_containers.commit()
    message_81 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=999,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=0.001,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.DEBUGGER,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_81)
    db_session_with_containers.commit()
    message_82 = Message(
        app_id=other_app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=other_conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=999,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=0.001,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_82)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/tokens-per-second",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "data": [
            {"date": "2024-01-01", "tps": 20.0},
            {"date": "2024-01-02", "tps": 0.0},
        ]
    }


def test_tokens_per_second_statistic_applies_start_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_83 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=10,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=2.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 23, 59, 0),
        updated_at=datetime(2024, 1, 1, 23, 59, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_83)
    db_session_with_containers.commit()
    message_84 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=12,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=3.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_84)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/tokens-per-second?start=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "tps": 4.0}]}


def test_tokens_per_second_statistic_applies_end_filter_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_85 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=10,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=2.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 23, 59, 0),
        updated_at=datetime(2024, 1, 1, 23, 59, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_85)
    db_session_with_containers.commit()
    message_86 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=12,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=3.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 0, 0, 0),
        updated_at=datetime(2024, 1, 2, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_86)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/tokens-per-second?end=2024-01-02 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-01", "tps": 5.0}]}


def test_tokens_per_second_statistic_applies_start_and_end_filters_to_message_created_at(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()

    message_87 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=10,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=2.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_87)
    db_session_with_containers.commit()
    message_88 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=12,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=3.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 2, 10, 0, 0),
        updated_at=datetime(2024, 1, 2, 10, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_88)
    db_session_with_containers.commit()
    message_89 = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=14,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=7.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 3, 0, 0, 0),
        updated_at=datetime(2024, 1, 3, 0, 0, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message_89)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/tokens-per-second?start=2024-01-02 00:00&end=2024-01-03 00:00",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-02", "tps": 4.0}]}


def test_daily_message_statistic_returns_bad_request_when_time_range_is_invalid(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-messages?start=invalid&end=invalid",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 400
    assert "Invalid start time format" in response.get_json()["message"]


def test_daily_message_statistic_treats_empty_time_range_strings_as_unfiltered_query(
    db_session_with_containers: Session,
    test_client_with_containers: FlaskClient,
) -> None:
    account, tenant = create_console_account_and_tenant(db_session_with_containers)
    app = create_console_app(db_session_with_containers, tenant.id, account.id, AppMode.CHAT)
    conversation = Conversation(
        app_id=app.id,
        app_model_config_id=None,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        mode=app.mode,
        name="Stats Conversation",
        inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        from_source=ConversationFromSource.CONSOLE,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 0, 0),
        updated_at=datetime(2024, 1, 1, 10, 0, 0),
    )
    db_session_with_containers.add(conversation)
    db_session_with_containers.commit()
    message = Message(
        app_id=app.id,
        model_provider=None,
        model_id="",
        override_model_configs=None,
        conversation_id=conversation.id,
        inputs={},
        query="Hello",
        message={"type": "text", "content": "Hello"},
        message_tokens=1,
        message_unit_price=Decimal("0.001"),
        message_price_unit=Decimal("0.001"),
        answer="Hi there",
        answer_tokens=1,
        answer_unit_price=Decimal("0.001"),
        answer_price_unit=Decimal("0.001"),
        parent_message_id=None,
        provider_response_latency=1.0,
        total_price=Decimal("0.01"),
        currency="USD",
        invoke_from=InvokeFrom.EXPLORE,
        from_source=ConversationFromSource.CONSOLE,
        from_end_user_id=None,
        from_account_id=account.id,
        created_at=datetime(2024, 1, 1, 10, 30, 0),
        updated_at=datetime(2024, 1, 1, 10, 30, 0),
        app_mode=AppMode.CHAT,
    )
    db_session_with_containers.add(message)
    db_session_with_containers.commit()

    response = test_client_with_containers.get(
        f"/console/api/apps/{app.id}/statistics/daily-messages?start=&end=",
        headers=authenticate_console_client(test_client_with_containers, account),
    )

    assert response.status_code == 200
    assert response.get_json() == {"data": [{"date": "2024-01-01", "message_count": 1}]}
