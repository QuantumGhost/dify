"""Celery entrypoint for persisted Human Input IM directory sync runs."""

import logging

from celery import shared_task
from sqlalchemy.orm import sessionmaker

from extensions.ext_database import db
from repositories.human_input_v2.im_integration import SQLAlchemyIMControlPlaneRepository
from services.human_input_v2.im_sync import IMSyncManagementError, IMSyncManagementService

logger = logging.getLogger(__name__)


@shared_task(queue="workflow_storage")
def human_input_im_sync_task(sync_run_id: str) -> None:
    """Claim and execute one run; duplicate deliveries exit without applying."""

    repository = SQLAlchemyIMControlPlaneRepository(
        sessionmaker(bind=db.engine, expire_on_commit=False),
    )
    service = IMSyncManagementService(repository, lambda _sync_run_id: None)
    try:
        service.execute_sync(sync_run_id)
    except IMSyncManagementError:
        logger.warning("Human Input IM directory sync failed, sync_run_id=%s", sync_run_id)
