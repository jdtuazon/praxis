"""Linear GraphQL client + schema introspection.

Counts every GraphQL request (the primary learning metric), retries on rate
limits with backoff, and exposes schema introspection that the synthesizer uses
to reason about *real* operations rather than a hard-coded endpoint table.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from graphql import build_client_schema, get_introspection_query, print_schema
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from ..base import GraphQLTransport, PlatformError


class HttpxTransport:
    """Real transport: talks to https://api.linear.app/graphql."""

    def __init__(self, url: str, api_key: str, timeout: float = 30.0) -> None:
        self._url = url
        # Linear personal API keys go in the Authorization header verbatim
        # (no "Bearer" prefix). OAuth tokens would use "Bearer <token>".
        self._client = httpx.Client(
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        resp = self._client.post(self._url, json={"query": query, "variables": variables})
        if resp.status_code == 429:
            raise PlatformError("Rate limited by Linear", code="RATELIMITED", status=429)
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()


def _is_rate_limit(exc: BaseException) -> bool:
    return isinstance(exc, PlatformError) and exc.is_rate_limit


class LinearClient:
    """Transport-agnostic Linear client. Counts API calls; surfaces structured errors."""

    def __init__(self, transport: GraphQLTransport) -> None:
        self._t = transport
        self.api_calls = 0
        self._sdl_cache: str | None = None
        self._schema_obj = None
        self._schema_hash: str | None = None

    def reset_counter(self) -> None:
        self.api_calls = 0

    @retry(
        retry=retry_if_exception(_is_rate_limit),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a GraphQL document; return `data`, raising PlatformError on errors."""
        self.api_calls += 1
        resp = self._t.execute(query, variables or {})
        if resp.get("errors"):
            raise PlatformError.from_graphql(resp["errors"])
        return resp.get("data", {}) or {}

    # ── Introspection ─────────────────────────────────────────────────────────
    def introspect_sdl(self, *, use_cache: bool = True) -> str:
        """Return the platform schema as SDL (works for real Linear and FakeLinear)."""
        if use_cache and self._sdl_cache is not None:
            return self._sdl_cache
        data = self.execute(get_introspection_query(descriptions=True))
        schema = build_client_schema(data)
        sdl = print_schema(schema)
        self._sdl_cache = sdl
        return sdl

    def graphql_schema(self):
        """Return the built GraphQLSchema object (cached) for programmatic validation."""
        if self._schema_obj is None:
            data = self.execute(get_introspection_query(descriptions=False))
            self._schema_obj = build_client_schema(data)
        return self._schema_obj

    def schema_hash(self) -> str:
        """A stable hash of the root field signatures — provenance for synthesized caps."""
        if self._schema_hash is None:
            import hashlib

            schema = self.graphql_schema()
            sig_parts: list[str] = []
            for root in (schema.query_type, schema.mutation_type):
                if not root:
                    continue
                for fname, field in sorted(root.fields.items()):
                    args = ",".join(sorted(field.args))
                    sig_parts.append(f"{fname}({args}):{field.type}")
            self._schema_hash = hashlib.sha256("\n".join(sig_parts).encode()).hexdigest()[:16]
        return self._schema_hash

    def root_field(self, operation_type: str, name: str):
        """Return the GraphQLField for a Query/Mutation root field, or None."""
        schema = self.graphql_schema()
        root = schema.query_type if operation_type == "query" else schema.mutation_type
        if not root:
            return None
        return root.fields.get(name)

    def schema_digest(self, keywords: list[str], *, max_types: int = 18) -> str:
        """A focused slice of the schema for the synthesizer.

        Always includes the root Query/Mutation field lists, plus the full
        definitions of types whose names match any keyword. Keeps prompts small
        even against a huge real schema.
        """
        sdl = self.introspect_sdl()
        blocks = _split_sdl_types(sdl)
        kw = [k.lower() for k in keywords if k]

        chosen: list[str] = []
        # Root types first.
        for root in ("type Query", "type Mutation"):
            for block in blocks.values():
                if block.startswith(root):
                    chosen.append(block)
        # Keyword-matched types.
        for name, block in blocks.items():
            if name in ("Query", "Mutation"):
                continue
            low = name.lower()
            if any(k in low for k in kw):
                chosen.append(block)
            if len(chosen) >= max_types:
                break
        return "\n\n".join(dict.fromkeys(chosen))  # dedupe, preserve order


def _split_sdl_types(sdl: str) -> dict[str, str]:
    """Split printed SDL into {type_name: definition_block}."""
    blocks: dict[str, str] = {}
    # Match top-level definitions: type/input/enum/interface/union/scalar Name ...
    pattern = re.compile(
        r"(?:^|\n)((?:\"\"\".*?\"\"\"\n)?(?:type|input|enum|interface|union|scalar)\s+(\w+)[\s\S]*?)(?=\n(?:\"\"\"|type |input |enum |interface |union |scalar )|\Z)",
        re.MULTILINE,
    )
    for m in pattern.finditer(sdl):
        block = m.group(1).strip()
        name = m.group(2)
        blocks[name] = block
    return blocks
