import logging

import click
from sqlalchemy.orm import Session

from extensions.ext_database import db
from services.human_input_observability import build_human_input_log_context
from services.contact_bootstrap_service import seed_member_contacts

logger = logging.getLogger(__name__)


@click.command("seed-workspace-contacts", help="Create missing member Contacts for a workspace.")
@click.option("--tenant-id", required=True, help="Workspace tenant ID.")
@click.option(
    "--account-id",
    "account_ids",
    multiple=True,
    help="Optional account IDs to seed. Repeat the option to seed multiple specific members.",
)
def seed_workspace_contacts(tenant_id: str, account_ids: tuple[str, ...]):
    """Backfill missing authoritative member Contacts for the given workspace."""

    logger.info(
        "Running workspace Contact seed command",
        extra=build_human_input_log_context(
            tenant_id=tenant_id,
            extra={"requested_account_count": len(account_ids)},
        ),
    )
    with Session(db.engine, expire_on_commit=False) as session:
        contacts = seed_member_contacts(
            session=session,
            tenant_id=tenant_id,
            account_ids=list(account_ids) if account_ids else None,
        )
        session.commit()

    logger.info(
        "Completed workspace Contact seed command",
        extra=build_human_input_log_context(
            tenant_id=tenant_id,
            extra={"resolved_contact_count": len(contacts)},
        ),
    )
    click.echo(
        click.style(
            f"Seeded workspace contacts.\nTenant: {tenant_id}\nResolved member contacts: {len(contacts)}",
            fg="green",
        )
    )
