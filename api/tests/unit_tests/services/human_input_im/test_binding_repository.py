import sqlalchemy as sa
from sqlalchemy.orm import Session

from models.base import TypeBase
from models.im_integration import (
    IMBinding,
    IMBindingSession,
    IMBindingSessionStatus,
    IMBindingStatus,
    IMInstallMode,
    IMProvider,
    IMScopeType,
)
from services.human_input_im.binding_repository import (
    get_binding_by_provider_identity,
    get_pending_binding_session,
)


def test_repository_finds_binding_by_provider_identity_scope_for_rebind_lookup() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMBinding.__table__])

    with Session(engine) as session:
        binding = IMBinding(
            account_id="account-1",
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            provider_workspace_id="ws-1",
            provider_user_id="user-1",
            provider_union_id="union-1",
            status=IMBindingStatus.REVOKED,
        )
        session.add(binding)
        session.commit()

        found_binding = get_binding_by_provider_identity(
            session=session,
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            provider_workspace_id="ws-1",
            provider_user_id="user-1",
        )

    assert found_binding is not None
    assert found_binding.id == binding.id
    assert found_binding.status == IMBindingStatus.REVOKED


def test_repository_only_returns_pending_binding_sessions() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMBindingSession.__table__])

    with Session(engine) as session:
        binding_session = IMBindingSession(
            account_id="account-1",
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            token="imbs_consumed",
            expires_at=sa.func.now(),
            status=IMBindingSessionStatus.CONSUMED,
        )
        session.add(binding_session)
        session.commit()

        found_binding_session = get_pending_binding_session(session=session, token="imbs_consumed")

    assert found_binding_session is None
