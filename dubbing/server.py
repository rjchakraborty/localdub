import asyncio
import fcntl
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .pipeline import read, save
from .settings import LANGUAGES, Options, home, options_for_job
from .sources import MAX_BYTES, public_url

ROOT = Path(__file__).resolve().parent
FILES = {"dubbed.wav", "dubbed.mp3", "translated.vtt", "report.json", "audit.json", "transcript.json", "translation.json", "source.wav"}
TOKEN = secrets.token_urlsafe(32)


def job_folder(job_id):
    try:
        normalized = str(uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(404, "Job not found")
    folder = home() / "jobs" / normalized
    if not (folder / "job.json").exists():
        raise HTTPException(404, "Job not found")
    return folder


def view(folder):
    job = read(folder / "job.json")
    source = read(folder/"source.json") if (folder/"source.json").exists() else {}
    progress = read(folder / "progress.json") if (folder / "progress.json").exists() else {}
    qa = read(folder/"audit.json") if (folder/"audit.json").exists() else None
    return {**job,"title":source.get("title"), "qa": {"passed":qa["passed"],"checks":qa["checks"],"status":qa["status"]} if qa else None,"progress": progress, "files": sorted(p.name for p in folder.iterdir() if p.name in FILES and (job["status"] in {"completed","needs_review"} or p.name not in {"dubbed.wav", "dubbed.mp3", "translated.vtt", "report.json"}))}


class Queue:
    def __init__(self):
        self.process = None
        self.active = None
        self.task = None

    async def work(self):
        while True:
            folders = sorted((home() / "jobs").glob("*/job.json"), key=lambda p: p.stat().st_mtime)
            for job_path in folders:
                job = read(job_path)
                if job["status"] != "queued":
                    continue
                from .batches import runnable
                if not runnable(job):
                    continue
                folder = job_path.parent
                self.active = job["id"]
                job.update(status="running", error=None)
                save(job_path, job)
                try:
                    with (folder / "worker.log").open("a") as log:
                        self.process = subprocess.Popen([sys.executable, "-u", "-m", "dubbing.pipeline", str(folder)], stdout=log, stderr=log, start_new_session=True)
                        while self.process.poll() is None:
                            await asyncio.sleep(0.5)
                    if (folder / "cancel").exists():
                        job.update(status="cancelled", error="Cancelled; resume retains completed stages")
                    elif self.process.returncode:
                        job.update(status="failed", error=(folder / "worker.log").read_text()[-2200:])
                    else:
                        audit = read(folder/"audit.json") if (folder/"audit.json").exists() else {}
                        job.update(status="needs_review" if audit.get("status")=="listening_review_required" else "completed", finished=time.time())
                except Exception as exc:
                    job.update(status="failed", error=str(exc))
                finally:
                    save(job_path, job)
                    self.active = self.process = None
                if (os.environ.get('DUBBING_DESKTOP_WORKSPACE') or job.get('batch_id')) and job['status'] in {'completed','needs_review'}:
                    from .exports import export_job
                    try:
                        exported=await asyncio.to_thread(export_job,folder)
                        export_fields={'export_folder':exported['folder'],'export_error':None}
                    except (OSError,ValueError,KeyError) as exc:
                        export_fields={'export_error':'Audio is retained; export needs attention: '+str(exc)}
                    latest=read(job_path)
                    if latest['status']==job['status'] and latest.get('finished')==job.get('finished'):
                        latest.update(export_fields)
                        save(job_path,latest)
            await asyncio.sleep(1)


queue = Queue()


@asynccontextmanager
async def lifespan(app):
    root = home()
    (root / "jobs").mkdir(exist_ok=True)
    lock = (root / "server.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("Another dubbing server owns this data directory")
    for path in (root / "jobs").glob("*/job.json"):
        job = read(path)
        if job["status"] == "running":
            job.update(status="interrupted", error="Server stopped; resume explicitly")
            save(path, job)
    queue.task = asyncio.create_task(queue.work())
    try:
        yield
    finally:
        queue.task.cancel()
        if queue.process and queue.process.poll() is None:
            os.killpg(queue.process.pid, signal.SIGTERM)
            await asyncio.to_thread(queue.process.wait)
        lock.close()


app = FastAPI(title="LocalDub", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.headers.get("host", "")
    port = os.environ.get('DUBBING_DESKTOP_PORT','8092')
    if host not in {f"127.0.0.1:{port}", f"localhost:{port}", "testserver"}:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Invalid local host"}, status_code=403)
    if request.method not in {"GET", "HEAD"} and not secrets.compare_digest(request.headers.get("x-dubbing-token", ""), TOKEN):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Reload the local app before submitting"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "index.html").read_text()


@app.get("/api/config")
def config():
    ready=all(os.environ.get(name) and Path(os.environ[name]).exists() for name in ('DUBBING_INDEXTTS_PYTHON','DUBBING_INDEXTTS_MODEL','DUBBING_INDEXTTS_CAMPPLUS','INDEXTTS_W2V_BERT_DIR'))
    return {"languages": LANGUAGES, "token": TOKEN, "storage": str(home()), "engine": "Local · Whisper → Hy-MT2 translation → Qwen3-TTS / IndexTTS 2.5", "indextts25_available":ready,'preferences_available':True,'export_available':True}


@app.get("/api/jobs")
def jobs():
    return sorted([view(p.parent) for p in (home()/"jobs").glob("*/job.json")], key=lambda j: j["created"], reverse=True)


@app.get('/api/preferences')
def preferences():
    path=home()/'preferences.json'
    if path.exists():
        try:return {'options':Options.model_validate(read(path)).model_dump()}
        except (ValueError,TypeError):
            return {'options':Options(language='zh').model_dump(),'warning':'Saved settings are invalid; defaults loaded. Existing settings file is retained until you save new settings.'}
    return {'options':Options(language='zh').model_dump()}


@app.get('/api/integrations')
def integrations():
    from .integrations import load, installed
    config = load()
    return {'podbean':config.podbean, 'plugins':config.plugins, 'installed':installed()}


class IntegrationUpdate(BaseModel):
    podbean: bool
    plugins: list[str] | None = None


@app.post('/api/integrations')
def update_integrations(value: IntegrationUpdate):
    from .integrations import set_podbean
    try:
        return set_podbean(value.podbean, value.plugins).model_dump()
    except ValueError as exc:
        raise HTTPException(422, str(exc))


from .batches import BatchRequest


@app.post('/api/batches', status_code=201)
async def create_batch(request: BatchRequest):
    from .batches import create
    if request.options.tts_engine == 'indextts25' and not config()['indextts25_available']:
        raise HTTPException(422, 'IndexTTS runtime is not configured')
    try:
        return create(request)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get('/api/batches')
def batches():
    from .batches import describe
    return [describe(read(p)) for p in sorted((home()/'batches').glob('*/batch.json'), reverse=True)]


@app.post('/api/batches/{batch_id}/{action}')
async def batch_control(batch_id: str, action: str):
    from .batches import control
    try:
        return control(batch_id, action)
    except FileNotFoundError:
        raise HTTPException(404, 'Batch not found')
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post('/api/preferences')
def save_preferences(options: Options):
    save(home()/'preferences.json',options.model_dump())
    return {'options':options.model_dump()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return view(job_folder(job_id))


@app.post("/api/jobs", status_code=201)
async def create_job(source: str = Form(""), options: str = Form(...), file: UploadFile | None = File(None)):
    folder,staging_created = None,False
    try:
        settings = Options.model_validate_json(options)
        if settings.tts_engine=='indextts25' and not config()['indextts25_available']:
            raise ValueError('IndexTTS 2.5 runtime/model/reference encoders are not configured')
        source = source.strip()
        if bool(source) == bool(file and file.filename):
            raise ValueError("Provide either one URL or one audio file")
        if source:
            await asyncio.to_thread(public_url, source)
        job_id = str(uuid.uuid4())
        folder = home() / "jobs" / job_id
        folder.mkdir(parents=True)
        staging_created = True
        if file and file.filename:
            size = 0
            with (folder / "input.audio").open("wb") as output:
                while chunk := await file.read(1024 * 256):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("Audio upload exceeds 512 MiB")
                    output.write(chunk)
            if not size:
                raise ValueError("Audio upload is empty")
        job = {"id": job_id, "source": source or None, "filename": Path(file.filename).name if file and file.filename else None, "options": settings.model_dump(), "status": "queued", "created": time.time(), "error": None}
        save(folder / "job.json", job)
        return view(folder)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    finally:
        if file:
            await file.close()
        if staging_created and not (folder/"job.json").exists():
            (folder/"input.audio").unlink(missing_ok=True)
            try:
                folder.rmdir()
            except OSError:
                pass  # Preserve unexpected control files rather than deleting recursively.


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str):
    folder = job_folder(job_id)
    job = read(folder / "job.json")
    if job["status"] not in {"running", "queued"}:
        raise HTTPException(409, "Job is not active")
    (folder / "cancel").touch()
    if queue.active == job_id and queue.process and queue.process.poll() is None:
        os.killpg(queue.process.pid, signal.SIGTERM)
    else:
        job["status"] = "cancelled"
        save(folder / "job.json", job)
    return {"status": "cancellation requested"}


@app.post("/api/jobs/{job_id}/resume")
async def resume(job_id: str):
    folder = job_folder(job_id)
    job = read(folder / "job.json")
    if job["status"] not in {"cancelled", "failed", "interrupted", "needs_review"}:
        raise HTTPException(409, "Only stopped jobs can resume")
    (folder / "cancel").unlink(missing_ok=True)
    job.update(status="queued", error=None)
    save(folder / "job.json", job)
    return view(folder)


class SourceReview(BaseModel):
    edits: dict[int,str] = Field(min_length=1,max_length=1000)
    reason: str = Field(min_length=3,max_length=2000)


class SpeechReview(BaseModel):
    segments: list[int] = Field(min_length=1,max_length=1000)
    reason: str = Field(min_length=3,max_length=2000)


@app.post("/api/jobs/{job_id}/translation")
async def review_translation(job_id: str, review: SourceReview):
    from .review import correct_translation

    folder=job_folder(job_id)
    job=read(folder/'job.json')
    if job['status'] in {'running','queued'}:
        raise HTTPException(409,'Stop the job before correcting translation')
    if not (folder/'translation.json').exists():
        raise HTTPException(409,'No translated passages are available')
    passages=read(folder/'translation.json')
    by_id={s['id']:s for s in passages}
    if not set(review.edits).issubset(by_id) or any(not text.strip() or len(text)>4000 for text in review.edits.values()):
        raise HTTPException(422,'Use existing passage IDs and 1–4000 characters of translated text')
    if all(by_id[i]['translation']==text.strip() for i,text in review.edits.items()):
        raise HTTPException(422,'No translated text changed')
    job.update(status='interrupted',error='Translation corrected; resume to regenerate affected speech')
    save(folder/'job.json',job)
    return correct_translation(folder,review.edits,review.reason)


@app.post("/api/jobs/{job_id}/speech")
async def review_speech(job_id: str, review: SpeechReview):
    from .review import retry_speech

    folder=job_folder(job_id)
    job=read(folder/"job.json")
    if job["status"] in {"running","queued"}:
        raise HTTPException(409,"Stop the job before retrying speech")
    if not (folder/"translation.json").exists():
        raise HTTPException(409,"No translated passages are available")
    if not set(review.segments).issubset({s["id"] for s in read(folder/"translation.json")}):
        raise HTTPException(422,"Unknown passage ID")
    job.update(status="interrupted",error="Speech regeneration requested; resume after reviewing")
    save(folder/"job.json",job)
    return retry_speech(folder,review.segments,review.reason)


@app.post("/api/jobs/{job_id}/transcript")
async def review_transcript(job_id: str, review: SourceReview):
    from .review import correct_transcript,publish_source_review

    folder = job_folder(job_id)
    job = read(folder/"job.json")
    if job["status"] in {"running","queued"}:
        raise HTTPException(409,"Stop the job before correcting source text")
    if not (folder/"transcript.json").exists():
        raise HTTPException(409,"No source transcript is available")
    if any(not text.strip() or len(text)>4000 for text in review.edits.values()):
        raise HTTPException(422,"Passage text must contain 1–4000 characters")
    existing = read(folder/"transcript.json")
    if not set(review.edits).issubset({s["id"] for s in existing["segments"]}):
        raise HTTPException(422,"Unknown passage ID")
    if all(s["text"]==review.edits.get(s["id"],s["text"]).strip() for s in existing["segments"]):
        raise HTTPException(422,"No source text changed")
    job.update(status="interrupted",error="Source correction requested; resume after reviewing")
    save(folder/"job.json",job)
    try:
        receipt = correct_transcript(folder,review.edits,review.reason)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    if (folder/"source.json").exists():
        receipt.update(publish_source_review(folder,receipt,options_for_job(job)))
        if receipt.get("cache_warning"):
            job["error"]+=". "+receipt["cache_warning"]
            save(folder/"job.json",job)
    return receipt


@app.get("/api/jobs/{job_id}/files/{name}")
def download(job_id: str, name: str):
    if name not in FILES:
        raise HTTPException(404, "File not found")
    folder = job_folder(job_id)
    if name not in view(folder)["files"] or not (folder/name).is_file():
        raise HTTPException(404, "File not ready")
    from .exports import download_name
    return FileResponse(folder/name, filename=download_name(folder,name))


@app.post('/api/jobs/{job_id}/export')
async def export(job_id: str):
    from .exports import export_job
    folder=job_folder(job_id)
    try:
        return await asyncio.to_thread(export_job,folder)
    except (OSError,ValueError,KeyError) as exc:
        raise HTTPException(409,str(exc))
