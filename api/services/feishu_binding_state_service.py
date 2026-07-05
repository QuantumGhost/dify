import json
import uuid
from typing import TypedDict

from extensions.ext_redis import redis_client

_TTL_SECONDS = 10 * 60
_KEY_PREFIX = "feishu_binding_context:"


class FeishuBindingContext(TypedDict):
    account_id: str


class FeishuBindingStateService:
    def create_context(self, *, account_id: str) -> str:
        context_id = str(uuid.uuid4())
        payload: FeishuBindingContext = {
            "account_id": account_id,
        }
        redis_client.setex(f"{_KEY_PREFIX}{context_id}", _TTL_SECONDS, json.dumps(payload))
        return context_id

    def consume_context(self, context_id: str) -> FeishuBindingContext:
        if not context_id:
            raise ValueError("state is required")

        key = f"{_KEY_PREFIX}{context_id}"
        raw_payload = redis_client.get(key)
        if not raw_payload:
            raise ValueError("state is invalid")

        redis_client.delete(key)
        payload = json.loads(raw_payload)
        account_id = payload.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("state is invalid")
        return {
            "account_id": account_id,
        }


_service = FeishuBindingStateService()


def get_feishu_binding_state_service() -> FeishuBindingStateService:
    return _service
