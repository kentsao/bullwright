from typing import Any

from bullwright_core import __version__ as core_version
from fastapi import APIRouter

from bullwright_api.settings import settings

router = APIRouter(tags=["meta"])

DISCLAIMER = "Bullwright is a research toy. Nothing here is investment advice."


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/version")
def version() -> dict[str, Any]:
    return {
        "git_sha": settings().git_sha,
        "core_version": core_version,
        "api_version": "v1",
        "disclaimer": DISCLAIMER,
    }
