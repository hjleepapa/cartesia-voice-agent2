import os
from typing import Optional

import httpx

from .config import settings


class CartesiaSTTClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        version: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or settings.cartesia_api_key
        self.version = version or settings.cartesia_version
        self.model = model or settings.cartesia_stt_model

    def transcribe_file(self, audio_path: str, language: str = "en") -> str:
        if not self.api_key:
            raise RuntimeError("CARTESIA_API_KEY is required for STT")
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(audio_path)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Cartesia-Version": self.version,
        }

        with open(audio_path, "rb") as audio_file:
            files = {"file": audio_file}
            data = {
                "model": self.model,
                "language": language,
                "timestamp_granularities[]": "word",
            }
            response = httpx.post(
                "https://api.cartesia.ai/stt",
                headers=headers,
                files=files,
                data=data,
                timeout=60.0,
            )
        response.raise_for_status()
        payload = response.json()
        return payload.get("text", "").strip()
