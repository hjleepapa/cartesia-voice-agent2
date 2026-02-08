from typing import Optional

from cartesia import Cartesia

from .config import settings


class CartesiaTTSClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        voice_id: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or settings.cartesia_api_key
        self.model_id = model_id or settings.cartesia_tts_model
        self.voice_id = voice_id or settings.cartesia_voice_id
        if not self.api_key:
            raise RuntimeError("CARTESIA_API_KEY is required for TTS")
        if not self.voice_id:
            raise RuntimeError("CARTESIA_VOICE_ID is required for TTS")
        self.client = Cartesia(api_key=self.api_key)

    def synthesize_to_file(self, text: str, output_path: str) -> None:
        generation_config = {}
        if settings.cartesia_tts_speed is not None:
            generation_config["speed"] = settings.cartesia_tts_speed
        if settings.cartesia_tts_volume is not None:
            generation_config["volume"] = settings.cartesia_tts_volume
        if settings.cartesia_tts_emotion:
            generation_config["emotion"] = settings.cartesia_tts_emotion

        params = {
            "model_id": self.model_id,
            "transcript": text,
            "voice": {"mode": "id", "id": self.voice_id},
            "output_format": {
                "container": "wav",
                "sample_rate": 44100,
                "encoding": "pcm_f32le",
            },
        }
        if generation_config:
            params["generation_config"] = generation_config

        chunk_iter = self.client.tts.bytes(**params)

        with open(output_path, "wb") as audio_file:
            for chunk in chunk_iter:
                audio_file.write(chunk)
