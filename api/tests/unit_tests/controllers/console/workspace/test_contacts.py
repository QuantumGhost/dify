import importlib
from inspect import unwrap

import pytest
from flask import Flask
from pydantic_core import ValidationError
from werkzeug.exceptions import UnprocessableEntity

module = importlib.import_module("controllers.console.workspace.contacts")
from controllers.console.workspace.contacts import WorkspaceContactsApi
from models.contact import ContactSource, ContactStatus, ContactType
from services.entities.contact_entities import ContactRecord, ResolvedContact


class TestWorkspaceContactsApi:
    def test_get_success(self, app: Flask):
        api = WorkspaceContactsApi()
        method = unwrap(api.get)
        contact = ResolvedContact(
            id="contact-1",
            tenant_id="tenant-1",
            type=ContactType.EXTERNAL,
            status=ContactStatus.ACTIVE,
            source=ContactSource.MANUAL_EXTERNAL,
            account_id=None,
            name="Vendor",
            email="vendor@example.com",
            delivery_status="email",
            delivery_provider=None,
        )

        from unittest.mock import patch

        with (
            app.test_request_context("/?type=external&include_disabled=false"),
            patch(
                "controllers.console.workspace.contacts.list_contact_records",
                return_value=[
                    ContactRecord(
                        id="contact-1",
                        tenant_id="tenant-1",
                        type=ContactType.EXTERNAL,
                        status=ContactStatus.ACTIVE,
                        source=ContactSource.MANUAL_EXTERNAL,
                        account_id=None,
                    )
                ],
            ) as list_contacts_mock,
            patch("controllers.console.workspace.contacts.resolve_contact_records", return_value=[contact]),
        ):
            result, status = method(api, "tenant-1")

        assert status == 200
        assert result["data"][0]["id"] == "contact-1"
        assert result["data"][0]["type"] == "external"
        assert result["data"][0]["delivery_status"] == "email"
        list_contacts_mock.assert_called_once_with(
            session=module.db.session,
            tenant_id="tenant-1",
            contact_type=ContactType.EXTERNAL,
            include_disabled=False,
        )

    def test_get_invalid_query(self, app: Flask):
        api = WorkspaceContactsApi()
        method = unwrap(api.get)

        with app.test_request_context("/?include_disabled=not-bool"):
            with pytest.raises(ValidationError):
                method(api, "tenant-1")

    def test_post_success(self, app: Flask):
        api = WorkspaceContactsApi()
        method = unwrap(api.post)
        payload = {"name": "Vendor", "email": "vendor@example.com"}
        contact = ContactRecord(
            id="contact-1",
            tenant_id="tenant-1",
            type=ContactType.EXTERNAL,
            status=ContactStatus.ACTIVE,
            source=ContactSource.MANUAL_EXTERNAL,
            account_id=None,
        )
        resolved_contact = ResolvedContact(
            id="contact-1",
            tenant_id="tenant-1",
            type=ContactType.EXTERNAL,
            status=ContactStatus.ACTIVE,
            source=ContactSource.MANUAL_EXTERNAL,
            account_id=None,
            name="Vendor",
            email="vendor@example.com",
            delivery_status="email",
            delivery_provider=None,
        )

        from unittest.mock import PropertyMock, patch

        with (
            app.test_request_context("/", json=payload),
            patch.object(
                type(module.console_ns),
                "payload",
                new_callable=PropertyMock,
                return_value=payload,
            ),
            patch("controllers.console.workspace.contacts.create_external_contact", return_value=contact) as create_mock,
            patch("controllers.console.workspace.contacts.resolve_contact_records", return_value=[resolved_contact]),
            patch("controllers.console.workspace.contacts.db.session.commit") as commit_mock,
        ):
            result, status = method(api, "tenant-1")

        assert status == 201
        assert result["id"] == "contact-1"
        create_mock.assert_called_once_with(
            session=module.db.session,
            tenant_id="tenant-1",
            name="Vendor",
            email="vendor@example.com",
        )
        commit_mock.assert_called_once()

    def test_post_normalizes_name_and_email_before_create(self, app: Flask):
        api = WorkspaceContactsApi()
        method = unwrap(api.post)
        payload = {"name": "  Vendor Name  ", "email": "  Vendor@Example.COM  "}
        contact = ContactRecord(
            id="contact-1",
            tenant_id="tenant-1",
            type=ContactType.EXTERNAL,
            status=ContactStatus.ACTIVE,
            source=ContactSource.MANUAL_EXTERNAL,
            account_id=None,
        )
        resolved_contact = ResolvedContact(
            id="contact-1",
            tenant_id="tenant-1",
            type=ContactType.EXTERNAL,
            status=ContactStatus.ACTIVE,
            source=ContactSource.MANUAL_EXTERNAL,
            account_id=None,
            name="Vendor Name",
            email="vendor@example.com",
            delivery_status="email",
            delivery_provider=None,
        )

        from unittest.mock import PropertyMock, patch

        with (
            app.test_request_context("/", json=payload),
            patch.object(
                type(module.console_ns),
                "payload",
                new_callable=PropertyMock,
                return_value=payload,
            ),
            patch("controllers.console.workspace.contacts.create_external_contact", return_value=contact) as create_mock,
            patch("controllers.console.workspace.contacts.resolve_contact_records", return_value=[resolved_contact]),
            patch("controllers.console.workspace.contacts.db.session.commit"),
        ):
            method(api, "tenant-1")

        create_mock.assert_called_once_with(
            session=module.db.session,
            tenant_id="tenant-1",
            name="Vendor Name",
            email="vendor@example.com",
        )

    def test_post_invalid_email_raises_validation_error(self, app: Flask):
        api = WorkspaceContactsApi()
        method = unwrap(api.post)
        payload = {"name": "Vendor", "email": "not-an-email"}

        from unittest.mock import PropertyMock, patch

        with (
            app.test_request_context("/", json=payload),
            patch.object(
                type(module.console_ns),
                "payload",
                new_callable=PropertyMock,
                return_value=payload,
            ),
            patch("controllers.console.workspace.contacts.db.session.commit") as commit_mock,
        ):
            with pytest.raises(ValidationError):
                method(api, "tenant-1")

        commit_mock.assert_not_called()

    def test_post_blank_name_raises_validation_error(self, app: Flask):
        api = WorkspaceContactsApi()
        method = unwrap(api.post)
        payload = {"name": "   ", "email": "vendor@example.com"}

        from unittest.mock import PropertyMock, patch

        with (
            app.test_request_context("/", json=payload),
            patch.object(
                type(module.console_ns),
                "payload",
                new_callable=PropertyMock,
                return_value=payload,
            ),
            patch("controllers.console.workspace.contacts.db.session.commit") as commit_mock,
        ):
            with pytest.raises(ValidationError):
                method(api, "tenant-1")

        commit_mock.assert_not_called()

    def test_post_service_invariant_failure_returns_422(self, app: Flask):
        api = WorkspaceContactsApi()
        method = unwrap(api.post)
        payload = {"name": "Vendor", "email": "vendor@example.com"}

        from unittest.mock import PropertyMock, patch

        with (
            app.test_request_context("/", json=payload),
            patch.object(
                type(module.console_ns),
                "payload",
                new_callable=PropertyMock,
                return_value=payload,
            ),
            patch(
                "controllers.console.workspace.contacts.create_external_contact",
                side_effect=module.ContactValidationError("bad contact"),
            ),
            patch("controllers.console.workspace.contacts.db.session.commit") as commit_mock,
        ):
            with pytest.raises(UnprocessableEntity):
                method(api, "tenant-1")

        commit_mock.assert_not_called()
