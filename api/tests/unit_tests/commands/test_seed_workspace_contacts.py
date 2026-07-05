from click.testing import CliRunner
from types import SimpleNamespace

from commands.contact import seed_workspace_contacts


class FakeSessionContext:
    def __init__(self, session: object) -> None:
        self.session = session
        self.entered = False
        self.exited = False

    def __enter__(self) -> object:
        self.entered = True
        return self.session

    def __exit__(self, *_args: object) -> None:
        self.exited = True


def test_seed_workspace_contacts_calls_service_with_optional_account_ids(monkeypatch) -> None:
    session = SimpleNamespace(commit=lambda: None)
    session_context = FakeSessionContext(session)
    captured: dict[str, object] = {}

    def fake_seed_member_contacts(*, session: object, tenant_id: str, account_ids: list[str] | None):
        captured["session"] = session
        captured["tenant_id"] = tenant_id
        captured["account_ids"] = account_ids
        return ["contact-1", "contact-2"]

    class FakeSessionFactory:
        def __call__(self, *_args, **_kwargs):
            return session_context

    monkeypatch.setattr("commands.contact.seed_member_contacts", fake_seed_member_contacts)
    monkeypatch.setattr("commands.contact.Session", FakeSessionFactory())
    monkeypatch.setattr("commands.contact.db", SimpleNamespace(engine=object()))

    result = CliRunner().invoke(
        seed_workspace_contacts,
        ["--tenant-id", "tenant-1", "--account-id", "account-1", "--account-id", "account-2"],
    )

    assert result.exit_code == 0
    assert captured["session"] is session
    assert captured["tenant_id"] == "tenant-1"
    assert captured["account_ids"] == ["account-1", "account-2"]
    assert session_context.entered is True
    assert session_context.exited is True
    assert "Resolved member contacts: 2" in result.output


def test_seed_workspace_contacts_requires_tenant_id() -> None:
    result = CliRunner().invoke(seed_workspace_contacts, [])

    assert result.exit_code != 0
    assert "--tenant-id" in result.output
