from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.pipeline import run_pipeline

app = FastAPI(title="YouTube Shorts Pipeline", version="1.0.0")


class PipelineRequest(BaseModel):
    topic: str | None = None
    upload: bool = True


class PipelineResponse(BaseModel):
    title: str
    video_path: str
    run_dir: str
    youtube_url: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/pipeline/run", response_model=PipelineResponse)
def trigger_pipeline(request: PipelineRequest):
    try:
        result = run_pipeline(topic=request.topic, upload=request.upload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not Path(result["video_path"]).exists():
        raise HTTPException(status_code=500, detail="Pipeline finished but video file is missing.")

    return PipelineResponse(**result)
