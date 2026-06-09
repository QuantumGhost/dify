"""Console app statistics endpoints backed by SQLAlchemy expressions.

The legacy implementation assembled vendor-specific SQL strings inline. The
queries below preserve that behaviour while moving to ORM-backed expressions so
the statistics continue to match the historical raw SQL semantics pinned by the
integration tests.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypeVar

import sqlalchemy as sa
from flask import abort, jsonify, request
from flask_restx import Resource, fields
from pydantic import BaseModel, Field, field_validator

from configs import dify_config
from controllers.common.schema import register_schema_models
from controllers.console import console_ns
from controllers.console.app.wraps import get_app_model
from controllers.console.wraps import account_initialization_required, setup_required, with_current_user
from core.app.entities.app_invoke_entities import InvokeFrom
from extensions.ext_database import db
from libs.datetime_utils import parse_time_range
from libs.helper import convert_datetime_to_date as _legacy_convert_datetime_to_date
from libs.login import login_required
from models import AppMode
from models.account import Account
from models.enums import FeedbackRating
from models.model import App, Conversation, Message, MessageFeedback


class StatisticTimeRangeQuery(BaseModel):
    start: str | None = Field(default=None, description="Start date (YYYY-MM-DD HH:MM)")
    end: str | None = Field(default=None, description="End date (YYYY-MM-DD HH:MM)")

    @field_validator("start", "end", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: str | None) -> str | None:
        if value == "":
            return None
        return value


register_schema_models(console_ns, StatisticTimeRangeQuery)


def convert_datetime_to_date(field: str, target_timezone: str = ":tz") -> str:
    """Compatibility shim kept for existing unit tests that monkeypatch this symbol."""
    return _legacy_convert_datetime_to_date(field, target_timezone)


def _build_local_date_bucket(field: sa.SQLColumnExpression[datetime]) -> sa.ColumnElement[date]:
    """Match the legacy SQL day-bucketing semantics for each supported database."""
    if dify_config.DB_TYPE == "postgresql":
        return sa.cast(
            sa.func.date_trunc(
                "day",
                sa.func.timezone(sa.bindparam("tz"), sa.func.timezone("UTC", field)),
            ),
            sa.Date,
        )

    if dify_config.DB_TYPE in {"mysql", "oceanbase", "seekdb"}:
        return sa.func.date(sa.func.convert_tz(field, "UTC", sa.bindparam("tz")))

    raise NotImplementedError(f"Unsupported database type: {dify_config.DB_TYPE}")


def _get_time_range_or_abort(
    args: StatisticTimeRangeQuery,
    timezone: str,
) -> tuple[datetime | None, datetime | None]:
    try:
        return parse_time_range(args.start, args.end, timezone)
    except ValueError as e:
        raise abort(400, description=str(e))


def _apply_time_range_filters[T: tuple](
    statement: sa.Select[T],
    field: sa.SQLColumnExpression[datetime],
    start_datetime_utc: datetime | None,
    end_datetime_utc: datetime | None,
) -> sa.Select[T]:
    if start_datetime_utc is not None:
        statement = statement.where(field >= sa.bindparam("start"))

    if end_datetime_utc is not None:
        statement = statement.where(field < sa.bindparam("end"))

    return statement


def _message_statistic_base(
    *columns: sa.ColumnExpressionArgument[Any],
) -> tuple[sa.ColumnElement[date], sa.Select[tuple[Any, ...]]]:
    date_bucket = _build_local_date_bucket(Message.created_at).label("date")
    statement = (
        sa.select(date_bucket, *columns)
        .select_from(Message)
        .where(
            Message.app_id == sa.bindparam("app_id"),
            Message.invoke_from != sa.bindparam("invoke_from"),
        )
    )
    return date_bucket, statement


def _build_statistic_parameters(
    account: Account,
    app_model: App,
    start_datetime_utc: datetime | None,
    end_datetime_utc: datetime | None,
) -> dict[str, Any]:
    assert account.timezone is not None
    parameters: dict[str, Any] = {
        "tz": account.timezone,
        "app_id": app_model.id,
        "invoke_from": InvokeFrom.DEBUGGER,
    }

    if start_datetime_utc is not None:
        parameters["start"] = start_datetime_utc

    if end_datetime_utc is not None:
        parameters["end"] = end_datetime_utc

    return parameters


@console_ns.route("/apps/<uuid:app_id>/statistics/daily-messages")
class DailyMessageStatistic(Resource):
    @console_ns.doc("get_daily_message_statistics")
    @console_ns.doc(description="Get daily message statistics for an application")
    @console_ns.doc(params={"app_id": "Application ID"})
    @console_ns.expect(console_ns.models[StatisticTimeRangeQuery.__name__])
    @console_ns.response(
        200,
        "Daily message statistics retrieved successfully",
        fields.List(fields.Raw(description="Daily message count data")),
    )
    @get_app_model
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    def get(self, account: Account, app_model: App):
        args = StatisticTimeRangeQuery.model_validate(request.args.to_dict(flat=True))
        assert account.timezone is not None
        start_datetime_utc, end_datetime_utc = _get_time_range_or_abort(args, account.timezone)
        parameters = _build_statistic_parameters(account, app_model, start_datetime_utc, end_datetime_utc)
        date_bucket, statement = _message_statistic_base(sa.func.count().label("message_count"))
        statement = _apply_time_range_filters(statement, Message.created_at, start_datetime_utc, end_datetime_utc)
        statement = statement.group_by(date_bucket).order_by(date_bucket)

        response_data = []

        with db.engine.begin() as conn:
            rs = conn.execute(statement, parameters)
            for i in rs:
                response_data.append({"date": str(i.date), "message_count": i.message_count})

        return jsonify({"data": response_data})


@console_ns.route("/apps/<uuid:app_id>/statistics/daily-conversations")
class DailyConversationStatistic(Resource):
    @console_ns.doc("get_daily_conversation_statistics")
    @console_ns.doc(description="Get daily conversation statistics for an application")
    @console_ns.doc(params={"app_id": "Application ID"})
    @console_ns.expect(console_ns.models[StatisticTimeRangeQuery.__name__])
    @console_ns.response(
        200,
        "Daily conversation statistics retrieved successfully",
        fields.List(fields.Raw(description="Daily conversation count data")),
    )
    @get_app_model
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    def get(self, account: Account, app_model: App):
        args = StatisticTimeRangeQuery.model_validate(request.args.to_dict(flat=True))
        assert account.timezone is not None
        start_datetime_utc, end_datetime_utc = _get_time_range_or_abort(args, account.timezone)
        parameters = _build_statistic_parameters(account, app_model, start_datetime_utc, end_datetime_utc)
        date_bucket, statement = _message_statistic_base(
            sa.func.count(sa.distinct(Message.conversation_id)).label("conversation_count")
        )
        statement = _apply_time_range_filters(statement, Message.created_at, start_datetime_utc, end_datetime_utc)
        statement = statement.group_by(date_bucket).order_by(date_bucket)

        response_data = []
        with db.engine.begin() as conn:
            rs = conn.execute(statement, parameters)
            for i in rs:
                response_data.append({"date": str(i.date), "conversation_count": i.conversation_count})

        return jsonify({"data": response_data})


@console_ns.route("/apps/<uuid:app_id>/statistics/daily-end-users")
class DailyTerminalsStatistic(Resource):
    @console_ns.doc("get_daily_terminals_statistics")
    @console_ns.doc(description="Get daily terminal/end-user statistics for an application")
    @console_ns.doc(params={"app_id": "Application ID"})
    @console_ns.expect(console_ns.models[StatisticTimeRangeQuery.__name__])
    @console_ns.response(
        200,
        "Daily terminal statistics retrieved successfully",
        fields.List(fields.Raw(description="Daily terminal count data")),
    )
    @get_app_model
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    def get(self, account: Account, app_model: App):
        args = StatisticTimeRangeQuery.model_validate(request.args.to_dict(flat=True))
        assert account.timezone is not None
        start_datetime_utc, end_datetime_utc = _get_time_range_or_abort(args, account.timezone)
        parameters = _build_statistic_parameters(account, app_model, start_datetime_utc, end_datetime_utc)
        date_bucket, statement = _message_statistic_base(
            sa.func.count(sa.distinct(Message.from_end_user_id)).label("terminal_count")
        )
        statement = _apply_time_range_filters(statement, Message.created_at, start_datetime_utc, end_datetime_utc)
        statement = statement.group_by(date_bucket).order_by(date_bucket)

        response_data = []

        with db.engine.begin() as conn:
            rs = conn.execute(statement, parameters)
            for i in rs:
                response_data.append({"date": str(i.date), "terminal_count": i.terminal_count})

        return jsonify({"data": response_data})


@console_ns.route("/apps/<uuid:app_id>/statistics/token-costs")
class DailyTokenCostStatistic(Resource):
    @console_ns.doc("get_daily_token_cost_statistics")
    @console_ns.doc(description="Get daily token cost statistics for an application")
    @console_ns.doc(params={"app_id": "Application ID"})
    @console_ns.expect(console_ns.models[StatisticTimeRangeQuery.__name__])
    @console_ns.response(
        200,
        "Daily token cost statistics retrieved successfully",
        fields.List(fields.Raw(description="Daily token cost data")),
    )
    @get_app_model
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    def get(self, account: Account, app_model: App):
        args = StatisticTimeRangeQuery.model_validate(request.args.to_dict(flat=True))
        assert account.timezone is not None
        start_datetime_utc, end_datetime_utc = _get_time_range_or_abort(args, account.timezone)
        parameters = _build_statistic_parameters(account, app_model, start_datetime_utc, end_datetime_utc)
        token_count = (sa.func.sum(Message.message_tokens) + sa.func.sum(Message.answer_tokens)).label("token_count")
        date_bucket, statement = _message_statistic_base(
            token_count,
            sa.func.sum(Message.total_price).label("total_price"),
        )
        statement = _apply_time_range_filters(statement, Message.created_at, start_datetime_utc, end_datetime_utc)
        statement = statement.group_by(date_bucket).order_by(date_bucket)

        response_data = []

        with db.engine.begin() as conn:
            rs = conn.execute(statement, parameters)
            for i in rs:
                response_data.append(
                    {"date": str(i.date), "token_count": i.token_count, "total_price": i.total_price, "currency": "USD"}
                )

        return jsonify({"data": response_data})


@console_ns.route("/apps/<uuid:app_id>/statistics/average-session-interactions")
class AverageSessionInteractionStatistic(Resource):
    @console_ns.doc("get_average_session_interaction_statistics")
    @console_ns.doc(description="Get average session interaction statistics for an application")
    @console_ns.doc(params={"app_id": "Application ID"})
    @console_ns.expect(console_ns.models[StatisticTimeRangeQuery.__name__])
    @console_ns.response(
        200,
        "Average session interaction statistics retrieved successfully",
        fields.List(fields.Raw(description="Average session interaction data")),
    )
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=[AppMode.CHAT, AppMode.AGENT_CHAT, AppMode.ADVANCED_CHAT, AppMode.AGENT])
    @with_current_user
    def get(self, account: Account, app_model: App):
        args = StatisticTimeRangeQuery.model_validate(request.args.to_dict(flat=True))
        assert account.timezone is not None
        start_datetime_utc, end_datetime_utc = _get_time_range_or_abort(args, account.timezone)
        parameters = _build_statistic_parameters(account, app_model, start_datetime_utc, end_datetime_utc)
        date_bucket = _build_local_date_bucket(Conversation.created_at).label("date")
        session_message_counts = (
            sa.select(
                Message.conversation_id.label("conversation_id"),
                sa.func.count(Message.id).label("message_count"),
            )
            .select_from(Conversation)
            .join(Message, Conversation.id == Message.conversation_id)
            .where(
                Conversation.app_id == sa.bindparam("app_id"),
                Message.invoke_from != sa.bindparam("invoke_from"),
            )
        )
        session_message_counts = _apply_time_range_filters(
            session_message_counts,
            Conversation.created_at,
            start_datetime_utc,
            end_datetime_utc,
        )
        session_message_counts_subquery = session_message_counts.group_by(Message.conversation_id).subquery("subquery")
        statement = (
            sa.select(
                date_bucket,
                sa.func.avg(session_message_counts_subquery.c.message_count).label("interactions"),
            )
            .select_from(
                session_message_counts_subquery.outerjoin(
                    Conversation,
                    Conversation.id == session_message_counts_subquery.c.conversation_id,
                )
            )
            .group_by(date_bucket)
            .order_by(date_bucket)
        )

        response_data = []

        with db.engine.begin() as conn:
            rs = conn.execute(statement, parameters)
            for i in rs:
                response_data.append(
                    {"date": str(i.date), "interactions": float(i.interactions.quantize(Decimal("0.01")))}
                )

        return jsonify({"data": response_data})


@console_ns.route("/apps/<uuid:app_id>/statistics/user-satisfaction-rate")
class UserSatisfactionRateStatistic(Resource):
    @console_ns.doc("get_user_satisfaction_rate_statistics")
    @console_ns.doc(description="Get user satisfaction rate statistics for an application")
    @console_ns.doc(params={"app_id": "Application ID"})
    @console_ns.expect(console_ns.models[StatisticTimeRangeQuery.__name__])
    @console_ns.response(
        200,
        "User satisfaction rate statistics retrieved successfully",
        fields.List(fields.Raw(description="User satisfaction rate data")),
    )
    @get_app_model
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    def get(self, account: Account, app_model: App):
        args = StatisticTimeRangeQuery.model_validate(request.args.to_dict(flat=True))
        assert account.timezone is not None
        start_datetime_utc, end_datetime_utc = _get_time_range_or_abort(args, account.timezone)
        parameters = _build_statistic_parameters(account, app_model, start_datetime_utc, end_datetime_utc)
        date_bucket = _build_local_date_bucket(Message.created_at).label("date")
        statement = (
            sa.select(
                date_bucket,
                sa.func.count(Message.id).label("message_count"),
                sa.func.count(MessageFeedback.id).label("feedback_count"),
            )
            .select_from(Message)
            .outerjoin(
                MessageFeedback,
                sa.and_(
                    MessageFeedback.message_id == Message.id,
                    MessageFeedback.rating == FeedbackRating.LIKE,
                ),
            )
            .where(
                Message.app_id == sa.bindparam("app_id"),
                Message.invoke_from != sa.bindparam("invoke_from"),
            )
        )
        statement = _apply_time_range_filters(statement, Message.created_at, start_datetime_utc, end_datetime_utc)
        statement = statement.group_by(date_bucket).order_by(date_bucket)

        response_data = []

        with db.engine.begin() as conn:
            rs = conn.execute(statement, parameters)
            for i in rs:
                response_data.append(
                    {
                        "date": str(i.date),
                        "rate": round((i.feedback_count * 1000 / i.message_count) if i.message_count > 0 else 0, 2),
                    }
                )

        return jsonify({"data": response_data})


@console_ns.route("/apps/<uuid:app_id>/statistics/average-response-time")
class AverageResponseTimeStatistic(Resource):
    @console_ns.doc("get_average_response_time_statistics")
    @console_ns.doc(description="Get average response time statistics for an application")
    @console_ns.doc(params={"app_id": "Application ID"})
    @console_ns.expect(console_ns.models[StatisticTimeRangeQuery.__name__])
    @console_ns.response(
        200,
        "Average response time statistics retrieved successfully",
        fields.List(fields.Raw(description="Average response time data")),
    )
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=AppMode.COMPLETION)
    @with_current_user
    def get(self, account: Account, app_model: App):
        args = StatisticTimeRangeQuery.model_validate(request.args.to_dict(flat=True))
        assert account.timezone is not None
        start_datetime_utc, end_datetime_utc = _get_time_range_or_abort(args, account.timezone)
        parameters = _build_statistic_parameters(account, app_model, start_datetime_utc, end_datetime_utc)
        date_bucket, statement = _message_statistic_base(
            sa.func.avg(Message.provider_response_latency).label("latency"),
        )
        statement = _apply_time_range_filters(statement, Message.created_at, start_datetime_utc, end_datetime_utc)
        statement = statement.group_by(date_bucket).order_by(date_bucket)

        response_data = []

        with db.engine.begin() as conn:
            rs = conn.execute(statement, parameters)
            for i in rs:
                response_data.append({"date": str(i.date), "latency": round(i.latency * 1000, 4)})

        return jsonify({"data": response_data})


@console_ns.route("/apps/<uuid:app_id>/statistics/tokens-per-second")
class TokensPerSecondStatistic(Resource):
    @console_ns.doc("get_tokens_per_second_statistics")
    @console_ns.doc(description="Get tokens per second statistics for an application")
    @console_ns.doc(params={"app_id": "Application ID"})
    @console_ns.expect(console_ns.models[StatisticTimeRangeQuery.__name__])
    @console_ns.response(
        200,
        "Tokens per second statistics retrieved successfully",
        fields.List(fields.Raw(description="Tokens per second data")),
    )
    @get_app_model
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    def get(self, account: Account, app_model: App):
        args = StatisticTimeRangeQuery.model_validate(request.args.to_dict(flat=True))
        assert account.timezone is not None
        start_datetime_utc, end_datetime_utc = _get_time_range_or_abort(args, account.timezone)
        parameters = _build_statistic_parameters(account, app_model, start_datetime_utc, end_datetime_utc)
        total_latency = sa.func.sum(Message.provider_response_latency)
        date_bucket, statement = _message_statistic_base(
            sa.case(
                (total_latency == 0, 0),
                else_=(sa.func.sum(Message.answer_tokens) / total_latency),
            ).label("tokens_per_second"),
        )
        statement = _apply_time_range_filters(statement, Message.created_at, start_datetime_utc, end_datetime_utc)
        statement = statement.group_by(date_bucket).order_by(date_bucket)

        response_data = []

        with db.engine.begin() as conn:
            rs = conn.execute(statement, parameters)
            for i in rs:
                response_data.append({"date": str(i.date), "tps": round(i.tokens_per_second, 4)})

        return jsonify({"data": response_data})
