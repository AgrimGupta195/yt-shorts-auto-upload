from pydantic import BaseModel, Field


class ScriptSegment(BaseModel):
    text: str
    image_prompt: str


class ShortScript(BaseModel):
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    segments: list[ScriptSegment]


class SegmentAsset(BaseModel):
    index: int
    text: str
    image_prompt: str
    audio_path: str
    image_path: str
    duration_seconds: float
