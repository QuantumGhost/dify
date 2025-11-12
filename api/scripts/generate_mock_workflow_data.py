#!/usr/bin/env python3
"""
Utility script for seeding mock workflow run data.

The generator creates a coherent set of rows that exercise every table touched by
the cleanup/recovery scripts:

* workflow_runs
* workflow_app_logs
* workflow_node_executions
* conversations
* workflow_conversation_variables
* messages
* message_chains
* message_agent_thoughts
* message_files
* message_annotations
* app_annotation_hit_histories
* message_feedbacks

Dates are spread across a configurable window so it is easy to target specific
batches during manual testing.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import click
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from configs import dify_config
from core.file.enums import FileTransferMethod, FileType
from models.enums import CreatorUserRole, WorkflowRunTriggeredFrom
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

DEFAULT_DATE_FMT = "%Y-%m-%d"


@dataclass(slots=True)
class GenerationConfig:
    database_url: str
    workflow_runs: int
    messages_per_run: int
    nodes_per_run: int
    variables_per_conversation: int
    days_span: int
    start_date: datetime
    tenant_id: str
    app_id: str
    workflow_id: str
    account_id: str
    end_user_id: str
    created_by_role: str = CreatorUserRole.ACCOUNT.value


@dataclass
class GenerationStats:
    workflow_runs: int = 0
    messages: int = 0
    annotations: int = 0
    node_executions: int = 0


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url)
    return sessionmaker(engine, expire_on_commit=False)


def random_datetime(start: datetime, days_span: int) -> datetime:
    if days_span <= 0:
        return start
    day_offset = random.randint(0, days_span)  # noqa: S311
    second_offset = random.randint(0, 24 * 60 * 60 - 1)  # noqa: S311
    return start + timedelta(days=day_offset, seconds=second_offset)


def make_currency_amount(low: float, high: float) -> Decimal:
    return Decimal(f"{random.uniform(low, high):.4f}")  # noqa: S311


def add_conversation_variables(
    session: Session,
    config: GenerationConfig,
    conversation_id: str,
    created_at: datetime,
) -> None:
    for idx in range(config.variables_per_conversation):
        variable = ConversationVariable(
            id=str(uuid4()),
            app_id=config.app_id,
            conversation_id=conversation_id,
            data=json.dumps(
                {
                    "id": f"var-{idx}",
                    "name": f"variable_{idx}",
                    "value": f"mock-value-{idx}",
                    "updated_at": created_at.isoformat(),
                }
            ),
        )
        session.add(variable)


def create_workflow_nodes(
    session: Session,
    config: GenerationConfig,
    workflow_run_id: str,
    created_by: str,
    base_time: datetime,
) -> int:
    added = 0
    for idx in range(config.nodes_per_run):
        started_at = base_time + timedelta(seconds=idx * 5)
        node = WorkflowNodeExecutionModel(
            id=str(uuid4()),
            tenant_id=config.tenant_id,
            app_id=config.app_id,
            workflow_id=config.workflow_id,
            triggered_from="workflow-run",
            workflow_run_id=workflow_run_id,
            index=idx + 1,
            predecessor_node_id=None if idx == 0 else f"node-{idx}",
            node_execution_id=f"exec-{uuid4().hex[:8]}",
            node_id=f"node-{idx + 1}",
            node_type="task",
            title=f"Mock Node {idx + 1}",
            inputs=json.dumps({"input": f"value-{idx}"}),
            process_data=json.dumps({"steps": idx + 1}),
            outputs=json.dumps({"output": f"result-{idx}"}),
            status="succeeded",
            error=None,
            elapsed_time=0.25,
            execution_metadata=json.dumps({"total_tokens": 50 + idx, "currency": "USD"}),
            created_at=started_at,
            created_by_role=config.created_by_role,
            created_by=created_by,
            finished_at=started_at + timedelta(seconds=2),
        )
        session.add(node)
        added += 1
    return added


def create_message_bundle(
    session: Session,
    config: GenerationConfig,
    *,
    message_index: int,
    conversation_id: str,
    workflow_run_id: str,
    created_by: str,
    created_at: datetime,
) -> tuple[str, int]:
    message_id = str(uuid4())
    prompt = f"Mock question {message_index + 1}"
    answer = f"Mock answer {message_index + 1}"
    message = Message(
        id=message_id,
        app_id=config.app_id,
        model_provider="mock-provider",
        model_id="mock-model",
        override_model_configs=None,
        conversation_id=conversation_id,
        _inputs={"question": prompt},
        query=prompt,
        message={"role": "assistant", "content": answer},
        message_tokens=200,
        message_unit_price=make_currency_amount(0.0020, 0.0030),
        message_price_unit=Decimal("0.001"),
        answer=answer,
        answer_tokens=320,
        answer_unit_price=make_currency_amount(0.0030, 0.0040),
        answer_price_unit=Decimal("0.001"),
        provider_response_latency=0.42,
        currency="USD",
        status="normal",
        message_metadata=json.dumps({"source": "mock"}),
        invoke_from="mock-script",
        from_source="api",
        from_end_user_id=config.end_user_id,
        from_account_id=config.account_id,
        created_at=created_at,
        updated_at=created_at,
        agent_based=False,
        workflow_run_id=workflow_run_id,
        app_mode="advanced-chat",
        total_price=Decimal("0.001"),
    )
    session.add(message)

    chain_id = str(uuid4())
    chain = MessageChain(
        id=chain_id,
        message_id=message_id,
        type="tool-call",
        input=json.dumps({"input": prompt}),
        output=json.dumps({"output": answer}),
        created_at=created_at,
    )
    session.add(chain)

    thought = MessageAgentThought(
        id=str(uuid4()),
        message_id=message_id,
        message_chain_id=chain_id,
        position=1,
        thought=f"Reasoning for {prompt}",
        tool="mock-tool",
        tool_labels_str=json.dumps({"mock-tool": "Mock Tool"}),
        tool_meta_str=json.dumps({"mock-tool": {"version": "1.0"}}),
        tool_input=json.dumps({"prompt": prompt}),
        observation=f"Observation for {prompt}",
        tool_process_data=json.dumps({"duration": 0.1}),
        message=json.dumps({"role": "assistant", "content": answer}),
        message_token=150,
        message_unit_price=Decimal("0.0020"),
        message_price_unit=Decimal("0.001"),
        answer=answer,
        answer_token=210,
        answer_unit_price=Decimal("0.0030"),
        answer_price_unit=Decimal("0.001"),
        tokens=360,
        total_price=Decimal("0.0015"),
        currency="USD",
        latency=0.25,
        created_by_role=config.created_by_role,
        created_by=created_by,
        created_at=created_at,
    )
    session.add(thought)

    attachment = MessageFile(
        message_id=message_id,
        type=FileType.IMAGE,
        transfer_method=FileTransferMethod.LOCAL_FILE,
        url="https://example.com/mock.png",
        belongs_to="assistant",
        created_by_role=CreatorUserRole(config.created_by_role),
        created_by=created_by,
    )
    session.add(attachment)

    annotation_id = str(uuid4())
    annotation = MessageAnnotation(
        id=annotation_id,
        app_id=config.app_id,
        conversation_id=conversation_id,
        message_id=message_id,
        question=f"Annotation for {prompt}",
        content=f"Reference answer for {prompt}",
        account_id=config.account_id,
    )
    session.add(annotation)

    history = AppAnnotationHitHistory(
        id=str(uuid4()),
        app_id=config.app_id,
        annotation_id=annotation_id,
        source="mock-script",
        question=prompt,
        account_id=config.account_id,
        score=1.0,
        message_id=message_id,
        annotation_question=annotation.question,
        annotation_content=annotation.content,
    )
    session.add(history)

    feedback = MessageFeedback(
        id=str(uuid4()),
        app_id=config.app_id,
        conversation_id=conversation_id,
        message_id=message_id,
        rating=random.choice(["like", "dislike"]),  # noqa: S311
        content=f"Feedback for {prompt}",
        from_source="user",
        from_end_user_id=config.end_user_id,
        from_account_id=config.account_id,
    )
    session.add(feedback)

    return message_id, 1


def generate_workflow_run(
    session: Session,
    config: GenerationConfig,
    *,
    run_index: int,
    stats: GenerationStats,
) -> None:
    created_by = config.account_id
    run_started_at = random_datetime(config.start_date, config.days_span)
    run_finished_at = run_started_at + timedelta(minutes=run_index + 1)
    workflow_run_id = str(uuid4())
    conversation_id = str(uuid4())

    workflow_run = WorkflowRun(
        id=workflow_run_id,
        tenant_id=config.tenant_id,
        app_id=config.app_id,
        workflow_id=config.workflow_id,
        type="advanced-chat",
        triggered_from=WorkflowRunTriggeredFrom.APP_RUN.value,
        version="1.0.0",
        graph=json.dumps({"nodes": ["start", "answer"]}),
        inputs=json.dumps({"question": f"Question {run_index}"}),
        status="succeeded",
        outputs=json.dumps({"answer": f"Answer {run_index}"}),
        error=None,
        elapsed_time=1.5,
        total_tokens=500,
        total_steps=config.nodes_per_run,
        created_by_role=config.created_by_role,
        created_by=created_by,
        created_at=run_started_at,
        finished_at=run_finished_at,
    )
    session.add(workflow_run)

    workflow_log = WorkflowAppLog(
        id=str(uuid4()),
        tenant_id=config.tenant_id,
        app_id=config.app_id,
        workflow_id=config.workflow_id,
        workflow_run_id=workflow_run_id,
        created_from="service-api",
        created_by_role=config.created_by_role,
        created_by=created_by,
        created_at=run_started_at,
    )
    session.add(workflow_log)

    conversation = Conversation(
        id=conversation_id,
        app_id=config.app_id,
        mode="advanced-chat",
        name=f"Conversation {run_index + 1}",
        _inputs={},
        introduction="",
        system_instruction="",
        system_instruction_tokens=0,
        status="normal",
        invoke_from="mock-script",
        from_source="api",
        from_end_user_id=config.end_user_id,
        from_account_id=config.account_id,
        created_at=run_started_at,
        updated_at=run_started_at,
    )
    session.add(conversation)

    add_conversation_variables(session, config, conversation_id, run_started_at)

    stats.node_executions += create_workflow_nodes(
        session,
        config,
        workflow_run_id,
        created_by,
        run_started_at,
    )

    for message_idx in range(config.messages_per_run):
        _, annotation_count = create_message_bundle(
            session,
            config,
            message_index=message_idx,
            conversation_id=conversation_id,
            workflow_run_id=workflow_run_id,
            created_by=created_by,
            created_at=run_started_at + timedelta(seconds=message_idx * 10),
        )
        stats.messages += 1
        stats.annotations += annotation_count

    stats.workflow_runs += 1


def seed_mock_data(config: GenerationConfig) -> GenerationStats:
    random.seed()
    session_factory = make_session_factory(config.database_url)
    stats = GenerationStats()

    for run_index in range(config.workflow_runs):
        with session_factory() as session:
            with session.begin():
                generate_workflow_run(session, config, run_index=run_index, stats=stats)

    return stats


@click.command()
@click.option("--database-url", envvar="MOCK_DB_URL", help="Target database URL")
@click.option("--workflow-runs", type=int, default=5, show_default=True, help="Number of workflow runs to create")
@click.option("--messages-per-run", type=int, default=2, show_default=True, help="Messages per workflow run")
@click.option("--nodes-per-run", type=int, default=3, show_default=True, help="Workflow nodes per run")
@click.option(
    "--variables-per-conversation",
    type=int,
    default=2,
    show_default=True,
    help="Conversation variables per conversation",
)
@click.option("--days-span", type=int, default=7, show_default=True, help="Spread created_at timestamps across N days")
@click.option(
    "--start-date",
    type=click.DateTime(formats=[DEFAULT_DATE_FMT]),
    help=f"Start date (UTC) for timestamp generation, format {DEFAULT_DATE_FMT}",
)
@click.option("--tenant-id", type=str, help="Tenant/Workspace ID to reuse")
@click.option("--app-id", type=str, help="Application ID to reuse")
@click.option("--workflow-id", type=str, help="Workflow ID to reuse")
@click.option("--account-id", type=str, help="Account ID recorded as creator")
@click.option("--end-user-id", type=str, help="End user ID referenced by messages")
def main(
    database_url: str | None,
    workflow_runs: int,
    messages_per_run: int,
    nodes_per_run: int,
    variables_per_conversation: int,
    days_span: int,
    start_date: datetime | None,
    tenant_id: str | None,
    app_id: str | None,
    workflow_id: str | None,
    account_id: str | None,
    end_user_id: str | None,
) -> None:
    """Generate mock workflow run data for manual recovery/cleanup testing."""

    resolved_db_url = database_url or dify_config.SQLALCHEMY_DATABASE_URI
    resolved_start = start_date or (datetime.utcnow() - timedelta(days=max(days_span, 1)))

    config = GenerationConfig(
        database_url=resolved_db_url,
        workflow_runs=workflow_runs,
        messages_per_run=messages_per_run,
        nodes_per_run=nodes_per_run,
        variables_per_conversation=variables_per_conversation,
        days_span=days_span,
        start_date=resolved_start,
        tenant_id=tenant_id or str(uuid4()),
        app_id=app_id or str(uuid4()),
        workflow_id=workflow_id or str(uuid4()),
        account_id=account_id or str(uuid4()),
        end_user_id=end_user_id or str(uuid4()),
    )

    stats = seed_mock_data(config)

    click.echo(
        click.style(
            f"Seeded {stats.workflow_runs} workflow runs, {stats.messages} messages, "
            f"{stats.annotations} annotations, and {stats.node_executions} node executions.",
            fg="green",
        )
    )


if __name__ == "__main__":
    main()
