"""FastMCP server exposing the NYPL Digital Collections Repo API (v2) as task-shaped tools."""

import os
import sys
from typing import Annotated, Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from nypl_api_bridge.api import CollectionView, IdentifierType, NyplApi, build_http_client
from nypl_api_bridge.logs import configure_logging

INSTRUCTIONS = """\
Tools for the New York Public Library Digital Collections (Repo API v2).

Data model: collection -> container(s) -> item -> capture. Captures are individual digitised
images/pages. Everything is addressed by UUID, and some tools only accept certain kinds:
- get_capture_details and get_plain_text need a *capture* UUID.
- get_item does NOT accept capture UUIDs.

Typical flow: search_items or list_collections to find UUIDs, then browse_collection /
get_item / get_captures to drill down, and get_rights before suggesting reuse of an image.
Use public_domain_only=True when the user wants images they can reuse; only those results
include image links. Results are paginated (page starts at 1).
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)

Uuid = Annotated[str, Field(description="NYPL UUID, e.g. 510d47da-...-a3d9-e040-e00a18064a99")]
Page = Annotated[int, Field(ge=1, description="1-based page number")]
PerPage = Annotated[int, Field(ge=1, le=100, description="Results per page (API max is 500; capped at 100 here)")]


def create_server(api: NyplApi) -> FastMCP:
    mcp = FastMCP("NYPL Digital Collections", instructions=INSTRUCTIONS)

    @mcp.tool(annotations=READ_ONLY)
    async def search_items(
        query: Annotated[str, Field(description="Keywords to search across item metadata (MODS)")],
        field: Annotated[
            str | None, Field(description="Restrict the search to one MODS field, e.g. 'title', 'topic', 'name'")
        ] = None,
        public_domain_only: Annotated[
            bool,
            Field(
                description="Only return items with no known US copyright restrictions (only these have image links)"
            ),
        ] = False,
        filters: Annotated[
            list[str] | None,
            Field(description="Facet filters as 'field:value', e.g. ['typeOfResource:still image']"),
        ] = None,
        page: Page = 1,
        per_page: PerPage = 10,
    ) -> Any:
        """Keyword search over digitised items. Returns uuid, title, imageID and itemLink per hit."""
        return await api.search_items(
            query=query,
            field=field,
            public_domain_only=public_domain_only,
            filters=filters,
            page=page,
            per_page=per_page,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_collections(
        query: Annotated[str | None, Field(description="Match against collection/container titles")] = None,
        search_recursive: Annotated[bool, Field(description="Also search mid-level container titles")] = False,
        page: Page = 1,
        per_page: PerPage = 10,
    ) -> Any:
        """List or search top-level collections. Returns uuid, title and numItems for each."""
        return await api.list_collections(query=query, search_recursive=search_recursive, page=page, per_page=per_page)

    @mcp.tool(annotations=READ_ONLY)
    async def browse_collection(
        uuid: Uuid,
        view: Annotated[
            CollectionView,
            Field(
                description="children: all direct children; subcollections: child containers only; items: items only"
            ),
        ] = "children",
        page: Page = 1,
        per_page: PerPage = 10,
    ) -> Any:
        """Walk down the hierarchy of a collection or container."""
        return await api.browse_collection(uuid=uuid, view=view, page=page, per_page=per_page)

    @mcp.tool(annotations=READ_ONLY)
    async def get_item(uuid: Uuid) -> Any:
        """Summary of an item, container or collection (not a capture): title, imageID, itemLink."""
        return await api.get_item(uuid)

    @mcp.tool(annotations=READ_ONLY)
    async def get_captures(
        uuid: Uuid,
        include_mods: Annotated[bool, Field(description="Include the full MODS record (verbose)")] = False,
        page: Page = 1,
        per_page: PerPage = 10,
    ) -> Any:
        """List the captures (digitised images/pages) under any collection, container, item or capture UUID."""
        return await api.get_captures(uuid=uuid, include_mods=include_mods, page=page, per_page=per_page)

    @mcp.tool(annotations=READ_ONLY)
    async def get_capture_details(
        uuid: Annotated[str, Field(description="A *capture* UUID")],
        include_mods: Annotated[bool, Field(description="Include the full MODS record (verbose)")] = False,
    ) -> Any:
        """Details for one capture, including image links (public-domain only) and sibling captures."""
        return await api.get_capture_details(uuid=uuid, include_mods=include_mods)

    @mcp.tool(annotations=READ_ONLY)
    async def get_mods(uuid: Uuid) -> Any:
        """Full bibliographic (MODS) metadata for any capture, item, container or collection UUID."""
        return await api.get_mods(uuid)

    @mcp.tool(annotations=READ_ONLY)
    async def find_by_identifier(
        identifier_type: Annotated[IdentifierType, Field(description="Kind of identifier you have")],
        value: Annotated[str, Field(description="The identifier value, e.g. '1666689' for a local_image_id")],
    ) -> Any:
        """Resolve a non-UUID identifier (image ID, b-number, barcode, OCLC, ISBN, ...) to NYPL UUIDs."""
        return await api.find_by_identifier(identifier_type=identifier_type, value=value)

    @mcp.tool(annotations=READ_ONLY)
    async def get_rights(uuid: Uuid) -> Any:
        """Rights / use statement for a UUID. Check this before recommending reuse of an image."""
        return await api.get_rights(uuid)

    @mcp.tool(annotations=READ_ONLY)
    async def get_plain_text(uuid: Annotated[str, Field(description="A *capture* UUID")]) -> Any:
        """OCR plain text for a capture (books, letters, newspapers...), where available."""
        return await api.get_plain_text(uuid)

    @mcp.tool(annotations=READ_ONLY)
    async def get_recent_items() -> Any:
        """Most recently added captures."""
        return await api.get_recent_items()

    @mcp.tool(annotations=READ_ONLY)
    async def get_featured_items() -> Any:
        """Items currently featured by NYPL."""
        return await api.get_featured_items()

    @mcp.tool(annotations=READ_ONLY)
    async def get_total_items() -> Any:
        """Total number of digitised items in NYPL Digital Collections."""
        return await api.get_total_items()

    return mcp


def main() -> None:
    token = os.environ.get("NYPL_API_TOKEN", "")
    if not token:
        print(
            "NYPL_API_TOKEN is not set. Get a token at https://api.repo.nypl.org/sign_up",
            file=sys.stderr,
        )
        raise SystemExit(1)
    configure_logging()  # stderr + file only: stdout carries the MCP stdio protocol
    create_server(NyplApi(build_http_client(token, transport=None))).run()


if __name__ == "__main__":
    main()
