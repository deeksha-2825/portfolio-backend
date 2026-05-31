from faster_whisper.audio import decode_audio
from silero_vad import load_silero_vad, get_speech_timestamps
import torch

vad_model = load_silero_vad()
print("VAD model loaded")
