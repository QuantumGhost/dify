from collections.abc import Sequence

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from core.file.models import File


class SystemVariable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        serialize_by_alias=True,
        validate_by_alias=True,
    )

    user_id: str
    app_id: str
    workflow_id: str

    # Optional fields
    files: Sequence[File] = Field(default_factory=list)
    workflow_execution_id: str | None = Field(
        validation_alias=AliasChoices("workflow_execution_id", "workflow_run_id"),
        serialization_alias="workflow_run_id",
        default=None,
    )
    # Chatflow related fields.
    query: str | None = None
    conversation_id: str | None = None
    dialogue_count: int | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_json_fields(cls, data):
        if isinstance(data, dict):
            # For JSON validation, only allow workflow_run_id
            if "workflow_execution_id" in data and "workflow_run_id" not in data:
                # This is likely from direct instantiation, allow it
                return data
            elif "workflow_execution_id" in data and "workflow_run_id" in data:
                # Both present, remove workflow_execution_id
                data = data.copy()
                data.pop("workflow_execution_id")
                return data
        return data
