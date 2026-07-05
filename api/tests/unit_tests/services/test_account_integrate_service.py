from types import SimpleNamespace
from unittest.mock import MagicMock

from models.account import AccountIntegrate
from services.account_service import AccountService


def _make_account(account_id: str = "acc-1") -> SimpleNamespace:
    return SimpleNamespace(id=account_id)


def test_link_account_integrate_creates_new_binding():
    session = MagicMock()
    session.scalar.return_value = None
    account = _make_account()

    AccountService.link_account_integrate("feishu_im", "ou_123", account, session=session)

    session.add.assert_called_once()
    added = session.add.call_args.args[0]
    assert isinstance(added, AccountIntegrate)
    assert added.account_id == "acc-1"
    assert added.provider == "feishu_im"
    assert added.open_id == "ou_123"
    session.commit.assert_called_once()


def test_link_account_integrate_updates_existing_binding():
    session = MagicMock()
    existing = AccountIntegrate(account_id="acc-1", provider="feishu_im", open_id="ou_old", encrypted_token="")
    session.scalar.return_value = existing
    account = _make_account()

    AccountService.link_account_integrate("feishu_im", "ou_new", account, session=session)

    assert existing.open_id == "ou_new"
    session.add.assert_not_called()
    session.commit.assert_called_once()
