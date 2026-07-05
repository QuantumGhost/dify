from flask import request
from flask_restx import Resource
from pydantic import BaseModel, Field, field_validator

from controllers.common.fields import SimpleResultResponse
from controllers.common.schema import (
    query_params_from_model,
    query_params_from_request,
    register_response_schema_models,
    register_schema_models,
)
from controllers.console import console_ns
from controllers.console.wraps import (
    account_initialization_required,
    edit_permission_required,
    setup_required,
    with_current_tenant_id,
)
from extensions.ext_database import db
from libs.helper import EmailStr, dump_response
from libs.login import login_required
from werkzeug.exceptions import UnprocessableEntity
from models.contact import ContactType
from services.contact_resolution_service import resolve_contact_records
from services.contact_service import create_external_contact, list_contact_records
from services.errors.contact import ContactValidationError
from services.entities.contact_entities import ContactRecord, ResolvedContact


class ContactListQuery(BaseModel):
    type: ContactType | None = Field(default=None, description="Optional contact type filter")
    include_disabled: bool = Field(default=True, description="Whether disabled contacts should be included")


class CreateExternalContactPayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return str(value).strip().lower()


class ContactListResponse(BaseModel):
    data: list[ResolvedContact]


register_schema_models(console_ns, ContactListQuery, CreateExternalContactPayload)
register_response_schema_models(console_ns, SimpleResultResponse, ContactRecord, ResolvedContact, ContactListResponse)


@console_ns.route("/workspaces/current/contacts")
class WorkspaceContactsApi(Resource):
    @console_ns.doc(params=query_params_from_model(ContactListQuery))
    @console_ns.response(200, "Success", console_ns.models[ContactListResponse.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        args = query_params_from_request(ContactListQuery, args=request.args)
        contacts = list_contact_records(
            session=db.session,
            tenant_id=tenant_id,
            contact_type=args.type,
            include_disabled=args.include_disabled,
        )
        resolved_contacts = resolve_contact_records(session=db.session, contacts=contacts)
        return dump_response(ContactListResponse, {"data": resolved_contacts}), 200

    @console_ns.expect(console_ns.models[CreateExternalContactPayload.__name__])
    @console_ns.response(201, "Created", console_ns.models[ResolvedContact.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @edit_permission_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        payload = CreateExternalContactPayload.model_validate(console_ns.payload or {})
        try:
            contact = create_external_contact(
                session=db.session,
                tenant_id=tenant_id,
                name=payload.name,
                email=payload.email,
            )
        except ContactValidationError as exc:
            raise UnprocessableEntity(str(exc))
        db.session.commit()
        resolved_contact = resolve_contact_records(session=db.session, contacts=[contact])[0]
        return dump_response(ResolvedContact, resolved_contact), 201
