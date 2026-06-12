import base64
import io
import time
import urllib.parse
from pathlib import Path

import requests
from huggingface_hub import InferenceClient
from openai import OpenAI
from PIL import Image

from app.config import settings

STYLE_SUFFIX = (
    "cinematic photorealistic photograph, dramatic lighting, ultra detailed, "
    "sharp focus, rich colors, vertical portrait composition, 9:16, "
    "no text, no watermark, no logo"
)
STYLE_NEGATIVE = (
    "cartoon, anime, illustration, drawing, painting, sketch, blurry, "
    "low quality, deformed, text, watermark, logo, ugly"
)
HF_FALLBACK_MODEL = "black-forest-labs/FLUX.1-schnell"


class ImageService:
    def __init__(self):
        self.providers = self._resolve_providers()
        if not self.providers:
            raise RuntimeError(
                "No image provider available. Add a free key:\n"
                "  - DEAPI_API_KEY from https://deapi.ai (free $5 credits)\n"
                "  - POLLINATIONS_API_KEY from https://enter.pollinations.ai (free flux)\n"
                "Or add HUGGINGFACE_API_KEY with paid Inference credits."
            )
        self._last_pollinations_call = 0.0

    def _resolve_providers(self) -> list[str]:
        preference = settings.image_provider.lower()
        available: list[str] = []
        if settings.deapi_api_key:
            available.append("deapi")
        if settings.pollinations_api_key or settings.image_provider == "pollinations":
            available.append("pollinations")
        if settings.huggingface_api_key:
            available.append("huggingface")
        if "pollinations" not in available:
            available.append("pollinations")

        if preference == "deapi":
            return ["deapi"] if settings.deapi_api_key else []
        if preference == "pollinations":
            return ["pollinations"]
        if preference == "huggingface":
            return ["huggingface"] if settings.huggingface_api_key else []
        return available

    def _enhance_prompt(self, prompt: str) -> str:
        return f"{prompt.strip().rstrip('.')}, {STYLE_SUFFIX}"

    def _fit_vertical(self, img: Image.Image, output_path: Path) -> Path:
        img = img.convert("RGB")
        target_ratio = settings.video_width / settings.video_height
        src_ratio = img.width / img.height

        if src_ratio > target_ratio:
            new_width = int(img.height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        else:
            new_height = int(img.width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))

        img = img.resize((settings.video_width, settings.video_height), Image.Resampling.LANCZOS)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, format="PNG", optimize=True)
        return output_path

    def _save_image_bytes(self, data: bytes, output_path: Path) -> Path:
        if len(data) < 1000:
            raise RuntimeError("Image response was too small")
        return self._fit_vertical(Image.open(io.BytesIO(data)), output_path)

    def _generate_deapi(self, prompt: str) -> bytes:
        client = OpenAI(
            api_key=settings.deapi_api_key,
            base_url="https://oai.deapi.ai/v1",
        )
        size = f"{settings.image_gen_width}x{settings.image_gen_height}"
        response = client.images.generate(
            model=settings.deapi_image_model,
            prompt=prompt,
            size=size,
            n=1,
        )
        item = response.data[0]
        if getattr(item, "b64_json", None):
            return base64.b64decode(item.b64_json)
        if getattr(item, "url", None):
            image_response = requests.get(item.url, timeout=120)
            image_response.raise_for_status()
            return image_response.content
        raise RuntimeError("deAPI returned no image data")

    def _generate_pollinations(self, prompt: str) -> bytes:
        if settings.pollinations_api_key:
            encoded = urllib.parse.quote(prompt, safe="")
            url = (
                f"https://gen.pollinations.ai/image/{encoded}"
                f"?model={settings.pollinations_model}"
                f"&width={settings.image_gen_width}"
                f"&height={settings.image_gen_height}"
                f"&nologo=true"
                f"&key={settings.pollinations_api_key}"
            )
            response = requests.get(url, timeout=180)
            if response.status_code == 200 and len(response.content) > 1000:
                return response.content
            raise RuntimeError(f"Pollinations error {response.status_code}: {response.text[:200]}")

        elapsed = time.time() - self._last_pollinations_call
        if elapsed < settings.pollinations_rate_limit_seconds:
            time.sleep(settings.pollinations_rate_limit_seconds - elapsed)

        encoded = urllib.parse.quote(prompt, safe="")
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?model={settings.pollinations_model}"
            f"&width={settings.image_gen_width}"
            f"&height={settings.image_gen_height}"
            f"&nologo=true"
        )
        response = requests.get(url, timeout=180)
        self._last_pollinations_call = time.time()

        if response.status_code == 200 and len(response.content) > 1000:
            return response.content

        if response.status_code in (401, 402):
            raise RuntimeError(
                "Pollinations requires a free API key for CI/server use. "
                "Sign up at https://enter.pollinations.ai and set POLLINATIONS_API_KEY."
            )
        raise RuntimeError(f"Pollinations error {response.status_code}: {response.text[:200]}")

    def _format_error(self, exc: Exception) -> str:
        message = str(exc).strip()
        if message:
            return message
        return f"{type(exc).__name__} (no details)"

    def _generate_huggingface(self, prompt: str) -> bytes:
        client = InferenceClient(
            api_key=settings.huggingface_api_key,
            provider="auto",
        )
        models = [settings.hf_image_model]
        if settings.hf_image_model != HF_FALLBACK_MODEL:
            models.append(HF_FALLBACK_MODEL)

        last_error: Exception | None = None
        for model in models:
            try:
                image = client.text_to_image(
                    prompt,
                    model=model,
                    width=settings.image_gen_width,
                    height=settings.image_gen_height,
                    negative_prompt=STYLE_NEGATIVE,
                )
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                if model != settings.hf_image_model:
                    print(f"   [image] Fallback model worked: {model}")
                return buffer.getvalue()
            except Exception as exc:
                last_error = exc
                print(f"   [image] Model {model} failed: {self._format_error(exc)[:120]}")

        if last_error:
            raise last_error
        raise RuntimeError("HuggingFace image generation failed")

    def generate_image(self, prompt: str, output_path: Path, max_retries: int = 2) -> Path:
        enhanced_prompt = self._enhance_prompt(prompt)
        errors: list[str] = []

        for provider in self.providers:
            for attempt in range(max_retries):
                try:
                    print(f"   [image] {provider} (attempt {attempt + 1})...")
                    if provider == "deapi":
                        data = self._generate_deapi(enhanced_prompt)
                    elif provider == "pollinations":
                        data = self._generate_pollinations(enhanced_prompt)
                    else:
                        data = self._generate_huggingface(enhanced_prompt)
                    result = self._save_image_bytes(data, output_path)
                    print(f"   [image] Saved via {provider}")
                    return result
                except Exception as exc:
                    message = self._format_error(exc)
                    errors.append(f"{provider}: {message}")
                    print(f"   [image] {provider} failed: {message[:200]}")
                    if attempt + 1 < max_retries:
                        time.sleep(3 * (attempt + 1))

        raise RuntimeError(
            "Image generation failed:\n- "
            + "\n- ".join(errors)
            + "\n\nFree fix for GitHub Actions: add DEAPI_API_KEY or POLLINATIONS_API_KEY to secrets."
        )
