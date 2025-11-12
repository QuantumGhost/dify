import datetime
import os
import uuid
from typing import Any

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import sessionmaker

from core.file.enums import FileTransferMethod
from models.enums import CreatorUserRole
from models.model import (
    AppAnnotationHitHistory,
    Conversation,
    Message,
    MessageAgentThought,
    MessageAnnotation,
    MessageChain,
    MessageFeedback,
    MessageFile,
)
from models.workflow import ConversationVariable, WorkflowAppLog, WorkflowNodeExecutionModel, WorkflowRun
from recover_workflow_runlogs import _model_to_dict, restore_workflow_runs_batch

PG_TEST_BASE_URL = os.getenv("PG_TEST_BASE_URL", "postgresql://postgres:pg-prod@127.0.0.1:5435")
PG_ADMIN_URL = f"{PG_TEST_BASE_URL}/postgres"


def _create_postgres_test_engine(prefix: str) -> tuple[Any, str]:
    db_name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()
    engine = create_engine(f"{PG_TEST_BASE_URL}/{db_name}")
    return engine, db_name


def _drop_postgres_test_database(db_name: str) -> None:
    admin_engine = create_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(
            text(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :db_name AND pid <> pg_backend_pid()
                """
            ),
            {"db_name": db_name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    admin_engine.dispose()


def _create_tables(engine):
    tables = [
        WorkflowRun.__table__,
        WorkflowAppLog.__table__,
        WorkflowNodeExecutionModel.__table__,
        Conversation.__table__,
        ConversationVariable.__table__,
        Message.__table__,
        MessageChain.__table__,
        MessageAgentThought.__table__,
        MessageFile.__table__,
        MessageAnnotation.__table__,
        AppAnnotationHitHistory.__table__,
        MessageFeedback.__table__,
    ]
    metadata = MetaData()
    for table in tables:
        cloned = table.tometadata(metadata)
        for column in cloned.c:
            column.server_default = None
            column.server_onupdate = None
        cloned.create(bind=engine)


def _seed_backup(session):
    now = datetime.datetime.utcnow()
    tenant_id = str(uuid.uuid4())
    app_id = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    workflow_run_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    chain_id = str(uuid.uuid4())
    account_id = str(uuid.uuid4())
    end_user_id = str(uuid.uuid4())
    log_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    conversation_variable_id = str(uuid.uuid4())
    message_thought_id = str(uuid.uuid4())
    message_file_id = str(uuid.uuid4())
    annotation_id = str(uuid.uuid4())
    hit_history_id = str(uuid.uuid4())
    feedback_id = str(uuid.uuid4())

    workflow_run = WorkflowRun(
        id=workflow_run_id,
        tenant_id=tenant_id,
        app_id=app_id,
        workflow_id=workflow_id,
        type="test",
        triggered_from="app-run",
        version="1",
        graph="{}",
        inputs="{}",
        status="succeeded",
        outputs="{}",
        elapsed_time=1.0,
        total_tokens=10,
        total_steps=1,
        created_by_role="account",
        created_by=account_id,
        created_at=now,
        finished_at=now,
    )
    session.add(workflow_run)

    workflow_log = WorkflowAppLog(
        id=log_id,
        tenant_id=tenant_id,
        app_id=app_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        created_from="service-api",
        created_by_role="account",
        created_by=account_id,
        created_at=now,
    )
    session.add(workflow_log)

    node_execution = WorkflowNodeExecutionModel(
        id=node_id,
        tenant_id=tenant_id,
        app_id=app_id,
        workflow_id=workflow_id,
        triggered_from="workflow-run",
        workflow_run_id=workflow_run_id,
        index=1,
        predecessor_node_id=None,
        node_execution_id="exec-1",
        node_id="node-1",
        node_type="task",
        title="Task",
        inputs="{}",
        process_data="{}",
        outputs="{}",
        status="succeeded",
        error=None,
        elapsed_time=0.5,
        execution_metadata="{}",
        created_at=now,
        created_by_role="account",
        created_by=account_id,
        finished_at=now,
    )
    session.add(node_execution)

    conversation = Conversation(
        id=conversation_id,
        app_id=app_id,
        mode="advanced-chat",
        name="Test Conversation",
        _inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        invoke_from="mock",
        from_source="api",
        from_end_user_id=end_user_id,
        from_account_id=account_id,
        created_at=now,
        updated_at=now,
    )
    conversation.is_deleted = False
    session.add(conversation)

    conversation_variable = ConversationVariable(
        id=conversation_variable_id,
        conversation_id=conversation_id,
        app_id=app_id,
        data="{}",
    )
    conversation_variable.created_at = now
    conversation_variable.updated_at = now
    session.add(conversation_variable)

    message = Message(
        id=message_id,
        app_id=app_id,
        model_provider="mock",
        model_id="mock-model",
        override_model_configs=None,
        conversation_id=conversation_id,
        _inputs={"prompt": "hi"},
        query="hi",
        message={"role": "assistant", "content": "hello"},
        message_tokens=10,
        message_unit_price=0,
        message_price_unit=0,
        answer="hello",
        answer_tokens=10,
        answer_unit_price=0,
        answer_price_unit=0,
        provider_response_latency=0.1,
        total_price=0,
        currency="USD",
        status="normal",
        from_source="api",
        from_end_user_id=end_user_id,
        from_account_id=account_id,
        created_at=now,
        updated_at=now,
        agent_based=False,
        workflow_run_id=workflow_run_id,
        app_mode="advanced-chat",
    )
    session.add(message)

    message_chain = MessageChain(
        id=chain_id,
        message_id=message_id,
        type="tool",
        input="{}",
        output="{}",
        created_at=now,
    )
    session.add(message_chain)

    message_thought = MessageAgentThought(
        id=message_thought_id,
        message_id=message_id,
        message_chain_id=chain_id,
        position=1,
        thought="thinking",
        tool="tool",
        tool_labels_str="{}",
        tool_meta_str="{}",
        tool_input="{}",
        observation="result",
        tool_process_data="{}",
        message="{}",
        message_token=1,
        message_unit_price=0,
        message_price_unit=0,
        answer="{}",
        answer_token=1,
        answer_unit_price=0,
        answer_price_unit=0,
        tokens=1,
        total_price=0,
        currency="USD",
        latency=0.1,
        created_by_role="account",
        created_by=account_id,
        created_at=now,
    )
    session.add(message_thought)

    message_file = MessageFile(
        message_id=message_id,
        type="image",
        transfer_method=FileTransferMethod.LOCAL_FILE,
        url="http://example.com",
        belongs_to="assistant",
        upload_file_id=None,
        created_by_role=CreatorUserRole.ACCOUNT,
        created_by=account_id,
    )
    message_file.id = message_file_id
    message_file.created_at = now
    session.add(message_file)

    annotation = MessageAnnotation(
        id=annotation_id,
        app_id=app_id,
        conversation_id=conversation_id,
        message_id=message_id,
        question="q",
        content="c",
        hit_count=0,
        account_id=account_id,
        created_at=now,
        updated_at=now,
    )
    session.add(annotation)

    hit_history = AppAnnotationHitHistory(
        id=hit_history_id,
        app_id=app_id,
        annotation_id=annotation_id,
        source="mock",
        question="q",
        account_id=account_id,
        created_at=now,
        score=1,
        message_id=message_id,
        annotation_question="q",
        annotation_content="c",
    )
    session.add(hit_history)

    feedback = MessageFeedback(
        id=feedback_id,
        app_id=app_id,
        conversation_id=conversation_id,
        message_id=message_id,
        rating="like",
        content="good",
        from_source="user",
        from_end_user_id=end_user_id,
        from_account_id=account_id,
        created_at=now,
        updated_at=now,
    )
    session.add(feedback)

    session.commit()
    return workflow_run_id


def test_restore_workflow_runs_batch_restores_all_related_rows():
    source_engine, source_db = _create_postgres_test_engine("source")
    target_engine, target_db = _create_postgres_test_engine("target")
    try:
        _create_tables(source_engine)
        _create_tables(target_engine)

        source_session_factory = sessionmaker(source_engine, expire_on_commit=False)
        target_session_factory = sessionmaker(target_engine, expire_on_commit=False)

        with source_session_factory() as source_session:
            workflow_run_id = _seed_backup(source_session)

        restored = restore_workflow_runs_batch(
            source_session_factory, target_session_factory, [workflow_run_id], dry_run=False
        )

        assert restored > 0

        with target_session_factory() as session:
            assert session.get(WorkflowRun, workflow_run_id)
            assert session.query(WorkflowAppLog).count() == 1
            assert session.query(WorkflowNodeExecutionModel).count() == 1
            assert session.query(Conversation).count() == 1
            assert session.query(ConversationVariable).count() == 1
            assert session.query(Message).count() == 1
            assert session.query(MessageChain).count() == 1
            assert session.query(MessageAgentThought).count() == 1
            assert session.query(MessageFile).count() == 1
            assert session.query(MessageAnnotation).count() == 1
            assert session.query(AppAnnotationHitHistory).count() == 1
            assert session.query(MessageFeedback).count() == 1
    finally:
        source_engine.dispose()
        target_engine.dispose()
        _drop_postgres_test_database(source_db)
        _drop_postgres_test_database(target_db)


def test_restore_workflow_runs_batch_is_idempotent():
    source_engine, source_db = _create_postgres_test_engine("source")
    target_engine, target_db = _create_postgres_test_engine("target")
    try:
        _create_tables(source_engine)
        _create_tables(target_engine)

        source_session_factory = sessionmaker(source_engine, expire_on_commit=False)
        target_session_factory = sessionmaker(target_engine, expire_on_commit=False)

        with source_session_factory() as source_session:
            workflow_run_id = _seed_backup(source_session)

        restore_workflow_runs_batch(
            source_session_factory, target_session_factory, [workflow_run_id], dry_run=False
        )
        restored_second_time = restore_workflow_runs_batch(
            source_session_factory, target_session_factory, [workflow_run_id], dry_run=False
        )

        assert restored_second_time == 0

        with target_session_factory() as session:
            assert session.query(WorkflowRun).count() == 1
            assert session.query(WorkflowAppLog).count() == 1
            assert session.query(WorkflowNodeExecutionModel).count() == 1
            assert session.query(Message).count() == 1
    finally:
        source_engine.dispose()
        target_engine.dispose()
        _drop_postgres_test_database(source_db)
        _drop_postgres_test_database(target_db)


def test_model_to_dict_handles_private_attribute_mapping():
    engine = create_engine("sqlite://")
    _create_tables(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)

    now = datetime.datetime.utcnow()
    conversation_id = "conv-model-to-dict"

    with session_factory.begin() as session:
        conversation = Conversation(
            id=conversation_id,
            app_id="app-1",
            mode="advanced-chat",
            name="ModelToDict Test",
            _inputs={"prompt": "hello"},
            introduction="",
            system_instruction="",
            system_instruction_tokens=0,
            status="normal",
            invoke_from="mock",
            from_source="api",
            from_end_user_id="end-user-1",
            from_account_id="user-1",
            created_at=now,
            updated_at=now,
        )
        conversation.is_deleted = False
        session.add(conversation)

    with session_factory() as session:
        loaded = session.get(Conversation, conversation_id)
        model_dict = _model_to_dict(loaded)

    assert model_dict["_inputs"] == {"prompt": "hello"}
