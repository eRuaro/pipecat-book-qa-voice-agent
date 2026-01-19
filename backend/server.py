"""FastAPI server with Daily WebRTC endpoints for the book Q&A voice agent."""

import os
import uuid
import time
from typing import Dict, Optional
from contextlib import asynccontextmanager

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from pipecat.transports.services.helpers.daily_rest import DailyRESTHelper, DailyRoomParams

from book_processor import BookProcessor
from bot import run_bot

load_dotenv()

# Shared aiohttp session for Daily API calls
_aiohttp_session: Optional[aiohttp.ClientSession] = None
_daily_helper: Optional[DailyRESTHelper] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage aiohttp session lifecycle."""
    global _aiohttp_session, _daily_helper
    _aiohttp_session = aiohttp.ClientSession()
    daily_api_key = os.getenv("DAILY_API_KEY")
    if daily_api_key:
        _daily_helper = DailyRESTHelper(
            daily_api_key=daily_api_key,
            aiohttp_session=_aiohttp_session,
        )
        logger.info("Daily REST helper initialized")
    else:
        logger.warning("DAILY_API_KEY not set - voice calls will not work")
    yield
    await _aiohttp_session.close()


app = FastAPI(title="Book Q&A Voice Agent", lifespan=lifespan)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store sessions with their book processors
sessions: Dict[str, Dict] = {}


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
        "room_url": None,
    }
    logger.info(f"Created session: {session_id}")
    return {"session_id": session_id}


@app.post("/api/session/{session_id}/upload-book")
async def upload_book(session_id: str, file: UploadFile = File(...)):
    """Upload a book for the session using Gemini File API."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    filename = file.filename or "unknown"
    if not (filename.lower().endswith(".pdf") or filename.lower().endswith(".txt")):
        raise HTTPException(
            status_code=400,
            detail="Only PDF and TXT files are supported"
        )

    try:
        content = await file.read()
        processor = sessions[session_id]["book_processor"]
        result = await processor.process_file(content, filename)

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


@app.post("/api/session/{session_id}/connect")
async def connect_session(
    session_id: str,
    request_data: dict,
    background_tasks: BackgroundTasks,
):
    """Create a Daily room and start the bot for a session."""
    if not _daily_helper:
        raise HTTPException(status_code=500, detail="Daily API not configured")

    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    tts_model = request_data.get("tts_model", "mars-flash")

    # Get file info from session
    file_uri = sessions[session_id].get("file_uri")
    mime_type = sessions[session_id].get("mime_type")
    book_title = sessions[session_id].get("book_title")

    try:
        # Create a temporary Daily room (expires in 10 minutes)
        room = await _daily_helper.create_room(
            DailyRoomParams(
                name=f"book-qa-{session_id[:8]}",
                properties={
                    "exp": time.time() + 600,  # 10 minutes
                    "enable_chat": False,
                    "enable_emoji_reactions": False,
                    "eject_at_room_exp": True,
                },
            )
        )
        logger.info(f"Created Daily room: {room.url}")

        # Store room URL in session for cleanup
        sessions[session_id]["room_url"] = room.url

        # Generate token for the user (client)
        user_token = await _daily_helper.get_token(
            room_url=room.url,
            expiry_time=600,  # 10 minutes
        )

        # Generate token for the bot
        bot_token = await _daily_helper.get_token(
            room_url=room.url,
            expiry_time=600,
        )

        # Start the bot in the background
        background_tasks.add_task(
            run_bot,
            room.url,
            bot_token,
            file_uri,
            mime_type,
            book_title,
            tts_model,
            session_id,
            cleanup_session,
        )

        logger.info(f"Session {session_id}: Bot started, room: {room.url}")

        return {
            "room_url": room.url,
            "token": user_token,
        }

    except Exception as e:
        logger.error(f"Failed to create room: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {str(e)}")


async def cleanup_session(session_id: str):
    """Clean up session and delete Daily room."""
    if session_id in sessions:
        room_url = sessions[session_id].get("room_url")
        if room_url and _daily_helper:
            try:
                await _daily_helper.delete_room_by_url(room_url)
                logger.info(f"Deleted Daily room: {room_url}")
            except Exception as e:
                logger.warning(f"Failed to delete room: {e}")
        sessions.pop(session_id, None)
        logger.info(f"Session {session_id} cleaned up")


# Mount static files for frontend (if exists)
frontend_path = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
logger.info(f"Looking for frontend at: {frontend_path}")
if os.path.exists(frontend_path):
    logger.info(f"Frontend found, mounting static files")
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="static")
else:
    logger.warning(f"Frontend not found at {frontend_path}")


def main():
    """Entry point for the server."""
    port = int(os.getenv("PORT", 7860))
    print(f"Starting Book Q&A Voice Agent server on port {port}...")
    print(f"API docs available at http://localhost:{port}/docs")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
