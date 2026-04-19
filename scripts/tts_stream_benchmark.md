# TTS `/generate/stream` benchmark

- Base URL: `http://127.0.0.1:17493`
- Endpoint: `/generate/stream`
- Text (51 chars): 'Hello, this is a short benchmark phrase for timing.'
- Cloned profile: `073e86e0-80f0-4ca3-abe4-c1493587b210`
- Kokoro preset profile: `(none — Kokoro rows skipped)`

## What “time to first byte” is here

- **HTTP TTFB** = time from starting the POST until the **first byte** of the response body arrives.

- **`/generate/stream`**:
  - The server runs **`generate_chunked()` to completion** (all text segments, crossfade), then encodes **one** WAV and streams it in 64 KiB slices (`backend/routes/generations.py`).
  - So TTFB ≈ **total synthesis + encode time**; it does **not** mean “first model audio chunk”.

**Streaming in Voicebox:** same `generate()` per text segment internally, but the client sees audio only after the **entire** utterance is ready.

| model_name | engine | model_size | time to first byte (s) | total (s) | bytes | error |
| --- | --- | --- | ---: | ---: | ---: | --- |
| qwen-tts-1.7B | qwen | 1.7B | 12.219 | 12.222 | 145964 |  |
| qwen-tts-0.6B | qwen | 0.6B | 8.594 | 8.596 | 149804 |  |
| qwen-custom-voice-1.7B | qwen_custom_voice | 1.7B | 14.828 | 14.828 | 188204 |  |
| qwen-custom-voice-0.6B | qwen_custom_voice | 0.6B |  |  | 0 | HTTP 400: {"detail":"Model 0.6B is not downloaded yet. Use /generate to trigger a download."} |
| luxtts | luxtts | default |  |  | 0 | HTTP 400: {"detail":"luxtts model is not downloaded yet. Use /generate to trigger a download."} |
| chatterbox-tts | chatterbox | default |  |  | 0 | HTTP 400: {"detail":"chatterbox model is not downloaded yet. Use /generate to trigger a download."} |
| chatterbox-turbo | chatterbox_turbo | default | 17.764 | 17.766 | 143084 |  |
| tada-1b | tada | 1B | 23.476 | 23.478 | 148832 |  |
| tada-3b-ml | tada | 3B |  |  | 0 | HTTP 400: {"detail":"Model 3B is not downloaded yet. Use /generate to trigger a download."} |
| kokoro | kokoro | default |  |  | 0 | no Kokoro preset profile (use --kokoro-profile-id or create a preset profile) |
