from silero_vad import load_silero_vad, get_speech_timestamps
import numpy as np

vad_model = load_silero_vad()

audio_array = np.random.randn(16000).astype(np.float32)
# from faster_whisper it's a numpy array
print(type(audio_array))
try:
    speech_timestamps = get_speech_timestamps(audio_array, vad_model, sampling_rate=16000)
    print("Timestamps:", speech_timestamps)
except Exception as e:
    print("Error:", e)
