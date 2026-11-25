"""Document repository — port (Protocol) for api-core without DB.

In the DB-backed version, this module also contains the SqlAlchemyDocumentRepository
concrete adapter. For api-core without DB, we only need the Protocol.
"""

from __future__ import annotations

from typing import Any, Protocol


class DocumentRepository(Protocol):
    async def get(self, kind: str, *, tenant_id: int) -> dict[str, Any] | None: ...
    async def put(
        self, *, kind: str, payload: dict[str, Any], tenant_id: int
    ) -> dict[str, Any]: ...
    async def list_all(self, *, tenant_id: int) -> list[dict[str, Any]]: ...
    async def delete(self, kind: str, *, tenant_id: int) -> bool: ...
    async def list_kinds(self, *, tenant_id: int) -> list[str]: ...
