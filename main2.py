import asyncio
import json
import os
import requests

from livekit import rtc
from livekit.agents import JobContext, WorkerOptions, cli, JobProcess
from livekit.agents.llm import (
    ChatContext,
    ChatMessage,
)
from livekit.agents.pipeline import VoicePipelineAgent
import logging
from livekit.agents.log import logger
from livekit.plugins import deepgram, silero, cartesia, openai, elevenlabs
from typing import List, Any
from livekit.plugins.elevenlabs import tts
from dotenv import load_dotenv
# logging.basicConfig(level=logging.INFO)  # Ensure logging is set to INFO or lower
# logger = logging.getLogger(__name__)
load_dotenv(dotenv_path=".env.local")

DEFAULT_ELEVENLABS_VOICE_ID = "ErXwobaYiN019PkySvjV"
ELEVENLABS_VOICES_LIST = [
    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
    {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella"},
    {"id": "29vD33N1CtxCmqQRPOHJ", "name": "Drew"},
    {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni"},
    
    ]

def prewarm(proc: JobProcess):
    # preload models when process starts to speed up first interaction
    proc.userdata["vad"] = silero.VAD.load()


    # headers = {
    #     "X-API-Key": os.getenv("CARTESIA_API_KEY", ""),
    #     "Cartesia-Version": "2024-08-01",
    #     "Content-Type": "application/json",
    # }
    # response = requests.get("https://api.cartesia.ai/voices", headers=headers)
    # if response.status_code == 200:
    #     proc.userdata["cartesia_voices"] = response.json()
    # else:
    #     logger.warning(f"Failed to fetch Cartesia voices: {response.status_code}")


async def entrypoint(ctx: JobContext):
    initial_ctx = ChatContext(
        messages=[
            ChatMessage(
                role="system",
                content="You are a voice assistant created by McDonald's. Your interface with users will be voice. Pretend we're having a conversation, no special formatting or headings, just natural speech.",
            )
        ]
    )
    # cartesia_voices: List[dict[str, Any]] = ctx.proc.userdata["cartesia_voices"]

    # tts = cartesia.TTS(
    #     model="sonic-2",
    # )
    
    tts = elevenlabs.tts.TTS(
        model="eleven_turbo_v2_5",
    )
    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=tts,
        chat_ctx=initial_ctx,
    )

    is_user_speaking = False
    is_agent_speaking = False

    @ctx.room.on("participant_attributes_changed")
    def on_participant_attributes_changed(
        changed_attributes: dict[str, str], participant: rtc.Participant
    ):
        print("Callback triggered with attributes:", changed_attributes)
        # # check for attribute changes from the user itself
        # if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD:
        #     return

        # if "voice" in changed_attributes:
        #     voice_id = participant.attributes.get("voice")
        #     logger.info(
        #         f"participant {participant.identity} requested voice change: {voice_id}"
        #     )
        #     if not voice_id:
        #         return

        #     voice_data = next(
        #         (voice for voice in cartesia_voices if voice["id"] == voice_id), None
        #     )
        #     if not voice_data:
        #         logger.warning(f"Voice {voice_id} not found")
        #         return
        #     if "embedding" in voice_data:
        #         language = "en"
        #         if "language" in voice_data and voice_data["language"] != "en":
        #             language = voice_data["language"]
        #         tts._opts.voice = voice_data["embedding"]
        #         tts._opts.language = language
        #         # allow user to confirm voice change as long as no one is speaking
        
        
        nonlocal tts # Allow modification of the outer 'tts' variable

        # check for attribute changes from the user itself
        if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD:
            return

        if "voice" in changed_attributes:
            voice_id = participant.attributes.get("voice")
            try:
                logger.info(f"\n\n\nTTS voice_id: {voice_id}\n\n\n")
            except Exception as e:
                logger.error(f"Error updating TTS voice_id: {e}")
            
            logger.info(
                f"participant {participant.identity} requested voice change: {voice_id}"
            )
            if not voice_id:
                logger.warning("Received empty voice_id attribute.")
                return

            # --- ElevenLabs Voice Change Logic ---
            # Validate if the voice_id is known (optional but recommended)
            if not any(v["id"] == voice_id for v in ELEVENLABS_VOICES_LIST):
                 logger.warning(f"Voice ID {voice_id} not found in predefined list. Attempting to use anyway.")
                 # Optionally return here if you only want to allow known voices

            try:
                tts.voice_id = voice_id
                logger.info(f"TTS voice_id set to: {tts.voice_id}")

                if not (is_agent_speaking or is_user_speaking):
                    asyncio.create_task(
                        agent.say("How do I sound now?", allow_interruptions=True)
                    )
            except Exception as e:
                 logger.error(f"Failed to update ElevenLabs voice ID: {e}")
                

    await ctx.connect()

    @agent.on("agent_started_speaking")
    def agent_started_speaking():
        nonlocal is_agent_speaking
        is_agent_speaking = True

    @agent.on("agent_stopped_speaking")
    def agent_stopped_speaking():
        nonlocal is_agent_speaking
        is_agent_speaking = False

    @agent.on("user_started_speaking")
    def user_started_speaking():
        nonlocal is_user_speaking
        is_user_speaking = True

    @agent.on("user_stopped_speaking")
    def user_stopped_speaking():
        nonlocal is_user_speaking
        is_user_speaking = False

    # set voice listing as attribute for UI
    # voices = []
    # for voice in cartesia_voices:
    #     voices.append(
    #         {
    #             "id": voice["id"],
    #             "name": voice["name"],
    #         }
    #     )
    # voices.sort(key=lambda x: x["name"])
    voices = sorted(ELEVENLABS_VOICES_LIST, key=lambda x: x["name"])
    await ctx.room.local_participant.set_attributes({"voices": json.dumps(voices)})

    agent.start(ctx.room)
    await agent.say("Hi there, how are you doing today?", allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
