"""
FastAPI app: routes, SSE streaming, background tasks.
"""

import os
import uuid
import queue
import threading
from typing import Generator

from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import mun_guidelines
import research
import llm
import docx_writer

BASE_DIR = os.path.dirname(__file__)
GENERATED_DIR = os.path.join(BASE_DIR, "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)

app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# job_id → queue of SSE message strings
_job_queues: dict[str, queue.Queue] = {}


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    threading.Thread(target=mun_guidelines.load_guidelines, daemon=True).start()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    topic: str
    country: str
    committee: str = ""
    pages: int = 2


class GenerateResponse(BaseModel):
    job_id: str


# ---------------------------------------------------------------------------
# Background pipeline
# ---------------------------------------------------------------------------

def _run_pipeline(job_id: str, req: GenerateRequest):
    q = _job_queues[job_id]

    def emit(msg: str):
        q.put(f"data: {msg}\n\n")

    try:
        # Step 1: Research
        emit("[1/5] Searching the web for research sources…")
        sources = research.gather_research(req.topic, req.country)
        emit(f"[1/5] Found {len(sources)} sources.")

        # Steps 2–4 happen inside llm.generate_paper
        paper_text = llm.generate_paper(
            topic=req.topic,
            country=req.country,
            committee=req.committee,
            pages=req.pages,
            sources=sources,
            progress_cb=emit,
        )

        # Step 5: Write .docx
        emit("[5/5] Writing .docx file…")
        output_path = os.path.join(GENERATED_DIR, f"{job_id}.docx")
        docx_writer.write_docx(paper_text, output_path)

        emit(f"done: /download/{job_id}")
    except Exception as e:
        emit(f"error: {e}")
    finally:
        q.put(None)  # sentinel


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    _job_queues[job_id] = queue.Queue()
    background_tasks.add_task(_run_pipeline, job_id, req)
    return GenerateResponse(job_id=job_id)


@app.get("/progress/{job_id}")
async def progress(job_id: str):
    if job_id not in _job_queues:
        return StreamingResponse(
            iter(["data: error: unknown job\n\n"]),
            media_type="text/event-stream",
        )

    def event_stream() -> Generator[str, None, None]:
        q = _job_queues[job_id]
        while True:
            msg = q.get()
            if msg is None:
                break
            yield msg

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/download/{job_id}")
async def download(job_id: str):
    path = os.path.join(GENERATED_DIR, f"{job_id}.docx")
    if not os.path.exists(path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="position_paper.docx",
    )
