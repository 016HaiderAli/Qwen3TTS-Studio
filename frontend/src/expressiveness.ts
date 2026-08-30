export interface ExpressivePreset {
  label: string
  instruct: string
}

export const EXPRESSIVE_PRESETS: ExpressivePreset[] = [
  {
    label: "Energetic & Cocky",
    instruct: "Speak with high energy, fast pace, and a sardonic, confident tone.",
  },
  {
    label: "Soft Whisper",
    instruct: "Whisper gently and softly, with a quiet and intimate breathy tone.",
  },
  {
    label: "Dramatic Scientist",
    instruct:
      "Speak with intense scientific enthusiasm, deliberate pauses, and sharp articulation.",
  },
  {
    label: "Calm Narrator",
    instruct: "Speak in a deep, measured, calm, and reassuring narration style.",
  },
  {
    label: "Fierce & Aggressive",
    instruct:
      "Deliver with gravelly, intense, aggressive pride and commanding authority.",
  },
]

export const DEMO_DIALOGUE_SCRIPT =
  "[Speaker: Ryan] Did you hear about the new open-source Qwen3-TTS engine? [Speaker: Serena] [instruct: Speak with warm curiosity] Yes! It runs local web UI with remote GPU worker pipelines seamlessly."

export function applyInstructPreset(
  currentInstruct: string,
  preset: ExpressivePreset,
  append = false,
): string {
  if (append) {
    const trimmed = currentInstruct.trim()
    return trimmed ? `${trimmed} ${preset.instruct}` : preset.instruct
  }
  return preset.instruct
}
