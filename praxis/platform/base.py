"""Platform transport abstraction.

`LinearClient` never knows whether it is talking to the real Linear API or the
in-process `FakeLinear` simulation — both implement `GraphQLTransport`. This is
the seam that lets the production code path run unchanged in offline tests, and
it is where every GraphQL request is counted (the primary learning metric).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class PlatformError(RuntimeError):
    """A structured error from the platform.

    The learner inspects `code`, `path` and `extensions` to extract constraints
    (e.g. an enum validation error becomes a reusable ENUM constraint).
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        path: list[str] | None = None,
        extensions: dict[str, Any] | None = None,
        status: int | None = None,
        raw_errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path or []
        self.extensions = extensions or {}
        self.status = status
        self.raw_errors = raw_errors or []

    @classmethod
    def from_graphql(cls, errors: list[dict[str, Any]], status: int | None = None) -> PlatformError:
        first = errors[0] if errors else {}
        ext = first.get("extensions", {}) or {}
        code = ext.get("code") or ext.get("type")
        msg = first.get("message", "GraphQL error")
        return cls(
            msg, code=code, path=first.get("path"), extensions=ext, status=status, raw_errors=errors
        )

    @property
    def is_rate_limit(self) -> bool:
        return self.status == 429 or (self.code or "").upper() in {"RATELIMITED", "RATE_LIMITED"}


@runtime_checkable
class GraphQLTransport(Protocol):
    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Execute a GraphQL document and return the raw `{data, errors}` response."""
        ...
