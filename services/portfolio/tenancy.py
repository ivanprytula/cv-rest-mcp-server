"""The tenant a request acts on.

`TenantId` is a distinct type, not an alias, so a plain `int` cannot be
passed where a tenant is expected. That matters because the ids in this
codebase are interchangeable at runtime and catastrophic to confuse: a
posting id or a document id transposed into a tenant argument reads another
tenant's CV and returns it as a complete, plausible answer. The type checker
rejects that at the call site instead.

Only two places construct one — the `uid` claim of a verified access token,
and the operator lookup that install-wide jobs use — so `TenantId(...)`
appearing anywhere else is worth a second look in review.

At runtime this *is* an `int`: `NewType` erases, so SQLAlchemy binding,
Pydantic models and the row-level-security parameter keep working with no
conversion.
"""

from __future__ import annotations

from typing import NewType


TenantId = NewType("TenantId", int)
