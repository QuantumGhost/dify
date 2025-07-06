import pytest
from pydantic import ValidationError

from core.file import File, FileTransferMethod, FileType
from core.variables import FileSegment, StringSegment
from core.workflow.constants import CONVERSATION_VARIABLE_NODE_ID, ENVIRONMENT_VARIABLE_NODE_ID
from core.workflow.entities.variable_pool import VariablePool
from core.workflow.enums import SystemVariableKey
from core.workflow.system_variable import SystemVariable
from factories.variable_factory import build_segment, segment_to_variable


@pytest.fixture
def pool():
    return VariablePool(
        system_variables=SystemVariable(user_id="test_user_id", app_id="test_app_id", workflow_id="test_workflow_id"),
        user_inputs={},
    )


@pytest.fixture
def file():
    return File(
        tenant_id="test_tenant_id",
        type=FileType.DOCUMENT,
        transfer_method=FileTransferMethod.LOCAL_FILE,
        related_id="test_related_id",
        remote_url="test_url",
        filename="test_file.txt",
        storage_key="",
    )


def test_get_file_attribute(pool, file):
    # Add a FileSegment to the pool
    pool.add(("node_1", "file_var"), FileSegment(value=file))

    # Test getting the 'name' attribute of the file
    result = pool.get(("node_1", "file_var", "name"))

    assert result is not None
    assert result.value == file.filename

    # Test getting a non-existent attribute
    result = pool.get(("node_1", "file_var", "non_existent_attr"))
    assert result is None


def test_use_long_selector(pool):
    pool.add(("node_1", "part_1", "part_2"), StringSegment(value="test_value"))

    result = pool.get(("node_1", "part_1", "part_2"))
    assert result is not None
    assert result.value == "test_value"


class TestVariablePool:
    def test_constructor(self):
        # Test with minimal required SystemVariable
        minimal_system_vars = SystemVariable(
            user_id="test_user_id", app_id="test_app_id", workflow_id="test_workflow_id"
        )
        pool = VariablePool(system_variables=minimal_system_vars)

        # Test with all parameters
        pool = VariablePool(
            variable_dictionary={},
            user_inputs={},
            system_variables=minimal_system_vars,
            environment_variables=[],
            conversation_variables=[],
        )

        # Test with more complex SystemVariable
        complex_system_vars = SystemVariable(
            user_id="test_user_id", app_id="test_app_id", workflow_id="test_workflow_id"
        )
        pool = VariablePool(
            user_inputs={"key": "value"},
            system_variables=complex_system_vars,
            environment_variables=[
                segment_to_variable(
                    segment=build_segment(1),
                    selector=[ENVIRONMENT_VARIABLE_NODE_ID, "env_var_1"],
                    name="env_var_1",
                )
            ],
            conversation_variables=[
                segment_to_variable(
                    segment=build_segment("1"),
                    selector=[CONVERSATION_VARIABLE_NODE_ID, "conv_var_1"],
                    name="conv_var_1",
                )
            ],
        )

    def test_constructor_with_invalid_system_variable_key(self):
        # Test that SystemVariable validation works properly
        with pytest.raises(ValidationError):
            # This should fail because required fields are missing
            SystemVariable()  # type: ignore

        # Test that VariablePool requires system_variables
        with pytest.raises(ValidationError):
            VariablePool()  # type: ignore
