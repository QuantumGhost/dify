import click
import lark_oapi as lark  # type: ignore[import-untyped]
from sqlalchemy.orm import sessionmaker

from configs import dify_config
from core.db.session_factory import session_factory
from extensions.ext_database import db
from services.human_input_feishu_service import HumanInputFeishuService
from services.member_contact_service import MemberContactService


@click.command("import-member-contacts", help="Import current workspace members as demo-scope member contacts.")
@click.option("--tenant-id", required=True, help="Workspace tenant ID to import member contacts from.")
def import_member_contacts(tenant_id: str) -> None:
    with session_factory.create_session() as session:
        result = MemberContactService().import_workspace_members(session, tenant_id)

    click.echo(click.style(f"Imported member contacts for tenant {tenant_id}", fg="green"))
    click.echo(f"Created: {result.created_count}")
    click.echo(f"Updated: {result.updated_count}")


@click.command("run-feishu-hitl-listener", help="Run the Feishu long-connection listener for HITL card callbacks.")
def run_feishu_hitl_listener() -> None:
    if not dify_config.FEISHU_APP_ID or not dify_config.FEISHU_APP_SECRET:
        raise click.ClickException("FEISHU_APP_ID and FEISHU_APP_SECRET are required.")

    feishu_service = HumanInputFeishuService(
        session_factory=sessionmaker(bind=db.engine, expire_on_commit=False),
    )
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(feishu_service.handle_card_action)
        .build()
    )
    client = lark.ws.Client(
        dify_config.FEISHU_APP_ID,
        dify_config.FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    client.start()
