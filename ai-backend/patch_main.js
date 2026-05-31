const fs = require('fs');

const path = '/Users/deeksha_ramakrishna/Desktop/portfolio-deeksha/ai-backend/main.py';
let data = fs.readFileSync(path, 'utf8');

const oldBlock = `            try:
                # 1. Voice Activity Detection to ignore noise/breathing
                audio_array = decode_audio(temp_audio_name, sampling_rate=16000)
                speech_timestamps = get_speech_timestamps(audio_array, vad_model, sampling_rate=16000)`;

const newBlock = `            try:
                # 1. Voice Activity Detection to ignore noise/breathing
                try:
                    audio_array = decode_audio(temp_audio_name, sampling_rate=16000)
                except Exception as ex:
                    print("FFmpeg Decode Error:", ex)
                    await websocket.send_text("IGNORE")
                    continue
                speech_timestamps = get_speech_timestamps(audio_array, vad_model, sampling_rate=16000)`;
data = data.replace(oldBlock, newBlock);

fs.writeFileSync(path, data);
