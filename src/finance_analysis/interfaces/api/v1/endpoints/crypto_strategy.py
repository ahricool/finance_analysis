from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from finance_analysis.crypto_strategy.service import overview, switch
from finance_analysis.interfaces.api.deps import private_no_store, require_admin

router = APIRouter(dependencies=[Depends(require_admin), Depends(private_no_store)])


class Selection(BaseModel):
    strategy: str


@router.get("")
def catalog():
    return overview()


@router.put("/{environment}", status_code=204)
def select_strategy(environment: Literal["paper", "live"], payload: Selection, user=Depends(require_admin)):
    try:
        switch(environment, payload.strategy, user.id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
