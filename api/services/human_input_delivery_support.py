"""Task-neutral helpers shared by Human Input delivery paths.

These helpers support both the legacy email task and the new contact-v2
delivery task without making either task module serve as a library.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session, sessionmaker

from configs import dify_config
from core.app.layers.pause_state_persist_layer import WorkflowResumptionContext
from core.workflow.human_input_adapter import EmailDeliveryConfig
from extensions.ext_database import db
from graphon.runtime import GraphRuntimeState, VariablePool
from repositories.factory import DifyAPIRepositoryFactory

logger = logging.getLogger(__name__)


def build_human_input_form_link(token: str) -> str:
    base_url = dify_config.APP_WEB_URL
    return f"{base_url.rstrip('/')}/form/{token}"


def render_human_input_email_body(
    body_template: str,
    form_link: str,
    *,
    variable_pool: VariablePool | None,
) -> str:
    body = EmailDeliveryConfig.render_body_template(
        body=body_template,
        url=form_link,
        variable_pool=variable_pool,
    )
    return EmailDeliveryConfig.render_markdown_body(body)


def load_human_input_variable_pool(workflow_run_id: str | None) -> VariablePool | None:
    if not workflow_run_id:
        return None

    repository_session_factory = sessionmaker(bind=db.engine, expire_on_commit=False)
    workflow_run_repo = DifyAPIRepositoryFactory.create_api_workflow_run_repository(repository_session_factory)
    pause_entity = workflow_run_repo.get_workflow_pause(workflow_run_id)
    if pause_entity is None:
        logger.info("No pause state found for workflow run %s", workflow_run_id)
        return None

    try:
        resumption_context = WorkflowResumptionContext.loads(pause_entity.get_state().decode())
    except Exception:
        logger.exception("Failed to load resumption context for workflow run %s", workflow_run_id)
        return None

    graph_runtime_state = GraphRuntimeState.from_snapshot(resumption_context.serialized_graph_runtime_state)
    return graph_runtime_state.variable_pool


def open_human_input_delivery_session(session_factory: sessionmaker | Session | None):
    if session_factory is None:
        return Session(db.engine)
    if isinstance(session_factory, Session):
        return session_factory
    return session_factory()
