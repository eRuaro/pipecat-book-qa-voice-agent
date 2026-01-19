"""Main Pipecat bot for book Q&A voice agent."""

import os
from typing import Callable, Optional

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.camb.tts import CambTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.services.daily import DailyParams, DailyTransport

from progress_tracker import STTProgressProcessor, LLMProgressProcessor, TTSStatusProcessor
from web_search import WebSearcher


# Cached API clients (reused across connections to avoid connection overhead)
_camb_client = None
web_searcher: Optional[WebSearcher] = None


def get_camb_client():
    """Get or create the shared CAMB API client."""
    global _camb_client
    if _camb_client is None:
        from camb.client import AsyncCambAI
        logger.info("Creating shared CAMB API client")
        _camb_client = AsyncCambAI(api_key=os.getenv("CAMB_API_KEY"), timeout=60.0)
    return _camb_client


def create_tts_service(model: str = "mars-flash") -> CambTTSService:
    """Create a TTS service with shared API client."""
    tts = CambTTSService(
        api_key=os.getenv("CAMB_API_KEY"),
        model=model,
    )
    # Inject cached client to reuse connections
    tts._client = get_camb_client()
    return tts


def create_stt_service() -> DeepgramSTTService:
    """Create a fresh STT service."""
    return DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))


def create_llm_service() -> GoogleLLMService:
    """Create a fresh LLM service."""
    llm = GoogleLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model="gemini-3-flash-preview",
    )
    llm.register_function("search_web", search_web)
    return llm


SYSTEM_PROMPT_WITH_FILE = """You are a helpful voice assistant that answers questions about the uploaded document.

IMPORTANT RULES:
1. Answer questions based on the document that has been uploaded. You have direct access to it.
2. You have access to a search_web function - ONLY use it when the user explicitly asks about something not covered in the document, or asks you to look something up online.
3. Keep responses concise (under 100 words) since they will be spoken aloud.
4. Do not discuss topics completely unrelated to the document or its themes.
5. If asked about something outside the document's scope, politely mention that and offer to search the web if relevant.
6. Speak naturally as this is a voice conversation.

CRITICAL - Your responses will be read aloud by text-to-speech. You MUST:
- Never use asterisks (*), markdown formatting, or bullet points
- Never use special characters like #, -, _, or similar
- Never use parenthetical asides like (pause) or (laughs)
- Write in plain, flowing sentences only
- Spell out abbreviations and acronyms when first used
- Use words like "first", "second", "third" instead of numbered lists
"""

SYSTEM_PROMPT_NO_FILE = """You are a helpful voice assistant. The user has not uploaded a document yet.

Please ask the user to upload a document (PDF or text file) so you can answer questions about it.

Keep responses concise and natural since they will be spoken aloud.

CRITICAL - Your responses will be read aloud by text-to-speech. You MUST:
- Never use asterisks (*), markdown formatting, or bullet points
- Never use special characters like #, -, _, or similar
- Never use parenthetical asides like (pause) or (laughs)
- Write in plain, flowing sentences only
"""


def create_tools() -> ToolsSchema:
    """Create the function calling tools."""
    search_function = FunctionSchema(
        name="search_web",
        description="Search the web for information. Only use this when the user asks about something not in the document, or explicitly asks you to search online.",
        properties={
            "query": {
                "type": "string",
                "description": "The search query to look up on the web.",
            },
        },
        required=["query"],
    )
    return ToolsSchema(standard_tools=[search_function])


async def search_web(params: FunctionCallParams):
    """Handle web search function calls from the LLM."""
    global web_searcher

    query = params.arguments.get("query", "")
    logger.info(f"Web search requested: {query}")

    if web_searcher is None:
        web_searcher = WebSearcher()

    results = await web_searcher.search(query, num_results=3)
    formatted = web_searcher.format_results_for_llm(results)

    logger.info(f"Web search results: {formatted[:200]}...")
    await params.result_callback(formatted)


async def run_bot(
    room_url: str,
    token: str,
    file_uri: Optional[str] = None,
    mime_type: Optional[str] = None,
    book_title: Optional[str] = None,
    tts_model: str = "mars-flash",
    session_id: Optional[str] = None,
    cleanup_callback: Optional[Callable] = None,
):
    """Run the voice agent bot for a Daily room.

    Args:
        room_url: The Daily room URL.
        token: The Daily token for the bot.
        file_uri: Optional Gemini file URI for the uploaded document.
        mime_type: Optional mime type of the uploaded file.
        book_title: Optional book title.
        tts_model: TTS model to use (mars-flash or mars-pro).
        session_id: Optional session ID for cleanup.
        cleanup_callback: Optional callback to clean up session when done.
    """
    transport = DailyTransport(
        room_url,
        token,
        "Book Q&A Bot",
        DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.3)),
        ),
    )

    # Create fresh service instances (with cached API clients for CAMB)
    stt = create_stt_service()
    tts = create_tts_service(tts_model)
    llm = create_llm_service()

    logger.info(f"Using TTS model: {tts_model}")

    # Create tools and context
    tools = create_tools()

    # Build initial messages based on whether we have a file
    if file_uri:
        logger.info(f"Starting bot with file: {book_title} ({file_uri})")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_WITH_FILE},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"I've uploaded a document called '{book_title}'. Greet me briefly and let me know you're ready to answer questions about it.",
                    },
                    {
                        "type": "file_data",
                        "file_data": {"mime_type": mime_type, "file_uri": file_uri},
                    },
                ],
            },
        ]
    else:
        logger.info("Starting bot without file")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_NO_FILE},
            {
                "role": "user",
                "content": "Greet me briefly and ask me to upload a document.",
            },
        ]

    context = LLMContext(messages, tools)
    context_aggregator = LLMContextAggregatorPair(context)

    # Progress processors for status updates
    stt_progress = STTProgressProcessor()
    llm_progress = LLMProgressProcessor()
    tts_status = TTSStatusProcessor()

    # Build the pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            stt_progress,
            context_aggregator.user(),
            llm,
            llm_progress,
            tts,
            tts_status,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(enable_metrics=True),
    )

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        logger.info(f"Participant joined: {participant['id']}")
        # Trigger initial greeting
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.info(f"Participant left: {participant['id']}, reason: {reason}")
        await task.cancel()

    @transport.event_handler("on_dialin_ready")
    async def on_dialin_ready(transport, cdata):
        logger.info("Dialin ready")

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)

    # Cleanup session when bot exits
    if cleanup_callback and session_id:
        await cleanup_callback(session_id)

    logger.info("Bot finished")
