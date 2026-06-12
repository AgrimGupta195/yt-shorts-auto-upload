from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = ""
    huggingface_api_key: str = ""
    hf_image_model: str = "black-forest-labs/FLUX.1-schnell"

    deapi_api_key: str = ""
    deapi_image_model: str = "Flux1schnell"

    pollinations_api_key: str = ""
    pollinations_model: str = "flux"
    pollinations_rate_limit_seconds: float = 16.0

    image_provider: str = "auto"
    image_gen_width: int = 768
    image_gen_height: int = 1344

    edge_tts_voice: str = "en-US-GuyNeural"
    tts_max_retries: int = 4
    tts_retry_delay_seconds: float = 3.0
    tts_request_delay_seconds: float = 1.0

    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_client_secrets_file: str = "client_secrets.json"
    youtube_token_file: str = "youtube_token.json"

    output_dir: Path = Path("output")
    topic: str = ""
    upload_to_youtube: bool = True
    cleanup_output_after_upload: bool = True

    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30

    subtitle_font_size: int = 18
    subtitle_margin_v: int = 220
    subtitle_margin_lr: int = 90
    subtitle_max_chars_per_line: int = 24
    subtitle_max_lines: int = 3
    subtitle_max_words_per_chunk: int = 5


settings = Settings()
