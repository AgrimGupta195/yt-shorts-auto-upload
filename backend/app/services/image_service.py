import base64
import io
import os
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


def _is_valid_deapi_key(key: str) -> bool:
    return key.startswith("dpn-sk-")


def _is_valid_pollinations_key(key: str) -> bool:
    return key.startswith("pk_") or key.startswith("sk_")


class ImageService:
    def __init__(self):
        self._last_pollinations_call = 0.0
        self._disabled_providers: set[str] = set()
        self.providers = self._resolve_providers()
        if not self.providers:
            raise RuntimeError(
                "No image provider available. Fix GitHub secrets:\n"
                "  DEAPI_API_KEY must start with dpn-sk- (from https://deapi.ai)\n"
                "  POLLINATIONS_API_KEY must start with pk_ or sk_ (from https://enter.pollinations.ai)"
            )
        print(f"   [image] Providers: {', '.join(self.providers)}")

    def _resolve_providers(self) -> list[str]:
        preference = settings.image_provider.lower()
        available: list[str] = []

        if settings.deapi_api_key:
            if _is_valid_deapi_key(settings.deapi_api_key):
                available.append("deapi")
            else:
                print(
                    "   [image] Skipping deapi: invalid key format "
                    "(expected dpn-sk-... from https://deapi.ai)"
                )

        if settings.pollinations_api_key:
            if _is_valid_pollinations_key(settings.pollinations_api_key):
                available.append("pollinations")
            else:
                print(
                    "   [image] Skipping pollinations: invalid key format "
                    "(expected pk_... or sk_... from https://enter.pollinations.ai)"
                )

        if settings.huggingface_api_key:
            available.append("huggingface")

        if preference == "deapi":
            return ["deapi"] if "deapi" in available else []
        if preference == "pollinations":
            return ["pollinations"] if "pollinations" in available else []
        if preference == "huggingface":
            return ["huggingface"] if settings.huggingface_api_key else []
        return available

    def _disable_provider(self, provider: str, reason: str) -> None:
        if provider not in self._disabled_providers:
            self._disabled_providers.add(provider)
            print(f"   [image] Disabled {provider} for this run: {reason}")

    def _active_providers(self) -> list[str]:
        return [p for p in self.providers if p not in self._disabled_providers]

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

    def _format_error(self, exc: Exception) -> str:
        message = str(exc).strip()
        return message or f"{type(exc).__name__} (no details)"

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
                return buffer.getvalue()
            except Exception as exc:
                last_error = exc
                print(f"   [image] Model {model} failed: {self._format_error(exc)[:120]}")

        if last_error:
            raise last_error
        raise RuntimeError("HuggingFace image generation failed")

    def _handle_provider_failure(self, provider: str, message: str) -> None:
        if provider == "deapi" and ("invalid_api_key" in message or "dpn-sk" in message):
            self._disable_provider(provider, "invalid API key format (need dpn-sk-...)")
        if provider == "huggingface" and "402" in message:
            self._disable_provider(provider, "monthly credits exhausted")

    def generate_image(self, prompt: str, output_path: Path, max_retries: int = 2) -> Path:
        enhanced_prompt = self._enhance_prompt(prompt)
        errors: list[str] = []

        for provider in self._active_providers():
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
                    self._handle_provider_failure(provider, message)
                    if provider in self._disabled_providers:
                        break
                    if attempt + 1 < max_retries:
                        time.sleep(3 * (attempt + 1))

        raise RuntimeError(
            "Image generation failed:\n- "
            + "\n- ".join(errors)
            + "\n\nFix GitHub secrets:\n"
            "  DEAPI_API_KEY = dpn-sk-... from https://deapi.ai\n"
            "  POLLINATIONS_API_KEY = sk-... from https://enter.pollinations.ai"
        )
