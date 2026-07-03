from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from services.account_im_binding_service import AccountIMBindingService
from services.errors.account import AccountIMBindingConflictError


class _FakeScalarResult:
    def __init__(self, obj):
        self._obj = obj

    def first(self):
        if isinstance(self._obj, list):
            return self._obj[0] if self._obj else None
        return self._obj

    def all(self):
        if self._obj is None:
            return []
        if isinstance(self._obj, list):
            return list(self._obj)
        return [self._obj]


class _FakeSession:
    def __init__(self, *, scalar_result=None, scalars_result=None):
        self._scalar_result = scalar_result
        self._scalars_result = scalars_result
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0
        self.commit_side_effect = None

    def scalar(self, _stmt):
        return self._scalar_result

    def scalars(self, _stmt):
        return _FakeScalarResult(self._scalars_result)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        if self.commit_side_effect is not None:
            raise self.commit_side_effect
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


def test_upsert_binding_creates_new_binding():
    session = _FakeSession(scalar_result=None)

    binding = AccountIMBindingService.upsert_binding(
        session=session,
        tenant_id="tenant-1",
        account_id="account-1",
        provider="feishu",
        open_id="open-1",
        user_id="user-1",
    )

    assert binding.tenant_id == "tenant-1"
    assert binding.account_id == "account-1"
    assert binding.provider == "feishu"
    assert binding.open_id == "open-1"
    assert binding.user_id == "user-1"
    assert session.added == [binding]
    assert session.commit_count == 1


def test_upsert_binding_updates_existing_binding():
    existing = SimpleNamespace(
        tenant_id="tenant-1",
        account_id="account-1",
        provider="feishu",
        open_id="old-open",
        user_id="old-user",
    )
    session = _FakeSession(scalar_result=existing)

    binding = AccountIMBindingService.upsert_binding(
        session=session,
        tenant_id="tenant-1",
        account_id="account-1",
        provider="feishu",
        open_id="open-1",
        user_id="user-1",
    )

    assert binding is existing
    assert existing.open_id == "open-1"
    assert existing.user_id == "user-1"
    assert session.added == []
    assert session.commit_count == 1


def test_list_bindings_by_account_ids_returns_snapshots():
    session = _FakeSession(
        scalars_result=[
            SimpleNamespace(
                id="binding-1",
                tenant_id="tenant-1",
                account_id="account-1",
                provider="feishu",
                open_id="open-1",
                user_id="user-1",
            ),
            SimpleNamespace(
                id="binding-2",
                tenant_id="tenant-1",
                account_id="account-2",
                provider="feishu",
                open_id="open-2",
                user_id="user-2",
            ),
        ]
    )

    snapshots = AccountIMBindingService.list_bindings_by_account_ids(
        session=session,
        tenant_id="tenant-1",
        account_ids=["account-1", "account-2"],
        provider="feishu",
    )

    assert [snapshot.account_id for snapshot in snapshots] == ["account-1", "account-2"]
    assert snapshots[0].open_id == "open-1"
    assert snapshots[1].user_id == "user-2"


def test_list_bindings_by_account_ids_short_circuits_empty_input():
    session = _FakeSession(scalars_result=["unexpected"])

    snapshots = AccountIMBindingService.list_bindings_by_account_ids(
        session=session,
        tenant_id="tenant-1",
        account_ids=[],
        provider="feishu",
    )

    assert snapshots == []


def test_upsert_binding_translates_integrity_error_to_domain_conflict():
    session = _FakeSession(scalar_result=None)
    session.commit_side_effect = IntegrityError("stmt", "params", Exception("duplicate"))

    with pytest.raises(AccountIMBindingConflictError, match="already bound"):
        AccountIMBindingService.upsert_binding(
            session=session,
            tenant_id="tenant-1",
            account_id="account-1",
            provider="feishu",
            open_id="open-1",
            user_id="user-1",
        )

    assert session.rollback_count == 1
