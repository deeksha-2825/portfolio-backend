from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from groq import Groq
import os
import json
import base64
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from collections import defaultdict
import tempfile
from faster_whisper.audio import decode_audio
from silero_vad import load_silero_vad, get_speech_timestamps
import asyncio
from edge_tts import Communicate
import time

load_dotenv()

# Initialize Groq client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Path to resume context — read fresh on every request so edits take effect without restart
context_path = os.path.join(os.path.dirname(__file__), "context.txt")

def load_context() -> str:
    with open(context_path, "r") as f:
        return f.read()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "AI Backend is running!"}

@app.get("/greet")
async def greet():
    """Return greeting audio played when the user clicks Talk to me."""
    text = "Hi! What would you like to know about Deeksha?"
    audio_bytes = await generate_tts(text)
    return {"text": text, "audio": base64.b64encode(audio_bytes).decode("utf-8")}

@app.get("/reset")
def reset_limits(request: Request):
    forwarded = request.headers.get("X-Forwarded-For")
    client_ip = forwarded.split(",")[0].strip() if forwarded else request.client.host
    user_requests[client_ip] = []
    return {"message": "Limit reset for your IP!"}

class ChatRequest(BaseModel):
    message: str

# Shared rate limiter (Rolling window)
user_requests = defaultdict(list)
MAX_QUESTIONS_PER_HOUR = 40

def is_rate_limited(client_ip: str) -> bool:
    current_time = time.time()
    # Filter out requests older than 1 hour (3600 seconds)
    user_requests[client_ip] = [req_time for req_time in user_requests[client_ip] if current_time - req_time < 3600]

    if len(user_requests[client_ip]) >= MAX_QUESTIONS_PER_HOUR:
        return True

    # Record prompt time
    user_requests[client_ip].append(current_time)
    return False

# Initialize Silero VAD
vad_model = load_silero_vad()

def get_ai_response(user_message: str, chat_count: int = 1):
    strict_instruction = (
        "STRICT RULES — follow every one without exception:\n"
        "1. Keep your answer to 2-3 sentences maximum. Never go longer.\n"
        "2. NEVER hallucinate, invent, or guess any detail. Only state facts that are explicitly written in the context document.\n"
        "3. If the answer is not in the context document, say exactly: 'I don't have that detail — you can email Deeksha at deeksharamakrishna6@gmail.com to find out more.'\n"
        "4. Never mention booking a call, scheduling, or interviews. The only action you may suggest is emailing Deeksha to discuss futher.\n"
        "5. Be direct and conversational. No filler phrases, no long introductions."
    )
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": load_context() + "\n\n" + strict_instruction},
            {"role": "user", "content": user_message}
        ]
    )
    return response.choices[0].message.content

def _groq_transcribe(audio_path: str) -> str:
    ext = audio_path.rsplit(".", 1)[-1]
    mime = "audio/mp4" if ext == "mp4" else "audio/webm"
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(os.path.basename(audio_path), f, mime),
            model="whisper-large-v3-turbo",
            response_format="json",
        )
    return (result.text or "").strip()

async def transcribe_audio(audio_path: str) -> str:
    return await asyncio.to_thread(_groq_transcribe, audio_path)

async def generate_tts(text: str) -> bytes:
    """Generate audio using Edge TTS and return MP3 bytes."""
    communicate = Communicate(text, "en-US-AriaNeural")
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return audio_data

@app.post("/chat")
async def chat_with_bot(request: ChatRequest, fastapi_req: Request):
    try:
        forwarded = fastapi_req.headers.get("X-Forwarded-For")
        client_ip = forwarded.split(",")[0].strip() if forwarded else fastapi_req.client.host

        message_lower = request.message.strip().lower()
        is_greeting = message_lower in ["hi", "hi.", "hello", "hello.", "hey", "hey."]

        if not is_greeting and len(request.message.strip()) < 5:
            return {"reply": "Could you please elaborate your question?"}

        if is_rate_limited(client_ip):
            return {"reply": "Whoa, you're chatting fast! To protect my backend infrastructure, I've paused this session. Please email me to chat more!"}

        chat_count = len(user_requests[client_ip])
        ai_reply = get_ai_response(request.message, chat_count=chat_count)

        return {"reply": ai_reply}

    except Exception as e:
        return {"reply": f"Sorry, I ran into an architecture error: {str(e)}"}

@app.websocket("/ws/voice")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_ip = websocket.client.host
    audio_ext = "webm"  # updated by client format announcement

    try:
        while True:
            message = await websocket.receive()

            # Text message = format announcement {"format": "mp4"} or {"format": "webm"}
            if "text" in message:
                try:
                    info = json.loads(message["text"])
                    if "format" in info:
                        audio_ext = info["format"]
                        print(f"Audio format set to: {audio_ext}")
                except Exception:
                    pass
                continue

            data = message.get("bytes", b"")
            if not data:
                continue
            print(f"Received audio bytes: {len(data)}")

            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{audio_ext}") as temp_audio:
                temp_audio.write(data)
                temp_audio_name = temp_audio.name

            try:
                # 1. Voice Activity Detection to ignore noise/breathing
                try:
                    audio_array = decode_audio(temp_audio_name, sampling_rate=16000)
                except Exception as ex:
                    print("FFmpeg Decode Error:", ex)
                    await websocket.send_text("IGNORE")
                    continue
                speech_timestamps = get_speech_timestamps(audio_array, vad_model, sampling_rate=16000, min_speech_duration_ms=100)

                if not speech_timestamps:
                    # Pure noise or silence, ignore entirely!
                    await websocket.send_text("IGNORE")
                    continue

                # 2. Transcribe using Groq Whisper API
                try:
                    transcription = await transcribe_audio(temp_audio_name)
                except Exception as transcribe_err:
                    print(f"Groq transcription error: {transcribe_err}")
                    await websocket.send_text("IGNORE")
                    continue
                transcription_lower = transcription.lower().strip()

                print(f"DEBUG TRANSCRIPTION: '{transcription}'")

                # 3. Filter hallucinations
                hallucinations = ["thank you.", "thanks for watching.", "okay.", "yeah.", "you", "ok.", "ok", "bye.", "thank you"]
                if transcription_lower in hallucinations or len(transcription) < 2:
                    is_noise = True
                    is_closing = False
                else:
                    is_noise = False
                    is_closing = any(phrase in transcription_lower for phrase in [
                        "thank you goodbye", "thanks goodbye", "thanks bye", "bye bye", "goodbye"
                    ]) or (transcription_lower in ["thank you!", "thanks!", "bye!", "goodbye!"])

                if is_closing:
                    msg = "You're welcome! Have a great day, and feel free to reach out to Deeksha at deeksharamakrishna6@gmail.com if you need anything else."
                    audio_bytes = await generate_tts(msg)
                    await websocket.send_text(json.dumps({
                        "type": "close",
                        "text": msg,
                        "audio": base64.b64encode(audio_bytes).decode('utf-8')
                    }))
                elif not is_noise:
                    is_greeting = transcription_lower.replace(",", "").replace("!", "").strip() in ["hello", "hello.", "hi", "hi.", "hey", "hey.", "hi there", "hi there."]

                    if not is_greeting and is_rate_limited(client_ip):
                        msg = "Whoa, you're chatting fast! To protect my backend infrastructure, I've paused this session. Please email me to chat more!"
                        audio_bytes = await generate_tts(msg)
                        await websocket.send_text(json.dumps({
                            "type": "limit",
                            "text": msg,
                            "audio": base64.b64encode(audio_bytes).decode('utf-8')
                        }))
                    else:
                        if is_greeting:
                            reply = "Hi! What would you like to know about Deeksha?"
                        else:
                            chat_count = len(user_requests[client_ip])
                            reply = get_ai_response(transcription, chat_count=chat_count)

                        # Generate natural voice TTS
                        try:
                            audio_bytes = await generate_tts(reply)
                            await websocket.send_text(json.dumps({
                                "type": "reply",
                                "user": transcription,
                                "text": reply,
                                "audio": base64.b64encode(audio_bytes).decode('utf-8')
                            }))
                        except Exception as e:
                            print(f"TTS Error: {e}")
                            await websocket.send_text(json.dumps({
                                "type": "reply",
                                "user": transcription,
                                "text": reply,
                                "audio": ""
                            }))
                else:
                    await websocket.send_text("IGNORE")

            finally:
                if os.path.exists(temp_audio_name):
                    os.remove(temp_audio_name)

    except WebSocketDisconnect:
        pass
    except Exception as general_error:
        print("UNHANDLED WEBSOCKET ERROR:", general_error)
