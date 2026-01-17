"""FastAPI server with WebRTC endpoints for the book Q&A voice agent."""

import os
import uuid
from typing import Dict, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection

from book_processor import BookProcessor
from bot import run_bot

load_dotenv()

app = FastAPI(title="Book Q&A Voice Agent")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active WebRTC connections
connections: Dict[str, SmallWebRTCConnection] = {}

# Store sessions with their book processors
sessions: Dict[str, Dict] = {}

# STUN server for WebRTC NAT traversal
ice_servers = [IceServer(urls="stun:stun.l.google.com:19302")]


@app.get("/")
async def root():
    """Redirect root to the client."""
    return RedirectResponse(url="/index.html")


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/api/session")
async def create_session():
    """Create a new session for a user."""
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "book_processor": BookProcessor(),
        "file_uri": None,
        "mime_type": None,
        "book_title": None,
    }
    logger.info(f"Created session: {session_id}")
    return {"session_id": session_id}


@app.post("/api/session/{session_id}/upload-book")
async def upload_book(session_id: str, file: UploadFile = File(...)):
    """Upload a book for the session using Gemini File API.

    Args:
        session_id: The session ID.
        file: The uploaded file (PDF or TXT).

    Returns:
        Success message with file info.
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate file type
    filename = file.filename or "unknown"
    if not (filename.lower().endswith(".pdf") or filename.lower().endswith(".txt")):
        raise HTTPException(
            status_code=400,
            detail="Only PDF and TXT files are supported"
        )

    try:
        content = await file.read()
        processor = sessions[session_id]["book_processor"]

        # Upload to Gemini File API
        result = await processor.process_file(content, filename)

        # Store file info in session
        sessions[session_id]["file_uri"] = result["file_uri"]
        sessions[session_id]["mime_type"] = result["mime_type"]
        sessions[session_id]["book_title"] = result["filename"]

        logger.info(f"Session {session_id}: Uploaded '{filename}' to Gemini")

        return {
            "success": True,
            "filename": filename,
            "file_uri": result["file_uri"],
        }
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload: {str(e)}")


@app.post("/api/session/{session_id}/clear-book")
async def clear_book(session_id: str):
    """Clear the book for the session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    processor = sessions[session_id]["book_processor"]
    await processor.clear()

    sessions[session_id]["file_uri"] = None
    sessions[session_id]["mime_type"] = None
    sessions[session_id]["book_title"] = None

    logger.info(f"Session {session_id}: Cleared book")
    return {"success": True}


@app.post("/start")
async def start(request_data: dict = {}):
    """RTVI protocol: Create a new session."""
    session_id = str(uuid.uuid4())

    # Initialize session if not exists
    if session_id not in sessions:
        sessions[session_id] = {
            "book_processor": BookProcessor(),
            "file_uri": None,
            "mime_type": None,
            "book_title": None,
        }

    result = {"sessionId": session_id}
    if request_data.get("enableDefaultIceServers"):
        result["iceConfig"] = {"iceServers": [{"urls": "stun:stun.l.google.com:19302"}]}

    return result


@app.api_route("/sessions/{session_id}/{path:path}", methods=["POST", "PATCH"])
async def session_proxy(
    session_id: str,
    path: str,
    request_data: dict,
    background_tasks: BackgroundTasks,
):
    """RTVI protocol: Proxy requests to session endpoints."""
    if session_id not in sessions:
        # Create session on the fly
        sessions[session_id] = {
            "book_processor": BookProcessor(),
            "file_uri": None,
            "mime_type": None,
            "book_title": None,
        }

    if path.endswith("api/offer"):
        return await offer(request_data, background_tasks, session_id)

    return {"status": "ok"}


@app.post("/api/offer")
async def offer_endpoint(
    request_data: dict,
    background_tasks: BackgroundTasks,
):
    """Direct WebRTC offer endpoint (without session)."""
    return await offer(request_data, background_tasks, None)


async def offer(
    request_data: dict,
    background_tasks: BackgroundTasks,
    session_id: Optional[str] = None,
):
    """Handle WebRTC offer from the client."""
    pc_id = request_data.get("pc_id")
    tts_model = request_data.get("tts_model", "mars-flash")

    # Get file info from session if available
    file_uri = None
    mime_type = None
    book_title = None
    if session_id and session_id in sessions:
        file_uri = sessions[session_id].get("file_uri")
        mime_type = sessions[session_id].get("mime_type")
        book_title = sessions[session_id].get("book_title")

    if pc_id and pc_id in connections:
        conn = connections[pc_id]
        await conn.renegotiate(
            sdp=request_data["sdp"],
            type=request_data["type"],
            restart_pc=request_data.get("restart_pc", False),
        )
    else:
        conn = SmallWebRTCConnection(ice_servers)
        await conn.initialize(sdp=request_data["sdp"], type=request_data["type"])

        @conn.event_handler("closed")
        async def handle_closed(c: SmallWebRTCConnection):
            connections.pop(c.pc_id, None)
            # Clean up session only if no book uploaded (keep sessions with books for reconnect)
            if session_id and session_id in sessions:
                if not sessions[session_id].get("file_uri"):
                    sessions.pop(session_id, None)
                    logger.info(f"Session {session_id} cleaned up (no book)")
                else:
                    logger.info(f"Session {session_id} kept (has book)")
            logger.info(f"Connection {c.pc_id} closed, active connections: {len(connections)}, sessions: {len(sessions)}")

        background_tasks.add_task(run_bot, conn, file_uri, mime_type, book_title, tts_model)

    answer = conn.get_answer()
    connections[answer["pc_id"]] = conn
    logger.info(f"Active connections: {len(connections)}, sessions: {len(sessions)}")
    return answer


# Mount static files for frontend (if exists)
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="static")


def main():
    """Entry point for the server."""
    port = int(os.getenv("PORT", 7860))
    print(f"Starting Book Q&A Voice Agent server on port {port}...")
    print(f"API docs available at http://localhost:{port}/docs")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
