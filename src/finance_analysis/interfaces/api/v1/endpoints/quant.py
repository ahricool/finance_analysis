"""Authenticated quant research API; Qlib internals are never exposed."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder

from finance_analysis.database.models.user import User
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.quant import DatasetBuildRequest, EventCreateRequest, EventImportRequest, IntradayRunRequest, ModelRunCreateRequest, PublishRequest
from finance_analysis.quant.capabilities import get_quant_capabilities
from finance_analysis.quant.events.import_service import EventImportService
from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS

router=APIRouter()


def encoded(value): return jsonable_encoder(value)


@router.get("/capabilities")
async def capabilities(_:User=Depends(require_current_user)): return get_quant_capabilities()


@router.get("/universes")
async def universes(market:str|None=None,_:User=Depends(require_current_user)):
    repo=QuantRepository(); rows=[]
    for item in repo.list_universes(market):
        members=repo.active_members(item.id,date.today()); rows.append({**encoded(item),"member_count":len(members),"members":[{"code":symbol.code,"sector_key":member.sector_key,"sector_benchmark_code":member.sector_benchmark_code,"effective_from":member.effective_from,"effective_to":member.effective_to} for member,symbol in members]})
    return rows


@router.get("/models/definitions")
async def model_definitions(_:User=Depends(require_current_user)): return encoded(QuantRepository().list_model_definitions())


@router.get("/models")
async def models(_:User=Depends(require_current_user)): return encoded(QuantRepository().list_model_runs())


@router.get("/datasets")
async def datasets(_:User=Depends(require_current_user)): return encoded(QuantRepository().list_datasets())


@router.get("/datasets/{snapshot_id}")
async def dataset(snapshot_id:int,_:User=Depends(require_current_user)):
    row=QuantRepository().get_dataset(snapshot_id)
    if not row: raise HTTPException(404,"Dataset snapshot not found")
    return encoded(row)


@router.post("/datasets/build",status_code=status.HTTP_202_ACCEPTED)
async def build_dataset(body:DatasetBuildRequest,user:User=Depends(require_admin)):
    from finance_analysis.tasks.celery.jobs.quant_dataset.tasks import build_quant_dataset
    result=build_quant_dataset.apply_async(kwargs={"market":body.market.upper(),"universe":body.universe,"date_from":str(body.date_from),"date_to":str(body.date_to),"owner_uid":user.id},queue=QUEUE_ANALYSIS)
    return {"task_id":result.id,"status":"pending"}


@router.get("/market-regime/latest")
async def latest_market_regime(market:str="US",_:User=Depends(require_current_user)):
    rows=QuantRepository().market_regimes(market.upper(),limit=1)
    if not rows: raise HTTPException(404,"Market regime not available")
    return encoded(rows[0])


@router.get("/market-regime/history")
async def market_regime_history(market:str="US",date_from:date|None=None,date_to:date|None=None,model_version:str|None=None,_:User=Depends(require_current_user)):
    rows=QuantRepository().market_regimes(market.upper(),date_from,date_to)
    if model_version: rows=[row for row in rows if row.model_version==model_version]
    return encoded(rows)


@router.get("/sectors/ranking")
async def sector_ranking(market:str="US",trade_date:date|None=None,_:User=Depends(require_current_user)): return encoded(QuantRepository().sector_regimes(market.upper(),trade_date))


@router.get("/sectors/{sector_key}")
async def sector_detail(sector_key:str,market:str="US",_:User=Depends(require_current_user)): return encoded(QuantRepository().sector_regimes(market.upper(),sector_key=sector_key))


@router.get("/events")
async def events(market:str|None=None,code:str|None=None,event_type:str|None=None,direction:str|None=None,source:str|None=None,published_from:datetime|None=None,published_to:datetime|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=200),_:User=Depends(require_current_user)):
    rows,total=QuantRepository().list_events({"market":market.upper() if market else None,"code":code.upper() if code else None,"event_type":event_type,"direction":direction,"source":source,"published_from":published_from,"published_to":published_to},(page-1)*page_size,page_size)
    return {"items":encoded(rows),"total":total,"page":page,"page_size":page_size}


@router.get("/events/{event_id}")
async def event(event_id:int,_:User=Depends(require_current_user)):
    row=QuantRepository().get_event(event_id)
    if not row: raise HTTPException(404,"Event not found")
    return encoded(row)


@router.post("/events")
async def create_event(body:EventCreateRequest,_:User=Depends(require_admin)):
    result=EventImportService().import_json([body.model_dump()])
    if result["errors"]: raise HTTPException(400,result["errors"])
    return result


@router.post("/events/import")
async def import_events(body:EventImportRequest,_:User=Depends(require_admin)):
    if body.format=="json": return EventImportService().import_json(body.items)
    if body.format=="csv" and body.csv_content is not None: return EventImportService().import_csv(body.csv_content)
    raise HTTPException(400,"format must be json or csv with csv_content")


@router.post("/model-runs",status_code=status.HTTP_202_ACCEPTED)
async def create_model_run(body:ModelRunCreateRequest,user:User=Depends(require_admin)):
    repo=QuantRepository(); definition=repo.get_model_definition(body.model_key); universe=repo.get_universe(body.universe); dataset=repo.get_dataset(body.dataset_snapshot_id)
    if not definition or not universe or not dataset: raise HTTPException(400,"Unknown model, universe, or dataset")
    if dataset.status!="ready": raise HTTPException(409,"Dataset is not ready")
    values=body.model_dump(exclude={"universe"}); values.update({"uid":user.id,"model_definition_id":definition.id,"universe_id":universe.id,"status":"draft","progress":0})
    run=repo.create_model_run(values)
    from finance_analysis.tasks.celery.jobs.quant_training.tasks import train_quant_model
    task=train_quant_model.apply_async(kwargs={"model_run_id":run.id,"owner_uid":user.id},queue=QUEUE_ANALYSIS); repo.update_model_run(run.id,task_id=task.id)
    return {"model_run_id":run.id,"task_id":task.id,"status":"draft"}


@router.get("/model-runs")
async def model_runs(_:User=Depends(require_current_user)): return encoded(QuantRepository().list_model_runs())


@router.get("/model-runs/{run_id}")
async def model_run(run_id:int,_:User=Depends(require_current_user)):
    row=QuantRepository().get_model_run(run_id)
    if not row: raise HTTPException(404,"Model run not found")
    return encoded(row)


@router.post("/model-runs/{run_id}/publish")
async def publish_model(run_id:int,body:PublishRequest,user:User=Depends(require_admin)):
    try: return encoded(QuantRepository().publish_model(run_id,user.id,body.reason))
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc


@router.get("/signals/latest")
@router.get("/signals/ranking")
async def signals(market:str="US",universe:str|None=None,_:User=Depends(require_current_user)):
    repo=QuantRepository(); definition=repo.get_universe(universe) if universe else None; rows=repo.latest_signals(market.upper(),definition.id if definition else None)
    regimes=repo.market_regimes(market.upper(),date_from=rows[0].trade_date,date_to=rows[0].trade_date,limit=1) if rows else []
    return {"trade_date":rows[0].trade_date if rows else None,"market":market.upper(),"universe":universe,"market_regime":regimes[0].regime if regimes else None,"max_equity_exposure":regimes[0].max_equity_exposure if regimes else None,"items":encoded(rows)}


@router.get("/signals/{code}")
async def signal(code:str,_:User=Depends(require_current_user)):
    suffix=code.upper().rsplit(".",1)[-1]; market="CN" if suffix in {"SH","SZ"} else suffix if suffix in {"US","HK"} else "US"
    rows=QuantRepository().latest_signals(market,code=code)
    if not rows: raise HTTPException(404,"Signal not found")
    return encoded(rows[0])


@router.get("/signals/{code}/history")
async def signal_history(code:str,_:User=Depends(require_current_user)): return encoded(QuantRepository().signal_history(code))


@router.get("/portfolios/latest")
async def latest_portfolio(market:str="US",universe:str|None=None,_:User=Depends(require_current_user)):
    repo=QuantRepository(); definition=repo.get_universe(universe) if universe else None; rows=repo.latest_portfolios(market.upper(),definition.id if definition else None,1)
    if not rows: raise HTTPException(404,"Portfolio recommendation not found")
    row,items=repo.portfolio(rows[0].id); return {**encoded(row),"items":encoded(items)}


@router.get("/portfolios")
async def portfolios(market:str="US",_:User=Depends(require_current_user)): return encoded(QuantRepository().latest_portfolios(market.upper()))


@router.get("/portfolios/{recommendation_id}")
async def portfolio(recommendation_id:int,_:User=Depends(require_current_user)):
    result=QuantRepository().portfolio(recommendation_id)
    if not result: raise HTTPException(404,"Portfolio recommendation not found")
    row,items=result; return {**encoded(row),"items":encoded(items)}


@router.get("/intraday-confirmations")
async def confirmations(trade_date:date|None=None,_:User=Depends(require_current_user)): return encoded(QuantRepository().confirmations(trade_date))


@router.get("/intraday-confirmations/{code}")
async def confirmation(code:str,_:User=Depends(require_current_user)): return encoded(QuantRepository().confirmations(code=code))


@router.post("/intraday-confirmations/run")
async def run_confirmation(body:IntradayRunRequest,_:User=Depends(require_admin)):
    from finance_analysis.quant.intraday_confirmation.runner import IntradayConfirmationRunner
    return IntradayConfirmationRunner().run(body.trade_date or date.today())
