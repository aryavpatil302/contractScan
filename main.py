import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fetcher import fetch_url
from scanner import scan

load_dotenv()

app = FastAPI(title="Contract Risk Scanner", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    text: str | None = None
    url: str | None = None
    focus: str | None = None


@app.post("/scan")
async def scan_endpoint(body: ScanRequest):
    if not body.text and not body.url:
        raise HTTPException(400, "Provide either 'text' or 'url'")

    if body.url:
        from urllib.parse import urlparse
        parsed = urlparse(body.url)
        if parsed.scheme not in ("http", "https"):
            raise HTTPException(400, "URL must use http or https")
        try:
            text = await fetch_url(body.url)
        except Exception as e:
            raise HTTPException(422, f"Could not fetch URL: {e}")
        if len(text.strip()) < 200:
            raise HTTPException(
                422,
                "Fetched page has too little text — the site may require JavaScript "
                "rendering. Try pasting the contract text directly.",
            )
    else:
        text = (body.text or "").strip()
        if len(text) < 100:
            raise HTTPException(400, "Text too short to analyze (minimum 100 characters)")

    try:
        result = scan(text, focus=body.focus)
    except EnvironmentError as e:
        raise HTTPException(503, "Server misconfiguration: API key not set")
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    return result


@app.get("/health")
def health():
    return {"status": "ok"}


_FRONTEND = os.path.join(os.path.dirname(__file__), "frontend")
app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
