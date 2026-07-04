"""Qlib 0.9.7 worker using exported PostgreSQL snapshots.

The worker owns no business database.  It reads immutable snapshots and writes
model artifacts below the shared QUANT_ARTIFACT_ROOT.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import qlib
from fastapi import FastAPI, HTTPException
from lightgbm import LGBMRegressor
from pydantic import BaseModel, Field
from qlib.contrib.data.handler import Alpha158
from qlib.constant import REG_US

ROOT=Path(os.getenv("QUANT_ARTIFACT_ROOT","/workspace/data/quant")).resolve()
app=FastAPI(title="finance-analysis qlib worker")


class TrainRequest(BaseModel):
    dataset_uri:str; model_key:str; model_version:str
    parameters:dict=Field(default_factory=dict); split_config:dict=Field(default_factory=dict); feature_config:dict=Field(default_factory=dict); target_config:dict=Field(default_factory=dict)


class PredictRequest(BaseModel):
    artifact_uri:str; dataset_uri:str|None=None; trade_date:str; universe:str


def path_for(uri:str)->Path:
    if not uri.startswith("quant://"): raise ValueError("artifact URI must use quant://")
    path=(ROOT/uri.removeprefix("quant://")).resolve()
    if path!=ROOT and ROOT not in path.parents: raise ValueError("artifact path traversal rejected")
    return path


def load_features(dataset:Path,manifest:dict,ablation:str="all_features")->pd.DataFrame:
    qlib.init(provider_uri=str(dataset),region=REG_US,kernels=1)
    handler=Alpha158(instruments="all",start_time=manifest["date_from"],end_time=manifest["date_to"],fit_start_time=manifest["date_from"],fit_end_time=manifest["date_to"])
    features=handler.fetch(col_set="feature")
    if list(features.index.names)==["instrument","datetime"]: features=features.swaplevel()
    features.index=features.index.set_names(["datetime","instrument"])
    features.columns=["_".join(map(str,column)) if isinstance(column,tuple) else str(column) for column in features.columns]
    custom=dataset/"source"/"custom_features.parquet"
    if custom.exists() and ablation!="base_only":
        extra=pd.read_parquet(custom).set_index(["datetime","instrument"])
        if ablation=="base_plus_relative_strength": extra=extra[[column for column in extra.columns if column.startswith("relative_")]]
        elif ablation=="base_plus_event": extra=extra[[column for column in extra.columns if column in {"event_score","negative_event_veto"}]]
        elif ablation!="all_features": raise ValueError(f"Unknown feature ablation: {ablation}")
        features=features.join(extra,how="left")
    return features.replace([np.inf,-np.inf],np.nan)


def labels(dataset:Path,manifest:dict)->pd.Series:
    bars=pd.read_csv(dataset/"source"/"daily.csv",parse_dates=["datetime"]).sort_values(["instrument","datetime"])
    mapping=manifest.get("sector_benchmark_mapping",{}); fallback=manifest["benchmark_codes"][0]
    grouped={code:frame.set_index("datetime") for code,frame in bars.groupby("instrument")}
    rows=[]
    for code,frame in grouped.items():
        if code in manifest["benchmark_codes"]: continue
        benchmark=grouped.get(mapping.get(code) or fallback)
        if benchmark is None: continue
        common=frame.index.intersection(benchmark.index); stock=frame.loc[common]; bench=benchmark.loc[common]
        value=((stock.close.shift(-5)/stock.open.shift(-1)-1)-(bench.close.shift(-5)/bench.open.shift(-1)-1))*100
        rows.extend((day,code,score) for day,score in value.items())
    result=pd.DataFrame(rows,columns=["datetime","instrument","label"]).set_index(["datetime","instrument"])["label"]
    return result


def split_dates(index:pd.MultiIndex,config:dict):
    dates=pd.DatetimeIndex(sorted(index.get_level_values("datetime").unique())); horizon=int(config.get("prediction_horizon",5)); embargo=int(config.get("embargo_days",2)); gap=horizon+embargo
    train_end=int(len(dates)*.6); valid_end=int(len(dates)*.8)
    return dates[:max(1,train_end-gap)],dates[min(len(dates),train_end+gap):max(train_end+gap+1,valid_end-gap)],dates[min(len(dates),valid_end+gap):]


def metrics(prediction:pd.DataFrame)->dict:
    clean=prediction.dropna(); daily=clean.groupby(level="datetime").apply(lambda x:x.prediction.corr(x.label,method="spearman"))
    top5=clean.groupby(level="datetime").apply(lambda x:x.nlargest(5,"prediction").label.mean()).mean()
    top10=clean.groupby(level="datetime").apply(lambda x:x.nlargest(10,"prediction").label.mean()).mean()
    ic=clean.prediction.corr(clean.label); rank_ic=clean.prediction.corr(clean.label,method="spearman")
    return {"ic":float(ic),"rank_ic":float(rank_ic),"rank_ic_mean":float(daily.mean()),"icir":float(daily.mean()/daily.std()) if daily.std() else None,
            "top5_excess_return_pct":float(top5),"top10_excess_return_pct":float(top10),"mae":float((clean.prediction-clean.label).abs().mean()),
            "rmse":float(np.sqrt(((clean.prediction-clean.label)**2).mean())),"hit_rate":float(((clean.prediction>0)==(clean.label>0)).mean())}


@app.get("/health")
def health(): return {"status":"available","qlib_version":qlib.__version__,"python":"3.12"}


@app.post("/train")
def train(request:TrainRequest):
    try:
        dataset=path_for(request.dataset_uri); manifest=json.loads((dataset/"manifest.json").read_text()); features=load_features(dataset,manifest,request.feature_config.get("ablation","all_features")); target=labels(dataset,manifest)
        panel=features.join(target.rename("label"),how="inner"); train_dates,valid_dates,test_dates=split_dates(panel.index,request.split_config)
        if not len(test_dates): raise ValueError("Dataset is too short for chronological train/valid/test split")
        train=panel[panel.index.get_level_values("datetime").isin(train_dates)].dropna(subset=["label"]); test=panel[panel.index.get_level_values("datetime").isin(test_dates)].dropna(subset=["label"])
        medians=train.drop(columns="label").median(); x_train=train.drop(columns="label").fillna(medians); x_test=test.drop(columns="label").fillna(medians)
        parameters={"n_estimators":300,"learning_rate":.03,"num_leaves":31,"verbosity":-1,"random_state":42,**request.parameters}
        model=LGBMRegressor(**parameters); model.fit(x_train,train.label)
        prediction=pd.DataFrame({"prediction":model.predict(x_test),"label":test.label},index=test.index); result_metrics=metrics(prediction)
        relative=f"models/{request.model_version}"; output=path_for(f"quant://{relative}"); output.mkdir(parents=True,exist_ok=True)
        joblib.dump({"model":model,"medians":medians,"columns":list(x_train.columns),"dataset_uri":request.dataset_uri},output/"model.joblib")
        prediction.to_parquet(output/"test_predictions.parquet"); (output/"metrics.json").write_text(json.dumps(result_metrics,indent=2))
        metadata={"model_key":request.model_key,"model_version":request.model_version,"dataset_uri":request.dataset_uri,"feature_config":request.feature_config,"target_config":request.target_config,"split_config":request.split_config,"qlib_version":qlib.__version__}
        (output/"metadata.json").write_text(json.dumps(metadata,indent=2)); data=(output/"model.joblib").read_bytes()
        importance=dict(sorted(zip(x_train.columns,map(float,model.feature_importances_)),key=lambda item:item[1],reverse=True)[:100])
        return {"metrics":result_metrics,"feature_importance":importance,"artifact_uri":f"quant://{relative}","artifact_digest":hashlib.sha256(data).hexdigest(),"artifact_size":len(data),"warnings":manifest.get("warnings",[])+["fixed observation universe; survivorship bias is present"]}
    except Exception as exc: raise HTTPException(422,str(exc)) from exc


@app.post("/predict")
def predict(request:PredictRequest):
    try:
        artifact=path_for(request.artifact_uri); bundle=joblib.load(artifact/"model.joblib"); dataset=path_for(request.dataset_uri or bundle["dataset_uri"]); manifest=json.loads((dataset/"manifest.json").read_text()); metadata=json.loads((artifact/"metadata.json").read_text()); features=load_features(dataset,manifest,metadata.get("feature_config",{}).get("ablation","all_features"))
        target_date=pd.Timestamp(request.trade_date); rows=features[features.index.get_level_values("datetime")==target_date].copy(); x=rows.reindex(columns=bundle["columns"]).fillna(bundle["medians"]); values=bundle["model"].predict(x)
        result=pd.DataFrame({"code":rows.index.get_level_values("instrument"),"raw_prediction":values}); result["normalized_score"]=result.raw_prediction.rank(pct=True); result["universe_rank"]=result.raw_prediction.rank(method="first",ascending=False).astype(int); result["predicted_return"]=result["raw_prediction"]
        # symbol_id is deliberately not guessed; main application must map canonical codes.
        return {"predictions":result.to_dict("records"),"trade_date":request.trade_date}
    except Exception as exc: raise HTTPException(422,str(exc)) from exc
