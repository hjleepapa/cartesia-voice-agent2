import argparse
import asyncio
import os

from rich import print

from .agents import MortgageAgent
from .config import settings
from .memory import MemoryStore
from .stt_cartesia import CartesiaSTTClient
from .tts_cartesia import CartesiaTTSClient


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cartesia voice agent scaffold")
    parser.add_argument("--audio", help="Path to input audio file")
    parser.add_argument("--text", help="Direct text input")
    parser.add_argument("--output", default="output.wav", help="Path to output audio file")
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    if not args.audio and not args.text:
        raise SystemExit("Provide --audio or --text")

    if args.audio:
        stt = CartesiaSTTClient()
        user_text = stt.transcribe_file(args.audio)
    else:
        user_text = args.text

    if not user_text:
        raise SystemExit("No text detected")

    memory = MemoryStore(settings.memory_db_uri)
    memory.add(role="user", content=user_text)
    agent = MortgageAgent(memory=memory)
    response_text = await agent.run(user_text)

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    tts = CartesiaTTSClient()
    tts.synthesize_to_file(response_text, args.output)
    print(f"[green]Response saved to {args.output}[/green]")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
