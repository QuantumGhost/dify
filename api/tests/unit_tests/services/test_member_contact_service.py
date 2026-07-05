from unittest.mock import MagicMock

from services.member_contact_service import MemberContactService


def test_list_workspace_member_bindings_returns_imported_member():
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        ("acc-1", "Demo User", "demo@example.com", "contact-1", "ou_123"),
    ]

    bindings = MemberContactService().list_workspace_member_bindings(session, tenant_id="tenant-1")

    assert len(bindings) == 1
    assert bindings[0].account_id == "acc-1"
    assert bindings[0].contact_id == "contact-1"
    assert bindings[0].feishu_open_id == "ou_123"
    assert bindings[0].is_feishu_bound is True


def test_list_workspace_member_bindings_returns_unimported_member():
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        ("acc-1", "Demo User", "demo@example.com", None, None),
    ]

    bindings = MemberContactService().list_workspace_member_bindings(
        session,
        tenant_id="tenant-1",
        account_ids=["acc-1"],
    )

    assert len(bindings) == 1
    assert bindings[0].contact_id is None
    assert bindings[0].feishu_open_id is None
    assert bindings[0].is_feishu_bound is False


def test_resolve_workspace_member_binding_returns_none_for_account_mismatch():
    session = MagicMock()
    session.execute.return_value.all.return_value = []

    binding = MemberContactService().resolve_workspace_member_binding(
        session,
        tenant_id="tenant-1",
        account_id="acc-missing",
    )

    assert binding is None
