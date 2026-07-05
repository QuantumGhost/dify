import click
from sqlalchemy.orm import Session

from extensions.ext_database import db
from services.contact_bootstrap_service import seed_member_contacts


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

    with Session(db.engine, expire_on_commit=False) as session:
        contacts = seed_member_contacts(
            session=session,
            tenant_id=tenant_id,
            account_ids=list(account_ids) if account_ids else None,
        )
        session.commit()

    click.echo(
        click.style(
            f"Seeded workspace contacts.\nTenant: {tenant_id}\nResolved member contacts: {len(contacts)}",
            fg="green",
        )
    )
