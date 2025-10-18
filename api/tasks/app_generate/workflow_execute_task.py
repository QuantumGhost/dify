import contextlib
import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Generator, Literal, Self, TypeAlias, Union, overload
import uuid

from celery import shared_task
from flask import current_app, json
from pydantic import BaseModel, Discriminator, Field, Tag
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from core.app.apps.advanced_chat.app_generator import AdvancedChatAppGenerator
from core.app.apps.base_app_generator import BaseAppGenerator
from core.app.entities.app_invoke_entities import (
    InvokeFrom,
)
from extensions.ext_database import db
from extensions.ext_redis import redis_client
from libs.broadcast_channel.redis import BroadcastChannel as RedisBroadcastChannel
from libs.flask_utils import set_login_user
from models.account import Account
from models.model import App, AppMode, EndUser
from models.workflow import Workflow

logger = logging.getLogger(__name__)


class _UserType(StrEnum):
    ACCOUNT = "account"
    END_USER = "end_user"


class _Account(BaseModel):
    TYPE = _UserType.ACCOUNT

    user_id: str


class _EndUser(BaseModel):
    TYPE: _UserType = _UserType.END_USER
    end_user_id: str


def _get_user_type_descriminator(value: Any):
    if isinstance(value, (_Account, _EndUser)):
        return value.TYPE
    elif isinstance(value, dict):
        user_type_str = value.get("type")
        if user_type_str is None:
            return None
        try:
            user_type = _UserType(user_type_str)
        except ValueError:
            return None
        return user_type
    else:
        # return None if the discriminator value isn't found
        return None


User: TypeAlias = Annotated[
    (Annotated[_Account, Tag(_UserType.ACCOUNT)] | Annotated[_EndUser, Tag(_UserType.END_USER)]),
    Discriminator(_get_user_type_descriminator),
]


class ChatflowExecutionParams(BaseModel):
    app_id: str
    workflow_id: str
    tenant_id: str
    user: User
    args: Mapping[str, Any]

    invoke_from: InvokeFrom
    streaming: bool = True
    call_depth: int = 0


def _make_channel_key(app_mode: AppMode, workflow_run_id: str) -> str:



class _ChatflowRunner:
    def __init__(self, session_factory: sessionmaker | Engine, exec_params: ChatflowExecutionParams):
        if isinstance(session_factory, Engine):
            session_factory = sessionmaker(bind=session_factory)
        self._session_factory = session_factory
        self._exec_params = exec_params

    @contextlib.contextmanager
    def _session(self):
        with self._session_factory(expire_on_commit=False) as session, session.begin():
            yield session

    @contextlib.contextmanager
    def _setup_flask_context(self, user: Account | EndUser):
        flask_app = current_app._get_current_object()  # type: ignore
        with flask_app.app_context():
            set_login_user(user)
            yield

    def run(self):
        exec_params = self._exec_params
        with self._session() as session:
            workflow = session.get(Workflow, exec_params.workflow_id)
            app = session.get(App, workflow.app_id)

        user = self._resolve_user()

        chat_generator = AdvancedChatAppGenerator()

        workflow_run_id = uuid.uuid4()

        with self._setup_flask_context(user):
            response = chat_generator.generate(
                app_model=app,
                workflow=workflow,
                user=user,
                args=exec_params.args,
                invoke_from=exec_params.invoke_from,
                streaming=exec_params.streaming,
                workflow_run_id=workflow_run_id
            )
            if not exec_params.streaming:
                return response

            topic = chat_generator.get_response_topic(AppMode.ADVANCED_CHAT, workflow_run_id)
            for event in response:
                try:
                    payload = json.dumps(event)
                except TypeError:
                    logging.exception("error while encoding event")
                    continue

                topic.publish(payload.encode())

    def _resolve_user(self) -> Account | EndUser:
        user_params = self._exec_params.user

        if isinstance(user_params, _EndUser):
            with self._session() as session:
                return session.get(EndUser, user_params.end_user_id)
        elif not isinstance(user_params, _Account):
            raise AssertionError(f"user should only be _Account or _EndUser, got {type(user_params)}")

        with self._session() as session:
            user: Account = session.get(Account, user_params.user_id)
            user.set_tenant_id(self._exec_params.tenant_id)

        return user


@overload
def chatflow_execute_task(
    app_model: App,
    workflow: Workflow,
    user: Union[Account, EndUser],
    args: Mapping[str, Any],
    invoke_from: InvokeFrom,
    streaming: Literal[True],
) -> None: ...


@overload
def chatflow_execute_task(
    app_model: App,
    workflow: Workflow,
    user: Union[Account, EndUser],
    args: Mapping[str, Any],
    invoke_from: InvokeFrom,
    streaming: Literal[False],
) -> Mapping[str, Any]: ...


@shared_task(queue="chatflow_execute")
def chatflow_execute_task(payload: str) -> Mapping[str, Any] | None:
    exec_params = ChatflowExecutionParams.model_validate_json(payload)

    runner = _ChatflowRunner(db.engine, exec_params=exec_params)
    return runner.run()


def consume_event(app_mode: AppMode, task_id: str) -> Generator[str, None, None]:
    channel_key = _make_channel_key(app_mode, task_id)
    channel = RedisBroadcastChannel(redis_client=redis_client)
    topic = channel.topic(channel_key)

    def gen() -> Generator[str | Mapping[str, Any], None, None]:
        with topic.subscribe() as subscription:
            for event in subscription:
                payload = _Payload.model_validate_json(event)
                yield payload.value

    return BaseAppGenerator.convert_to_event_stream(gen)
