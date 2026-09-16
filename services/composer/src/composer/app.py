"""FastAPI application for the bossa arrangement service."""

import logging
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from composer.pipeline import arrange

app = FastAPI(
    title="nineteenseventytwo-composer",
    description="AI-powered bossa jazz arrangement service",
    version="0.1.0",
)

log_level = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
logger = logging.getLogger(__name__)

# Sniffed from the first bytes rather than taken from the filename. The
# filename is a client assertion; on a public endpoint it is not evidence.
# Compressed MusicXML (.mxl) is a zip — which is what MuseScore exports by
# default, and what every score in the reference corpus is. Handing zip bytes
# to the XML parser raises "not well-formed (invalid token): line 1, column 2",
# which is how /arrange came to fail on 100% of real uploads while the library
# underneath handled them correctly.
_ZIP_MAGIC = b"PK\x03\x04"
_XML_PREFIXES = (b"<?xml", b"<score-partwise", b"<score-timewise", b"\xef\xbb\xbf<?xml")

# music21 parsing is unbounded work on attacker-supplied input, under a tenant
# quota where limits.memory covers every service in the namespace. The largest
# score in the reference corpus is 28 KB compressed, so this is generous.
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 5 * 1024 * 1024))


def _suffix_for(content: bytes) -> str | None:
    """Return the file suffix implied by the content, or None if unrecognised."""
    if content.startswith(_ZIP_MAGIC):
        return ".mxl"
    if content.lstrip()[:64].startswith(_XML_PREFIXES):
        return ".musicxml"
    return None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/arrange")
async def arrange_endpoint(file: UploadFile = File(...)):
    """Accept a MusicXML piano score and return a bossa arrangement.

    Accepts compressed (`.mxl`) or plain (`.musicxml`, `.xml`) MusicXML,
    detected from content. Returns a MusicXML file with the full arrangement.
    """
    content = await file.read()

    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Score exceeds {MAX_UPLOAD_BYTES} bytes",
        )

    suffix = _suffix_for(content)
    if suffix is None:
        # A malformed upload is the client's error and should read as one; this
        # previously surfaced as a 500 from deep inside the parser.
        raise HTTPException(
            status_code=400,
            detail="Not a MusicXML file — expected .mxl, .musicxml or .xml",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
        tmp_in.write(content)
        input_path = Path(tmp_in.name)

    output_path = input_path.with_name("arranged_" + input_path.stem + ".musicxml")

    try:
        result = await arrange(input_path, output_path)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        input_path.unlink(missing_ok=True)

    # FileResponse does not remove what it serves, despite the previous
    # comment here claiming otherwise — the output files accumulated for the
    # life of the pod. A BackgroundTask runs after the response is sent.
    # A fallback used to be invisible: the caller received a well-formed file
    # and had no way to tell that none of it had been transformed (C3). The
    # headers say what actually happened, without changing the media type.
    if result.total and not result.transformed:
        raise HTTPException(
            status_code=502,
            detail=(
                "No section could be arranged — "
                + (result.outcomes[0].reason or "unknown reason")
            ),
        )

    return FileResponse(
        path=str(output_path),
        media_type="application/xml",
        filename="arrangement.musicxml",
        background=BackgroundTask(output_path.unlink, missing_ok=True),
        headers={
            "X-Composer-Chunks-Transformed": str(result.transformed),
            "X-Composer-Chunks-Total": str(result.total),
        },
    )
