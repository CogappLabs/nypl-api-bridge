"""Thin async client for the NYPL Digital Collections Repo API (v2 only).

Docs: https://api.repo.nypl.org/
"""

import re
from typing import Any, Literal

import httpx
from fastmcp.exceptions import ToolError

BASE_URL = "https://api.repo.nypl.org/api/v2/"
DEFAULT_TIMEOUT_SECONDS = 30.0

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_IDENTIFIER_VALUE_RE = re.compile(r"^[A-Za-z0-9._-]+$")

IdentifierType = Literal[
    "local_image_id",
    "local_bnumber",
    "local_barcode",
    "local_mss",
    "local_archives_ead",
    "local_tms_id",
    "oclc",
    "isbn",
    "lccn",
]

CollectionView = Literal["children", "subcollections", "items"]


def require_uuid(value: str) -> str:
    """Validate a UUID before it is interpolated into a URL path."""
    if not _UUID_RE.match(value):
        raise ToolError(f"Not a valid NYPL UUID: {value!r}")
    return value.lower()


def require_identifier_value(value: str) -> str:
    if not _IDENTIFIER_VALUE_RE.match(value):
        raise ToolError(f"Identifier contains unsupported characters: {value!r}")
    return value


def unwrap(payload: Any) -> Any:
    """Strip the `nyplAPI.response` envelope when present; otherwise return the payload as-is."""
    if isinstance(payload, dict) and "nyplAPI" in payload:
        envelope = payload["nyplAPI"]
        if isinstance(envelope, dict) and "response" in envelope:
            return envelope["response"]
    return payload


def build_http_client(token: str, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"Authorization": f'Token token="{token}"', "Accept": "application/json"},
        timeout=DEFAULT_TIMEOUT_SECONDS,
        transport=transport,
    )


class NyplApi:
    """Wraps the v2 endpoints this server exposes. One method per endpoint."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def _get(self, path: str, params: dict[str, Any] | None) -> Any:
        response = await self._http.get(path, params=params)
        if response.status_code == 401:
            raise ToolError("NYPL API rejected the token (401). Check NYPL_API_TOKEN.")
        if response.status_code == 404:
            raise ToolError(f"Not found: {path}")
        if not response.is_success:
            raise ToolError(f"NYPL API error {response.status_code} for {path}: {response.text[:300]}")
        return unwrap(response.json())

    async def search_items(
        self,
        *,
        query: str,
        field: str | None,
        public_domain_only: bool,
        filters: list[str] | None,
        page: int,
        per_page: int,
    ) -> Any:
        params: dict[str, Any] = {"q": query, "page": page, "per_page": per_page}
        if field is not None:
            params["field"] = field
        if public_domain_only:
            params["publicDomainOnly"] = "true"
        if filters:
            params["filter[]"] = filters
        return await self._get("items/search", params)

    async def list_collections(self, *, query: str | None, search_recursive: bool, page: int, per_page: int) -> Any:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if query is not None:
            params["q"] = query
        if search_recursive:
            params["search_recursive"] = "true"
        return await self._get("collections", params)

    async def browse_collection(self, *, uuid: str, view: CollectionView, page: int, per_page: int) -> Any:
        suffix = {"children": "", "subcollections": "/subcollections", "items": "/items"}[view]
        return await self._get(f"collections/{require_uuid(uuid)}{suffix}", {"page": page, "per_page": per_page})

    async def get_item(self, uuid: str) -> Any:
        return await self._get(f"items/{require_uuid(uuid)}", None)

    async def get_captures(self, *, uuid: str, include_mods: bool, page: int, per_page: int) -> Any:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if not include_mods:
            params["show_mods"] = "no"
        return await self._get(f"items/mods_captures/{require_uuid(uuid)}", params)

    async def get_capture_details(self, *, uuid: str, include_mods: bool) -> Any:
        params = None if include_mods else {"show_mods": "no"}
        return await self._get(f"items/item_details/{require_uuid(uuid)}", params)

    async def get_mods(self, uuid: str) -> Any:
        return await self._get(f"mods/{require_uuid(uuid)}", None)

    async def find_by_identifier(self, *, identifier_type: IdentifierType, value: str) -> Any:
        return await self._get(f"items/{identifier_type}/{require_identifier_value(value)}", None)

    async def get_rights(self, uuid: str) -> Any:
        return await self._get(f"items/rights/{require_uuid(uuid)}", None)

    async def get_plain_text(self, uuid: str) -> Any:
        return await self._get(f"items/plain_text/{require_uuid(uuid)}", None)

    async def get_recent_items(self) -> Any:
        return await self._get("items/recent", None)

    async def get_featured_items(self) -> Any:
        return await self._get("items/featured", None)

    async def get_total_items(self) -> Any:
        return await self._get("items/total", None)
