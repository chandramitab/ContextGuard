from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)
from fastapi import FastAPI,UploadFile,File,Form,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.services.pipeline import run_pipeline, UnsupportedUpload
app=FastAPI(title="ContextGuard")
# localhost and 127.0.0.1 are different origins to the browser: a tab opened on
# one while CORS allows only the other gets its response blocked client-side,
# even though the server logs a clean 200.
app.add_middleware(CORSMiddleware,allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

@app.get("/health")
def health():
    import os
    # Which credential the spawned CLI will resolve first. Never echo the key.
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    return {
        "status": "ok",
        "mode": os.getenv("CONTEXTGUARD_MODE", "local").lower(),
        "model": os.getenv("CONTEXTGUARD_MODEL", "sonnet"),
        "auth": "api_key" if key else "cli_session",
        "api_key_suffix": key[-4:] if key else None,
    }

@app.post("/api/analyze")
async def analyze(task:str=Form(...),files:list[UploadFile]=File(...)):
    if not task.strip(): raise HTTPException(400,"Task is required.")
    try:return await run_pipeline(task,files)
    except UnsupportedUpload as e: raise HTTPException(400,str(e))
    except Exception as e: raise HTTPException(500,str(e))

@app.get("/api/session/{sid}/released/{filename}")
def released(sid:str,filename:str):
    import os
    p=Path(os.getenv("SESSION_ROOT","/tmp/contextguard-agentic"))/sid/"released"/Path(filename).name
    if not p.exists(): raise HTTPException(404,"Not found")
    return FileResponse(p)
