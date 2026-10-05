"""The logos to pick from: the names of both collections, and each picture fetched by nexsift for the picker."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from ..deps import CurrentAccount
from ..meldungen import fehler
from ..services import icons

router = APIRouter(prefix="/api/icons", tags=["icons"])


@router.get("", summary="Every logo of dashboard-icons and selfh.st")
async def names(account: CurrentAccount) -> list[dict[str, str]]:
    return await icons.all_names()


@router.get("/batch", summary="Several logos at once, as data addresses, for the picker")
async def batch(
    account: CurrentAccount, icon: Annotated[list[str], Query(max_length=icons.BATCH_MAX)]
) -> dict[str, str]:
    """One answer for a screenful of tiles. A browser sends six requests to one server at a time, and each logo
    nexsift has not seen yet is a trip to GitHub: one by one, the first look at the picker took twelve seconds
    (05.10.2026). nexsift fetches these side by side instead. Logos it cannot get are left out."""
    return await icons.fetch_many(icon)


@router.get("/{collection}/{name}.png", summary="One logo, for the picker", response_class=Response)
async def picture(collection: str, name: str, account: CurrentAccount) -> Response:
    try:
        icon = icons.normalize(f"{collection}/{name}")
    except icons.IconError as error:
        raise fehler("not_found", "No such icon.", 404) from error
    found = await icons.fetch(icon)
    if found is None:
        raise fehler("icon_unavailable", "The icon could not be loaded.", 404)
    data, kind = found
    return Response(data, media_type=kind, headers={"Cache-Control": "private, max-age=604800"})
