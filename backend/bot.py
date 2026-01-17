"""Main Pipecat bot for book Q&A voice agent."""

import os
from typing import Optional

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame, OutputTransportMessageFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.camb.tts import CambTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

from progress_tracker import STTProgressProcessor, LLMProgressProcessor, TTSStatusProcessor
from web_search import WebSearcher


# Global web searcher instance
web_searcher: Optional[WebSearcher] = None


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
    conn: SmallWebRTCConnection,
    file_uri: Optional[str] = None,
    mime_type: Optional[str] = None,
    book_title: Optional[str] = None,
):
    """Run the voice agent bot for a WebRTC connection.

    Args:
        conn: The WebRTC connection.
        file_uri: Optional Gemini file URI for the uploaded document.
        mime_type: Optional mime type of the uploaded file.
        book_title: Optional book title.
    """
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    transport = SmallWebRTCTransport(
        webrtc_connection=conn,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.3)),
        ),
    )

    # Speech-to-text with Deepgram
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
    )

    # CAMB AI TTS - using mars-flash for low latency
    tts = CambTTSService(
        api_key=os.getenv("CAMB_API_KEY"),
        model="mars-flash",
    )

    # Google Gemini LLM
    llm = GoogleLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model="gemini-3.0-flash-preview",
    )

    # Register web search function
    llm.register_function("search_web", search_web)

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

    # Progress processors for status updates - split by position in pipeline
    stt_progress = STTProgressProcessor()      # After STT for transcription frames
    llm_progress = LLMProgressProcessor()      # After LLM for response streaming
    tts_status = TTSStatusProcessor()          # After TTS for speaking status

    # Build the pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            stt_progress,           # Catches TranscriptionFrame, sends user transcript
            context_aggregator.user(),
            llm,
            llm_progress,           # Catches LLMTextFrame, sends assistant transcript
            tts,
            tts_status,             # Catches TTS frames for speaking status
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(enable_metrics=True),
    )

    @transport.event_handler("on_client_connected")
    async def on_connected(transport, client):
        logger.info("Client connected")
        # Send initial status
        await task.queue_frame(
            OutputTransportMessageFrame(message={"type": "status", "status": "connected"})
        )
        # Trigger initial greeting
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(transport, client):
        logger.info("Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
