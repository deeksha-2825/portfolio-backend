import asyncio
from edge_tts import Communicate
import base64

async def test():
    text = "Hello, testing."
    communicate = Communicate(text, "en-US-AriaNeural")
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    print("Audio bytes length:", len(audio_data))
    
asyncio.run(test())
