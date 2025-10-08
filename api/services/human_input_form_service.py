"""
Service for managing human input forms.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from models.human_input import HumanInputForm, HumanInputFormStatus, HumanInputSubmissionType
from services.errors.base import BaseServiceError

logger = logging.getLogger(__name__)


class HumanInputFormNotFoundError(BaseServiceError):
    """Raised when a human input form is not found."""

    def __init__(self, identifier: str):
        super().__init__(f"Human input form not found: {identifier}")
        self.identifier = identifier


class HumanInputFormExpiredError(BaseServiceError):
    """Raised when a human input form has expired."""

    def __init__(self):
        super().__init__("Human input form has expired")


class HumanInputFormAlreadySubmittedError(BaseServiceError):
    """Raised when trying to operate on an already submitted form."""

    def __init__(self):
        super().__init__("Human input form has already been submitted")


class InvalidFormDataError(BaseServiceError):
    """Raised when form submission data is invalid."""

    def __init__(self, message: str):
        super().__init__(f"Invalid form data: {message}")
        self.message = message


class HumanInputFormService:
    """Service for managing human input forms."""

    def __init__(self, session: Session):
        self._session = session

    def create_form(
        self,
        *,
        form_id: str,
        workflow_run_id: str,
        tenant_id: str,
        app_id: str,
        form_definition: str,
        rendered_content: str,
        web_app_token: Optional[str] = None,
    ) -> HumanInputForm:
        """Create a new human input form."""
        form = HumanInputForm(
            id=form_id,
            tenant_id=tenant_id,
            app_id=app_id,
            workflow_run_id=workflow_run_id,
            form_definition=form_definition,
            rendered_content=rendered_content,
            status=HumanInputFormStatus.WAITING,
            web_app_token=web_app_token,
        )

        self._session.add(form)
        self._session.commit()

        logger.info("Created human input form %s", form_id)
        return form

    def get_form_by_id(self, form_id: str) -> HumanInputForm:
        """Get a form by its ID."""
        form = self._session.get(HumanInputForm, form_id)
        if not form:
            raise HumanInputFormNotFoundError(form_id)
        return form

    def get_form_by_token(self, web_app_token: str) -> HumanInputForm:
        """Get a form by its web app token."""
        stmt = select(HumanInputForm).where(HumanInputForm.web_app_token == web_app_token)
        form = self._session.scalar(stmt)
        if not form:
            raise HumanInputFormNotFoundError(web_app_token)
        return form

    def get_form_definition(
        self,
        identifier: str,
        is_token: bool = False,
        include_site_info: bool = False,
    ) -> dict[str, Any]:
        """
        Get form definition for display.

        Args:
            identifier: Form ID or web app token
            is_token: True if identifier is a web app token, False if it's a form ID
            include_site_info: Whether to include site information in the response
        """
        if is_token:
            form = self.get_form_by_token(identifier)
        else:
            form = self.get_form_by_id(identifier)

        if form.status == HumanInputFormStatus.EXPIRED:
            raise HumanInputFormExpiredError()

        if form.status == HumanInputFormStatus.SUBMITTED:
            raise HumanInputFormAlreadySubmittedError()

        # Parse form definition from JSON
        form_definition = json.loads(form.form_definition)
        response = {
            "form_content": form.rendered_content,
            "inputs": form_definition.get("inputs", []),
            "user_actions": form_definition.get("user_actions", []),
        }

        if include_site_info:
            response["site"] = {
                "app_id": form.app_id,
                "title": "Workflow Form",
            }

        return response

    def submit_form(
        self,
        identifier: str,
        form_data: dict[str, Any],
        action: str,
        is_token: bool = False,
        submission_type: HumanInputSubmissionType = HumanInputSubmissionType.web_form,
        submission_user_id: Optional[str] = None,
        submission_end_user_id: Optional[str] = None,
    ) -> HumanInputForm:
        """
        Submit a form.

        Args:
            identifier: Form ID or web app token
            form_data: The submitted form data
            action: The action taken by the user
            is_token: True if identifier is a web app token, False if it's a form ID
            submission_type: Type of submission (web_form, web_app, email)
            submission_user_id: ID of the user who submitted (for console submissions)
            submission_end_user_id: ID of the end user who submitted (for webapp submissions)
        """
        if is_token:
            form = self.get_form_by_token(identifier)
        else:
            form = self.get_form_by_id(identifier)

        if form.status == HumanInputFormStatus.EXPIRED:
            raise HumanInputFormExpiredError()

        if form.status == HumanInputFormStatus.SUBMITTED:
            raise HumanInputFormAlreadySubmittedError()

        # Validate submission data
        self._validate_submission(form, form_data, action)

        # Update form with submission
        form.submitted_data = json.dumps(form_data)
        form.submitted_at = datetime.utcnow()
        form.status = HumanInputFormStatus.SUBMITTED
        form.submission_type = submission_type
        form.submission_user_id = submission_user_id
        form.submission_end_user_id = submission_end_user_id

        self._session.commit()

        logger.info(f"Form {form.id} submitted with action {action}")
        return form

    def _validate_submission(self, form: HumanInputForm, form_data: dict[str, Any], action: str) -> None:
        """Validate form submission data."""
        form_definition = json.loads(form.form_definition)

        # Check that the action is valid
        valid_actions = {act.get("id") for act in form_definition.get("user_actions", [])}
        if action not in valid_actions:
            raise InvalidFormDataError(f"Invalid action: {action}")

        # Note: We don't validate required inputs here as the original implementation
        # allows extra inputs and doesn't strictly enforce all inputs to be present

    def cleanup_expired_forms(self) -> int:
        """Clean up expired forms. Returns the number of forms cleaned up."""
        now = datetime.utcnow()

        # Find expired forms that are still in WAITING status
        stmt = select(HumanInputForm).where(
            and_(
                HumanInputForm.status == HumanInputFormStatus.WAITING,
                HumanInputForm.created_at < now - timedelta(hours=48),  # Default expiry
            )
        )

        expired_forms = self._session.scalars(stmt).all()
        count = 0

        for form in expired_forms:
            form.status = HumanInputFormStatus.EXPIRED
            count += 1

        self._session.commit()
        return count

    def get_pending_forms_for_workflow_run(self, workflow_run_id: str) -> list[HumanInputForm]:
        """Get all pending human input forms for a workflow run."""
        stmt = select(HumanInputForm).where(
            and_(
                HumanInputForm.workflow_run_id == workflow_run_id, HumanInputForm.status == HumanInputFormStatus.WAITING
            )
        )
        return list(self._session.scalars(stmt).all())
