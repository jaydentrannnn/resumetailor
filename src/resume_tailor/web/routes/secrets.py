"""`/api/secrets`: save, check and remove API keys without ever sending one back.

Values are write-only: responses say whether a key is set and where it comes from
(`.env` wins over a saved key, see `config.credential`), never the key itself.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.infra import secret_store

router = APIRouter()


class SecretState(BaseModel):
    name: str
    set: bool
    #: "env" (from `.env`/the environment), "saved" (secret store), or None.
    source: str | None = None


class SecretsResponse(BaseModel):
    backend: str
    secrets: list[SecretState]


class SecretWrite(BaseModel):
    value: str = Field(min_length=1, max_length=4096)


def _state(name: str) -> SecretState:
    if os.environ.get(name):
        return SecretState(name=name, set=True, source="env")
    try:
        saved = bool(secret_store.get(f"api_key:{name}"))
    except secret_store.SecretStoreError:
        saved = False
    return SecretState(name=name, set=saved, source="saved" if saved else None)


def _check_name(name: str) -> None:
    if name not in config.SAVABLE_CREDENTIALS:
        raise HTTPException(status_code=404, detail=f"Unknown secret {name!r}.")


@router.get("/api/secrets", response_model=SecretsResponse)
def list_secrets() -> SecretsResponse:
    """Which API keys are set, and whether from the environment or saved in the app."""
    return SecretsResponse(
        backend=secret_store.backend().name,
        secrets=[_state(name) for name in config.SAVABLE_CREDENTIALS],
    )


@router.put("/api/secrets/{name}", response_model=SecretState)
def put_secret(name: str, body: SecretWrite) -> SecretState:
    """Save an API key in the OS keychain (or the encrypted fallback file)."""
    _check_name(name)
    try:
        secret_store.set(f"api_key:{name}", body.value.strip())
    except secret_store.SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _state(name)


@router.delete("/api/secrets/{name}", response_model=SecretState)
def delete_secret(name: str) -> SecretState:
    """Forget a saved API key. A key set in `.env` is untouched and still reported."""
    _check_name(name)
    try:
        secret_store.delete(f"api_key:{name}")
    except secret_store.SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _state(name)
