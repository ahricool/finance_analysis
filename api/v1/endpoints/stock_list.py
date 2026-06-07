# -*- coding: utf-8 -*-
"""
===================================
持仓股接口 (stock_list)
===================================

1. GET    /api/v1/stock-list          — 获取持仓股列表
2. POST   /api/v1/stock-list          — 添加持仓股
3. PUT    /api/v1/stock-list/{id}     — 更新持仓股（含数量）
4. DELETE /api/v1/stock-list/{id}     — 删除持仓股
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from api.deps import get_effective_uid
from api.v1.schemas.stock_list import (
    StockHoldingCreate,
    StockHoldingResponse,
    StockHoldingUpdate,
    StockListResponse,
)
from src.repositories.stock_list_repo import StockListRepo

logger = logging.getLogger(__name__)
router = APIRouter()


def _repo() -> StockListRepo:
    return StockListRepo()


@router.get("", response_model=StockListResponse, summary="获取持仓股列表")
def list_stock_list(http_request: Request):
    uid = get_effective_uid(http_request)
    items = _repo().list_all(uid=uid)
    return StockListResponse(
        items=[StockHoldingResponse.model_validate(i) for i in items],
        total=len(items),
    )


@router.post("", response_model=StockHoldingResponse, status_code=201, summary="添加持仓股")
def create_stock_holding(http_request: Request, body: StockHoldingCreate):
    uid = get_effective_uid(http_request)
    repo = _repo()
    if repo.get_by_code(body.code, uid=uid):
        raise HTTPException(status_code=409, detail=f"股票 {body.code} 已在持仓股中")
    try:
        item = repo.create(
            uid=uid,
            code=body.code,
            name=body.name,
            quantity=body.quantity,
            market_type=body.market_type,
            notes=body.notes,
        )
    except Exception as e:
        logger.error("创建持仓股失败: %s", e)
        raise HTTPException(status_code=500, detail="创建失败，请重试") from e
    return StockHoldingResponse.model_validate(item)


@router.put("/{item_id}", response_model=StockHoldingResponse, summary="更新持仓股")
def update_stock_holding(http_request: Request, item_id: int, body: StockHoldingUpdate):
    uid = get_effective_uid(http_request)
    item = _repo().update(
        item_id,
        uid=uid,
        name=body.name,
        quantity=body.quantity,
        market_type=body.market_type,
        notes=body.notes,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="未找到该持仓股")
    return StockHoldingResponse.model_validate(item)


@router.delete("/{item_id}", status_code=204, summary="删除持仓股")
def delete_stock_holding(http_request: Request, item_id: int):
    uid = get_effective_uid(http_request)
    deleted = _repo().delete(item_id, uid=uid)
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到该持仓股")
