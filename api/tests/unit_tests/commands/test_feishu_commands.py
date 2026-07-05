from types import SimpleNamespace
from unittest.mock import MagicMock

from click.testing import CliRunner

from services.member_contact_service import MemberContactImportResult


class FakeSessionContext:
    session: object
    entered: bool
    exited: bool

    def __init__(self, session: object) -> None:
        self.session = session
        self.entered = False
        self.exited = False

    def __enter__(self) -> object:
        self.entered = True
        return self.session

    def __exit__(self, *_args: object) -> None:
        self.exited = True


def test_import_member_contacts_command(monkeypatch):
    from commands import feishu as feishu_module
    from commands.feishu import import_member_contacts

    session = object()
    session_context = FakeSessionContext(session)
    captured: dict[str, object] = {}

    class FakeMemberContactService:
        def import_workspace_members(self, import_session, tenant_id: str) -> MemberContactImportResult:
            captured["session"] = import_session
            captured["tenant_id"] = tenant_id
            return MemberContactImportResult(created_count=2, updated_count=1)

    monkeypatch.setattr(feishu_module.session_factory, "create_session", lambda: session_context)
    monkeypatch.setattr(feishu_module, "MemberContactService", FakeMemberContactService)

    result = CliRunner().invoke(import_member_contacts, ["--tenant-id", "tenant-1"])

    assert result.exit_code == 0
    assert captured["session"] is session
    assert captured["tenant_id"] == "tenant-1"
    assert "Created: 2" in result.output
    assert "Updated: 1" in result.output
    assert session_context.entered
    assert session_context.exited


def test_run_feishu_hitl_listener_command(monkeypatch):
    from commands import feishu as feishu_module
    from commands.feishu import run_feishu_hitl_listener

    handler_builder = MagicMock()
    handler_builder.register_p2_card_action_trigger.return_value = handler_builder
    handler_builder.build.return_value = "handler"
    dispatcher_handler = MagicMock()
    dispatcher_handler.builder.return_value = handler_builder
    ws_client = MagicMock()
    ws_client_cls = MagicMock(return_value=ws_client)
    feishu_service = MagicMock()

    monkeypatch.setattr(feishu_module.dify_config, "FEISHU_APP_ID", "cli_test")
    monkeypatch.setattr(feishu_module.dify_config, "FEISHU_APP_SECRET", "secret")
    monkeypatch.setattr(feishu_module, "db", SimpleNamespace(engine=object()))
    monkeypatch.setattr(feishu_module.lark, "EventDispatcherHandler", dispatcher_handler)
    monkeypatch.setattr(feishu_module.lark.ws, "Client", ws_client_cls)
    monkeypatch.setattr(feishu_module, "HumanInputFeishuService", MagicMock(return_value=feishu_service))

    result = CliRunner().invoke(run_feishu_hitl_listener, [])

    assert result.exit_code == 0
    dispatcher_handler.builder.assert_called_once_with("", "")
    handler_builder.register_p2_card_action_trigger.assert_called_once_with(feishu_service.handle_card_action)
    ws_client_cls.assert_called_once()
    ws_client.start.assert_called_once()
