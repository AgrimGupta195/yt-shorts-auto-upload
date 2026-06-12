import json
import re

from openai import OpenAI

from app.config import settings
from app.models import ShortScript

SHORTS_SYSTEM_PROMPT = """You write scripts for viral YouTube Shorts (under 60 seconds when spoken) make new engaging stories every time.
Return ONLY valid JSON with this exact structure:
{
  "title": "catchy title under 70 chars",
  "description": "2-3 sentence description with hashtags at the end",
  "tags": ["tag1", "tag2", "tag3"],
  "segments": [
    {
      "text": "spoken narration for this scene (1-2 sentences)",
      "image_prompt": "photorealistic scene description for AI image generation"
    }
  ]
}
Rules:
- 4 to 6 segments total
- Hook in the first segment
- Conversational, energetic tone
- image_prompt must describe a real photograph (not illustration/cartoon), vivid and cinematic, no text in images
- No markdown, no code fences, only raw JSON"""


class ScriptService:
    def __init__(self):
        if not settings.groq_api_key:
            raise RuntimeError("Missing GROQ_API_KEY. Set it in backend/.env or the environment.")
        self.client = OpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

    def _parse_script(self, raw: str) -> ShortScript:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        data = json.loads(cleaned)
        return ShortScript.model_validate(data)

    def generate_script(self, topic: str | None = None) -> ShortScript:
        user_prompt = (
            f"Write a YouTube Short about: {topic}"
            if topic
            else "Pick a fascinating, surprising fact or story and write a YouTube Short about it."
        )
        response = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SHORTS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1500,
            temperature=0.7,
        )
        content = response.choices[0].message.content or ""
        return self._parse_script(content)
