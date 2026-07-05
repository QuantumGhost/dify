from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from libs.datetime_utils import naive_utc_now
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
from services.errors.im_binding import IMBindingValidationError
from services.human_input_im.app_config_service import (
    IMAppConfigStatus,
    IMAppContext,
    IMEventMode,
    IMTokenStatus,
)
from services.human_input_im.binding_service import (
    complete_binding_session,
    create_binding_session,
    get_active_binding,
    revoke_active_binding,
)


def test_create_binding_session_requires_configured_context() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMBinding.__table__])

    context = IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=IMAppConfigStatus.INVALID,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        event_mode=IMEventMode.WEBHOOK,
        errors=["phase-1 demo requires LARK_EVENT_MODE=long_connection"],
    )

    with Session(engine) as session:
        try:
            create_binding_session(session=session, account_id="account-1", app_context=context)
        except IMBindingValidationError:
            return
    raise AssertionError("expected configured-context validation failure")


def test_create_binding_session_rejects_existing_active_binding() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(
        engine,
        tables=[IMBinding.__table__, __import__("models.im_integration", fromlist=["IMBindingSession"]).IMBindingSession.__table__],
    )

    context = IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=IMAppConfigStatus.CONFIGURED,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        event_mode=IMEventMode.LONG_CONNECTION,
        app_id="cli_a",
        app_secret_configured=True,
        errors=[],
    )

    with Session(engine) as session:
        session.add(
            IMBinding(
                account_id="account-1",
                provider=IMProvider.FEISHU,
                install_mode=IMInstallMode.SELF_BUILT,
                scope_type=IMScopeType.DEPLOYMENT,
                scope_id="deployment",
                provider_workspace_id="ws-1",
                provider_user_id="user-1",
                provider_union_id=None,
                status=IMBindingStatus.ACTIVE,
            )
        )
        session.commit()
        try:
            create_binding_session(session=session, account_id="account-1", app_context=context)
        except IMBindingValidationError:
            return
    raise AssertionError("expected existing active binding to block session creation")


def test_revoke_active_binding_marks_row_revoked() -> None:
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
            provider_union_id=None,
            provider_user_display_name="User 1",
            provider_user_avatar_url=None,
            status=IMBindingStatus.ACTIVE,
        )
        session.add(binding)
        session.commit()

        revoked_binding = revoke_active_binding(session=session, account_id="account-1")
        session.commit()

    assert revoked_binding is not None
    assert revoked_binding.status == IMBindingStatus.REVOKED


def test_revoke_active_binding_hides_binding_from_active_lookup() -> None:
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
            provider_union_id=None,
            status=IMBindingStatus.ACTIVE,
        )
        session.add(binding)
        session.commit()

        revoke_active_binding(session=session, account_id="account-1")
        active_binding = get_active_binding(session=session, account_id="account-1")
        session.commit()

        persisted_binding = session.get(IMBinding, binding.id)

    assert active_binding is None
    assert persisted_binding is not None
    assert persisted_binding.status == IMBindingStatus.REVOKED
    assert persisted_binding.active_account_id is None


def test_create_binding_session_returns_pending_record() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMBinding.__table__, __import__("models.im_integration", fromlist=["IMBindingSession"]).IMBindingSession.__table__])

    context = IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=IMAppConfigStatus.CONFIGURED,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        event_mode=IMEventMode.LONG_CONNECTION,
        app_id="cli_a",
        app_secret_configured=True,
        errors=[],
    )

    with Session(engine) as session:
        binding_session = create_binding_session(
            session=session,
            account_id="account-1",
            app_context=context,
            expires_in=timedelta(minutes=5),
        )
        session.commit()

    assert binding_session.account_id == "account-1"
    assert binding_session.provider == IMProvider.FEISHU
    assert binding_session.expires_at > naive_utc_now()


def test_complete_binding_session_creates_active_binding_and_consumes_session() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    im_binding_session_table = __import__("models.im_integration", fromlist=["IMBindingSession"]).IMBindingSession.__table__
    TypeBase.metadata.create_all(engine, tables=[IMBinding.__table__, im_binding_session_table])

    context = IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=IMAppConfigStatus.CONFIGURED,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        event_mode=IMEventMode.LONG_CONNECTION,
        app_id="cli_a",
        app_secret_configured=True,
        errors=[],
    )

    with Session(engine) as session:
        binding_session = create_binding_session(
            session=session,
            account_id="account-1",
            app_context=context,
            expires_in=timedelta(minutes=5),
        )
        binding = complete_binding_session(
            session=session,
            token=binding_session.token,
            provider_workspace_id="ws-1",
            provider_user_id="user-1",
            provider_union_id="union-1",
            provider_user_display_name="User 1",
            provider_user_avatar_url=None,
        )
        session.commit()

    assert binding.account_id == "account-1"
    assert binding.status == IMBindingStatus.ACTIVE
    assert binding.provider_user_display_name == "User 1"


def test_complete_binding_session_reuses_revoked_binding_identity() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    im_binding_session_table = __import__("models.im_integration", fromlist=["IMBindingSession"]).IMBindingSession.__table__
    TypeBase.metadata.create_all(engine, tables=[IMBinding.__table__, im_binding_session_table])

    context = IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=IMAppConfigStatus.CONFIGURED,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        event_mode=IMEventMode.LONG_CONNECTION,
        app_id="cli_a",
        app_secret_configured=True,
        errors=[],
    )

    with Session(engine) as session:
        revoked_binding = IMBinding(
            account_id="account-1",
            provider=IMProvider.FEISHU,
            install_mode=IMInstallMode.SELF_BUILT,
            scope_type=IMScopeType.DEPLOYMENT,
            scope_id="deployment",
            provider_workspace_id="ws-1",
            provider_user_id="user-1",
            active_account_id=None,
            provider_union_id=None,
            provider_user_display_name="Old User",
            provider_user_avatar_url=None,
            status=IMBindingStatus.REVOKED,
        )
        session.add(revoked_binding)
        session.commit()
        revoked_binding_id = revoked_binding.id

        binding_session = create_binding_session(
            session=session,
            account_id="account-1",
            app_context=context,
            expires_in=timedelta(minutes=5),
        )
        binding = complete_binding_session(
            session=session,
            token=binding_session.token,
            provider_workspace_id="ws-1",
            provider_user_id="user-1",
            provider_union_id="union-1",
            provider_user_display_name="New User",
            provider_user_avatar_url=None,
        )
        session.commit()

    assert binding.id == revoked_binding_id
    assert binding.status == IMBindingStatus.ACTIVE
    assert binding.provider_user_display_name == "New User"

    with Session(engine) as session:
        assert session.query(IMBinding).count() == 1


def test_complete_binding_session_marks_expired_session() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMBinding.__table__, IMBindingSession.__table__])
    context = IMAppContext(
        provider=IMProvider.FEISHU,
        install_mode=IMInstallMode.SELF_BUILT,
        scope_type=IMScopeType.DEPLOYMENT,
        scope_id="deployment",
        status=IMAppConfigStatus.CONFIGURED,
        token_status=IMTokenStatus.NOT_APPLICABLE,
        event_mode=IMEventMode.LONG_CONNECTION,
        app_id="cli_a",
        app_secret_configured=True,
        errors=[],
    )

    with Session(engine) as session:
        binding_session = create_binding_session(
            session=session,
            account_id="account-1",
            app_context=context,
            expires_in=timedelta(seconds=-1),
        )

        try:
            complete_binding_session(
                session=session,
                token=binding_session.token,
                provider_workspace_id="ws-1",
                provider_user_id="user-1",
            )
        except IMBindingValidationError as exc:
            assert str(exc) == "binding session expired"
        else:
            raise AssertionError("expected expired binding session validation failure")

        session.commit()
        persisted_session = session.get(IMBindingSession, binding_session.id)

    assert persisted_session is not None
    assert persisted_session.status == IMBindingSessionStatus.EXPIRED
