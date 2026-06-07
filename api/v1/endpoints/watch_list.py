# -*- coding: utf-8 -*-
"""
===================================
自选股接口 (watch_list)
===================================

1. GET    /api/v1/watch-list          — 获取自选股列表
2. POST   /api/v1/watch-list          — 添加自选股
3. PUT    /api/v1/watch-list/{id}     — 更新自选股
4. DELETE /api/v1/watch-list/{id}     — 删除自选股
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from api.deps import get_effective_user_uid
from api.v1.schemas.watch_list import (
    WatchListItemCreate,
    WatchListItemResponse,
    WatchListItemUpdate,
    WatchListResponse,
)
from src.repositories.watch_list_repo import WatchListRepo

logger = logging.getLogger(__name__)
router = APIRouter()


def _repo() -> WatchListRepo:
    return WatchListRepo()


@router.get("", response_model=WatchListResponse, summary="获取自选股列表")
def list_watch_list(http_request: Request):
    uid = get_effective_user_uid(http_request)
    items = _repo().list_all(uid=uid)
    return WatchListResponse(
        items=[WatchListItemResponse.model_validate(i) for i in items],
        total=len(items),
    )


@router.post("", response_model=WatchListItemResponse, status_code=201, summary="添加自选股")
def create_watch_list_item(http_request: Request, body: WatchListItemCreate):
    uid = get_effective_user_uid(http_request)
    repo = _repo()
    if repo.get_by_code(body.code, uid=uid):
        raise HTTPException(status_code=409, detail=f"股票 {body.code} 已在自选股中")
    try:
        item = repo.create(
            uid=uid,
            code=body.code,
            name=body.name,
            notes=body.notes,
            market_type=body.market_type,
            is_favorite=body.is_favorite,
        )
    except Exception as e:
        logger.error("创建自选股失败: %s", e)
        raise HTTPException(status_code=500, detail="创建失败，请重试") from e
    return WatchListItemResponse.model_validate(item)


@router.put("/{item_id}", response_model=WatchListItemResponse, summary="更新自选股")
def update_watch_list_item(http_request: Request, item_id: int, body: WatchListItemUpdate):
    uid = get_effective_user_uid(http_request)
    item = _repo().update(
        item_id=item_id,
        uid=uid,
        name=body.name,
        notes=body.notes,
        market_type=body.market_type,
        is_favorite=body.is_favorite,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="未找到该自选股")
    return WatchListItemResponse.model_validate(item)


@router.delete("/{item_id}", status_code=204, summary="删除自选股")
def delete_watch_list_item(http_request: Request, item_id: int):
    uid = get_effective_user_uid(http_request)
    deleted = _repo().delete(item_id, uid=uid)
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到该自选股")
