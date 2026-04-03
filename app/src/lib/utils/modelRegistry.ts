/**
 * Maps `/models/status` registry `model_name` → `/generate` and `/generate/stream` fields.
 *
 * Rule: **`model_name`** is the download/registry id (`POST /models/download`).
 * **`engine`** + optional **`model_size`** are what generation endpoints accept — they are not the same string.
 *
 * - Qwen / Qwen CustomVoice / TADA: multiple registry rows → set both `engine` and `model_size`.
 * - LuxTTS, Chatterbox, Chatterbox Turbo, Kokoro: one row each → only `engine` (omit `model_size` or rely on server defaults).
 * - Whisper `model_name` values are STT only → not valid for TTS stream (`null`).
 */
import type { GenerationRequest } from '@/lib/api/types';

export type GenerateStreamEngineFields = Pick<GenerationRequest, 'engine' | 'model_size'>;

const WHISPER_PREFIX = 'whisper-';

/** Registry `model_name` → `{ engine, model_size? }` for generation. Keep in sync with `backend/backends/__init__.py` TTS configs. */
const MODEL_NAME_TO_GENERATE: Record<string, GenerateStreamEngineFields> = {
  'qwen-tts-1.7B': { engine: 'qwen', model_size: '1.7B' },
  'qwen-tts-0.6B': { engine: 'qwen', model_size: '0.6B' },
  'qwen-custom-voice-1.7B': { engine: 'qwen_custom_voice', model_size: '1.7B' },
  'qwen-custom-voice-0.6B': { engine: 'qwen_custom_voice', model_size: '0.6B' },
  luxtts: { engine: 'luxtts' },
  'chatterbox-tts': { engine: 'chatterbox' },
  'chatterbox-turbo': { engine: 'chatterbox_turbo' },
  'tada-1b': { engine: 'tada', model_size: '1B' },
  'tada-3b-ml': { engine: 'tada', model_size: '3B' },
  kokoro: { engine: 'kokoro' },
};

/**
 * Convert a `ModelStatus.model_name` from `/models/status` into `engine` / `model_size` for `/generate/stream`.
 * Returns `null` for unknown names or Whisper (STT) models.
 */
export function streamParamsFromModelName(modelName: string): GenerateStreamEngineFields | null {
  if (modelName.startsWith(WHISPER_PREFIX)) {
    return null;
  }
  const row = MODEL_NAME_TO_GENERATE[modelName];
  if (!row) {
    return null;
  }
  return { ...row };
}
