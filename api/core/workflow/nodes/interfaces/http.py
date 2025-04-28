import dataclasses
import json
from collections.abc import Callable, Iterable
from typing import Any, TypeAlias
from urllib.parse import ParseResult as Url

# There is no Go's io.Reader alternative in Python.
# It seems that Iterable[bytes] is the closest type
# we can get and httpx support.
Reader: TypeAlias = Iterable[bytes]
URLType: TypeAlias = str | Url

_DEFAULT_METHOD: str = "GET"


@dataclasses.dataclass(frozen=True, init=False, eq=False)
class Request:
    url: URLType

    method: str = _DEFAULT_METHOD
    headers: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    body: bytes | Reader = b""

    @classmethod
    def create_get_request(
        cls,
        url: URLType,
        headers: list[tuple[str, str]] | None = None,
        body: bytes | Reader = b"",
    ) -> "Request":
        pass

    @classmethod
    def create_text_request(
        cls,
        *,
        url: Url,
        method: str = _DEFAULT_METHOD,
        headers: list[tuple[str, str]] | None = None,
        body: Any,
        json_encoder: Callable[[Any], str] = json.dumps,
    ) -> "Request":
        pass

    @classmethod
    def create_json_request(
        cls,
        *,
        url: Url,
        method: str = _DEFAULT_METHOD,
        headers: list[tuple[str, str]] | None = None,
        body: Any,
        json_encoder: Callable[[Any], str] = json.dumps,
    ) -> "Request":
        pass

    @classmethod
    def create_form_request(
        cls,
        *,
        url: Url,
        method: str = _DEFAULT_METHOD,
        headers: list[tuple[str, str]] | None = None,
        body: ...,
        form_encoder: Callable[[Any], str] = json.dumps,
    ):
        pass

    @classmethod
    def create_multipart_request(
        cls,
        *,
        url: Url,
        method: str = _DEFAULT_METHOD,
        headers: list[tuple[str, str]] | None = None,
        body: ...,
    ):
        pass
