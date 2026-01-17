#
# Copyright (c) 2024–2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Local copy of Camb.ai MARS text-to-speech service with correct sample rates.

This is a local copy to handle the mars-flash sample rate change from 22.05kHz to 48kHz.
"""

from typing import Any, AsyncGenerator, Dict, Optional

from camb import StreamTtsOutputConfiguration
from camb.client import AsyncCambAI
from loguru import logger
from pydantic import BaseModel, Field

from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language, resolve_language
from pipecat.utils.tracing.service_decorators import traced_tts

# Model-specific sample rates - updated for mars-flash 48kHz output
MODEL_SAMPLE_RATES: Dict[str, int] = {
    "mars-flash": 48000,  # Updated: was 22.05kHz, now 48kHz
    "mars-pro": 48000,
    "mars-instruct": 22050,
}


def language_to_camb_language(language: Language) -> Optional[str]:
    """Convert a Pipecat Language enum to Camb.ai language code."""
    LANGUAGE_MAP = {
        Language.EN: "en-us",
        Language.EN_US: "en-us",
        Language.EN_GB: "en-gb",
        Language.EN_AU: "en-au",
        Language.ES: "es-es",
        Language.ES_ES: "es-es",
        Language.ES_MX: "es-mx",
        Language.FR: "fr-fr",
        Language.FR_FR: "fr-fr",
        Language.FR_CA: "fr-ca",
        Language.DE: "de-de",
        Language.DE_DE: "de-de",
        Language.IT: "it-it",
        Language.PT: "pt-pt",
        Language.PT_BR: "pt-br",
        Language.PT_PT: "pt-pt",
        Language.NL: "nl-nl",
        Language.PL: "pl-pl",
        Language.RU: "ru-ru",
        Language.JA: "ja-jp",
        Language.KO: "ko-kr",
        Language.ZH: "zh-cn",
        Language.ZH_CN: "zh-cn",
        Language.ZH_TW: "zh-tw",
        Language.AR: "ar-sa",
        Language.HI: "hi-in",
        Language.TR: "tr-tr",
        Language.VI: "vi-vn",
        Language.TH: "th-th",
        Language.ID: "id-id",
        Language.MS: "ms-my",
        Language.SV: "sv-se",
        Language.DA: "da-dk",
        Language.NO: "no-no",
        Language.FI: "fi-fi",
        Language.CS: "cs-cz",
        Language.EL: "el-gr",
        Language.HE: "he-il",
        Language.HU: "hu-hu",
        Language.RO: "ro-ro",
        Language.SK: "sk-sk",
        Language.UK: "uk-ua",
        Language.BG: "bg-bg",
        Language.HR: "hr-hr",
        Language.SR: "sr-rs",
        Language.SL: "sl-si",
        Language.CA: "ca-es",
        Language.EU: "eu-es",
        Language.GL: "gl-es",
        Language.AF: "af-za",
        Language.SW: "sw-ke",
        Language.TA: "ta-in",
        Language.TE: "te-in",
        Language.BN: "bn-in",
        Language.MR: "mr-in",
        Language.GU: "gu-in",
        Language.KN: "kn-in",
        Language.ML: "ml-in",
        Language.PA: "pa-in",
        Language.UR: "ur-pk",
        Language.FA: "fa-ir",
        Language.TL: "tl-ph",
    }
    return resolve_language(language, LANGUAGE_MAP, use_base_code=True)


def _get_aligned_audio(buffer: bytes) -> tuple[bytes, bytes]:
    """Split buffer into aligned audio (2-byte samples) and remainder."""
    aligned_size = (len(buffer) // 2) * 2
    return buffer[:aligned_size], buffer[aligned_size:]


class CambTTSService(TTSService):
    """Camb.ai MARS text-to-speech service with correct 48kHz sample rate for mars-flash."""

    class InputParams(BaseModel):
        language: Optional[Language] = Language.EN
        user_instructions: Optional[str] = Field(
            default=None,
            max_length=1000,
            description="Custom instructions for mars-instruct model only.",
        )

    def __init__(
        self,
        *,
        api_key: str,
        voice_id: int = 147320,
        model: str = "mars-flash",
        timeout: float = 60.0,
        sample_rate: Optional[int] = None,
        params: Optional[InputParams] = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        params = params or CambTTSService.InputParams()
        self._client = AsyncCambAI(api_key=api_key, timeout=timeout)

        if sample_rate and sample_rate != MODEL_SAMPLE_RATES.get(model):
            logger.warning(
                f"Camb.ai's {model} model only supports {MODEL_SAMPLE_RATES.get(model)}Hz "
                f"sample rate. Current rate of {sample_rate}Hz may cause issues."
            )

        self._settings = {
            "language": (
                self.language_to_service_language(params.language) if params.language else "en-us"
            ),
            "user_instructions": params.user_instructions,
        }

        self.set_model_name(model)
        self.set_voice(str(voice_id))
        self._voice_id = voice_id

    def can_generate_metrics(self) -> bool:
        return True

    def language_to_service_language(self, language: Language) -> Optional[str]:
        return language_to_camb_language(language)

    async def start(self, frame: StartFrame):
        await super().start(frame)
        if not self._init_sample_rate:
            self._sample_rate = MODEL_SAMPLE_RATES.get(self._model_name, 48000)
        self._settings["sample_rate"] = self._sample_rate

        if self._sample_rate != MODEL_SAMPLE_RATES.get(self._model_name):
            logger.warning(
                f"Camb.ai's {self._model_name} model requires "
                f"{MODEL_SAMPLE_RATES.get(self._model_name)}Hz sample rate. "
                f"Current rate of {self._sample_rate}Hz may cause issues."
            )

    @traced_tts
    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"{self}: Generating TTS [{text}]")

        if len(text) > 3000:
            logger.warning("Text too long for Camb.ai TTS (max 3000 chars), truncating")
            text = text[:3000]

        try:
            await self.start_ttfb_metrics()

            tts_kwargs: Dict[str, Any] = {
                "text": text,
                "voice_id": self._voice_id,
                "language": self._settings["language"],
                "speech_model": self.model_name,
                "output_configuration": StreamTtsOutputConfiguration(format="pcm_s16le"),
            }

            if self._model_name == "mars-instruct" and self._settings.get("user_instructions"):
                tts_kwargs["user_instructions"] = self._settings["user_instructions"]

            await self.start_tts_usage_metrics(text)
            yield TTSStartedFrame()

            audio_buffer = b""

            async for chunk in self._client.text_to_speech.tts(**tts_kwargs):
                if chunk:
                    await self.stop_ttfb_metrics()
                    audio_buffer += chunk

                    aligned_audio, audio_buffer = _get_aligned_audio(audio_buffer)
                    if aligned_audio:
                        yield TTSAudioRawFrame(
                            audio=aligned_audio,
                            sample_rate=self.sample_rate,
                            num_channels=1,
                        )

            if len(audio_buffer) >= 2:
                aligned_audio, _ = _get_aligned_audio(audio_buffer)
                if aligned_audio:
                    yield TTSAudioRawFrame(
                        audio=aligned_audio,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                    )

        except Exception as e:
            yield ErrorFrame(error=f"Camb.ai TTS error: {e}")
        finally:
            yield TTSStoppedFrame()
