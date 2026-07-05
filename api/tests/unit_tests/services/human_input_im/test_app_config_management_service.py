from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from libs.datetime_utils import naive_utc_now
from models.base import TypeBase
from models.im_integration import (
    IMAppInstallation,
    IMInstallMode,
    IMInstallStatus,
    IMProvider,
    IMSelfBuiltTenantConfig,
)
from services.entities.im_app_entities import UpsertIMAppInstallation, UpsertIMSelfBuiltTenantConfig
from services.errors.im_app_config import IMAppConfigValidationError
from services.human_input_im.app_config_management_service import (
    delete_tenant_self_built_config,
    get_app_installation,
    get_tenant_self_built_config,
    uninstall_app_installation,
    upsert_app_installation,
    upsert_tenant_self_built_config,
)
from services.human_input_im.app_config_service import IMTokenStatus


def test_upsert_tenant_self_built_config_rejects_blank_payload() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMSelfBuiltTenantConfig.__table__])

    with Session(engine) as session:
        try:
            upsert_tenant_self_built_config(
                session=session,
                tenant_id="tenant-1",
                provider=IMProvider.FEISHU,
                request=UpsertIMSelfBuiltTenantConfig(),
            )
        except IMAppConfigValidationError:
            return

    raise AssertionError("expected blank self-built config payload to be rejected")


def test_upsert_tenant_self_built_config_encrypts_and_redacts(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMSelfBuiltTenantConfig.__table__])
    monkeypatch.setattr(
        "services.human_input_im.app_config_management_service.encrypter.encrypt_token",
        lambda tenant_id, value: f"enc:{tenant_id}:{value}",
    )

    with Session(engine) as session:
        record = upsert_tenant_self_built_config(
            session=session,
            tenant_id="tenant-1",
            provider=IMProvider.FEISHU,
            request=UpsertIMSelfBuiltTenantConfig(
                provider_workspace_id="ws-1",
                app_id="cli_a",
                app_secret="secret",
                verification_token="token",
                encrypt_key="encrypt",
                event_mode="long_connection",
            ),
        )
        session.commit()
        persisted = session.query(IMSelfBuiltTenantConfig).one()

    assert record.provider == IMProvider.FEISHU
    assert record.scope_id == "tenant-1"
    assert record.provider_workspace_id == "ws-1"
    assert record.app_id == "cli_a"
    assert record.app_secret_configured is True
    assert record.verification_token_configured is True
    assert record.encrypt_key_configured is True
    assert record.event_mode == "long_connection"
    assert persisted.encrypted_app_secret == "enc:tenant-1:secret"
    assert persisted.encrypted_verification_token == "enc:tenant-1:token"
    assert persisted.encrypted_encrypt_key == "enc:tenant-1:encrypt"


def test_get_tenant_self_built_config_returns_none_when_missing() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMSelfBuiltTenantConfig.__table__])

    with Session(engine) as session:
        record = get_tenant_self_built_config(
            session=session,
            tenant_id="tenant-1",
            provider=IMProvider.FEISHU,
        )

    assert record is None


def test_delete_tenant_self_built_config_returns_false_when_missing() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMSelfBuiltTenantConfig.__table__])

    with Session(engine) as session:
        deleted = delete_tenant_self_built_config(
            session=session,
            tenant_id="tenant-1",
            provider=IMProvider.FEISHU,
        )

    assert deleted is False


def test_get_app_installation_returns_redacted_record() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMAppInstallation.__table__])

    with Session(engine) as session:
        installation = IMAppInstallation(
            tenant_id="tenant-1",
            provider=IMProvider.SLACK,
            install_mode=IMInstallMode.ISV,
            install_status=IMInstallStatus.INSTALLED,
            provider_workspace_id="team-1",
            encrypted_access_token="token",
            encrypted_refresh_token="refresh",
            access_token_expires_at=naive_utc_now() + timedelta(minutes=30),
        )
        session.add(installation)
        session.commit()

        record = get_app_installation(
            session=session,
            tenant_id="tenant-1",
            provider=IMProvider.SLACK,
            install_mode=IMInstallMode.ISV,
        )

    assert record is not None
    assert record.provider == IMProvider.SLACK
    assert record.install_mode == IMInstallMode.ISV
    assert record.install_status == IMInstallStatus.INSTALLED
    assert record.token_status == IMTokenStatus.VALID
    assert record.access_token_configured is True
    assert record.refresh_token_configured is True


def test_upsert_app_installation_rejects_blank_payload() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMAppInstallation.__table__])

    with Session(engine) as session:
        try:
            upsert_app_installation(
                session=session,
                tenant_id="tenant-1",
                provider=IMProvider.SLACK,
                install_mode=IMInstallMode.ISV,
                request=UpsertIMAppInstallation(),
            )
        except IMAppConfigValidationError:
            return

    raise AssertionError("expected blank installation payload to be rejected")


def test_upsert_app_installation_encrypts_tokens(monkeypatch) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMAppInstallation.__table__])
    monkeypatch.setattr(
        "services.human_input_im.app_config_management_service.encrypter.encrypt_token",
        lambda tenant_id, value: f"enc:{tenant_id}:{value}",
    )

    with Session(engine) as session:
        record = upsert_app_installation(
            session=session,
            tenant_id="tenant-1",
            provider=IMProvider.SLACK,
            install_mode=IMInstallMode.ISV,
            request=UpsertIMAppInstallation(
                provider_workspace_id="team-1",
                install_status=IMInstallStatus.INSTALLED,
                access_token="token",
                refresh_token="refresh",
                access_token_expires_at=naive_utc_now() + timedelta(minutes=30),
                token_refreshed_at=naive_utc_now(),
                installed_at=naive_utc_now(),
            ),
        )
        session.commit()
        persisted = session.query(IMAppInstallation).one()

    assert record.provider == IMProvider.SLACK
    assert record.install_mode == IMInstallMode.ISV
    assert record.install_status == IMInstallStatus.INSTALLED
    assert record.access_token_configured is True
    assert record.refresh_token_configured is True
    assert persisted.encrypted_access_token == "enc:tenant-1:token"
    assert persisted.encrypted_refresh_token == "enc:tenant-1:refresh"


def test_uninstall_app_installation_marks_row_uninstalled() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    TypeBase.metadata.create_all(engine, tables=[IMAppInstallation.__table__])

    with Session(engine) as session:
        installation = IMAppInstallation(
            tenant_id="tenant-1",
            provider=IMProvider.SLACK,
            install_mode=IMInstallMode.ISV,
            install_status=IMInstallStatus.INSTALLED,
            encrypted_access_token="token",
            encrypted_refresh_token="refresh",
            access_token_expires_at=naive_utc_now() + timedelta(minutes=30),
        )
        session.add(installation)
        session.commit()

        changed = uninstall_app_installation(
            session=session,
            tenant_id="tenant-1",
            provider=IMProvider.SLACK,
            install_mode=IMInstallMode.ISV,
        )
        session.commit()
        persisted = session.query(IMAppInstallation).one()

    assert changed is True
    assert persisted.install_status == IMInstallStatus.UNINSTALLED
    assert persisted.encrypted_access_token is None
    assert persisted.encrypted_refresh_token is None
    assert persisted.access_token_expires_at is None
    assert persisted.token_refresh_error is None
    assert persisted.uninstalled_at is not None
