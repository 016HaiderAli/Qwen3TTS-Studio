export interface SpeakerInfo {
  id: string
  displayName: string
  description: string
  nativeLanguage: string
}

export const SPEAKERS: SpeakerInfo[] = [
  {
    id: "Vivian",
    displayName: "Vivian",
    description:
      "Vivian is a warm and engaging female voice with a bright, expressive tone. She speaks with natural prosody and is well-suited for storytelling, content narration, and audiobooks. Her delivery feels lively yet approachable, making her ideal for younger audiences and conversational content alike.",
    nativeLanguage: "English",
  },
  {
    id: "Serena",
    displayName: "Serena",
    description:
      "Serena is a calm and articulate female voice with a clear, confident delivery. She strikes a balance between professional and personable, making her a versatile choice for explainer videos, presentations, news reads, and any content that benefits from measured, authoritative narration.",
    nativeLanguage: "English",
  },
  {
    id: "Uncle_Fu",
    displayName: "Uncle Fu",
    description:
      "Uncle Fu is a deep, grandfatherly male voice with a warm and wise tone. He conveys authority and trustworthiness through slow, deliberate pacing and a resonant bass register. Perfect for historical narratives, motivational content, spiritual or philosophical material, and storytelling that benefits from gravitas.",
    nativeLanguage: "English",
  },
  {
    id: "Dylan",
    displayName: "Dylan",
    description:
      "Dylan is a smooth and charismatic male voice with an upbeat, energetic delivery. His youthful energy and natural pacing make him well-suited for entertainment content, social media narration, promotional videos, and any script that calls for a relatable and engaging male voice.",
    nativeLanguage: "English",
  },
  {
    id: "Eric",
    displayName: "Eric",
    description:
      "Eric is a steady and authoritative male voice with a clear, medium pitch and measured pacing. He conveys professionalism and trustworthiness, making him a solid choice for corporate narration, training materials, news delivery, and educational content that requires a neutral, reliable voice.",
    nativeLanguage: "English",
  },
  {
    id: "Ryan",
    displayName: "Ryan",
    description:
      "Ryan is a friendly and conversational male voice with a casual, approachable tone. His natural delivery feels like a knowledgeable friend explaining something, making him ideal for how-to guides, vlog-style narration, tech commentary, and any content that benefits from a relaxed, relatable voice.",
    nativeLanguage: "English",
  },
  {
    id: "Aiden",
    displayName: "Aiden",
    description:
      "Aiden is a soft-spoken male voice with a gentle, intimate quality. His whisper-like delivery creates an atmosphere of closeness, making him especially well-suited for bedtime stories, meditation guidance, audio journals, and any content that calls for a soothing, personal narration.",
    nativeLanguage: "English",
  },
  {
    id: "Ono_Anna",
    displayName: "Ono Anna",
    description:
      "Ono Anna is a bright and lively female voice with an expressive, anime-inspired character. Her dynamic tonal range and energetic delivery make her an excellent fit for character narration in animated content, game dialogue, and lively promotional material that demands personality and charm.",
    nativeLanguage: "Japanese",
  },
  {
    id: "Sohee",
    displayName: "Sohee",
    description:
      "Sohee is a warm and emotional female voice with a soft, melodic quality that conveys deep feeling. Her expressive delivery excels at delivering dialogue-driven narratives, audio drama, emotional storytelling, and any content where sincerity and emotional resonance are paramount.",
    nativeLanguage: "Korean",
  },
]

export function getSpeaker(id: string): SpeakerInfo | undefined {
  return SPEAKERS.find((s) => s.id === id)
}
