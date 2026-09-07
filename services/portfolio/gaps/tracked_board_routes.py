"""CRUD for tracked boards (API-backed ATS sources + career-page URLs).

Reads are `cv:read`-scoped; writes are admin-gated, since the tracked-board
list controls what the scheduled refresh polls.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from services.portfolio.constants import API_V1_PREFIX
from services.portfolio.dependencies import get_tracked_board_service
from services.portfolio.gaps.tracked_board import TrackedBoard
from services.portfolio.gaps.tracked_board_service import (
    TrackedBoardService,
    TrackedBoardValidationError,
)
from services.portfolio.schemas.tracked_boards import (
    TrackedBoardCreate,
    TrackedBoardUpdate,
)


router = APIRouter(prefix=f"{API_V1_PREFIX}/tracked-boards", tags=["tracked-boards"])

get_tracked_board_service_dep = Depends(get_tracked_board_service)


@router.get("", response_model=list[TrackedBoard])
async def list_tracked_boards(
    active_only: bool = False,
    group: str | None = None,
    service: TrackedBoardService = get_tracked_board_service_dep,
) -> list[TrackedBoard]:
    """List tracked boards. `?active_only=true` excludes soft-disabled ones;
    `?group=X` narrows to that group (omit for every group)."""
    rows = await service.list_all(active_only=active_only, group=group)
    return [row.to_domain() for row in rows]


@router.post("", response_model=TrackedBoard, status_code=201)
async def create_tracked_board(
    payload: TrackedBoardCreate,
    service: TrackedBoardService = get_tracked_board_service_dep,
) -> TrackedBoard:
    """Track a new board. Validated against its `kind`'s required fields."""
    try:
        row = await service.create(
            kind=payload.kind,
            company_name=payload.company_name,
            company_slug=payload.company_slug,
            url=payload.url,
            notes=payload.notes,
            group=payload.group,
        )
    except TrackedBoardValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return row.to_domain()


@router.get("/{board_id}", response_model=TrackedBoard)
async def read_tracked_board(
    board_id: int,
    service: TrackedBoardService = get_tracked_board_service_dep,
) -> TrackedBoard:
    """Read one tracked board."""
    row = await service.get(board_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Tracked board not found")
    return row.to_domain()


@router.patch("/{board_id}", response_model=TrackedBoard)
async def update_tracked_board(
    board_id: int,
    payload: TrackedBoardUpdate,
    service: TrackedBoardService = get_tracked_board_service_dep,
) -> TrackedBoard:
    """Partially update a board (any subset of fields, `kind` excepted —
    it's immutable; switch kinds via delete + re-create)."""
    fields = payload.model_dump(exclude_unset=True)
    row = await service.update(board_id, fields)
    if row is None:
        raise HTTPException(status_code=404, detail="Tracked board not found")
    return row.to_domain()


@router.delete("/{board_id}", status_code=204)
async def delete_tracked_board(
    board_id: int,
    service: TrackedBoardService = get_tracked_board_service_dep,
) -> None:
    """Permanently remove a tracked board."""
    deleted = await service.delete(board_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tracked board not found")
