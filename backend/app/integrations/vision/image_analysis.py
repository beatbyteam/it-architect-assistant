from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.integrations.openai_compatible import resolve_openai_compatible_endpoint

IMAGE_FILE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg", "image/webp"})


@dataclass(slots=True)
class ImageAnalysisResult:
    text: str
    parser_name: str
    model_id: str | None = None
    warning: str | None = None


def is_supported_image_file(filename: str | None, media_type: str | None = None) -> bool:
    normalized_media = (media_type or "").split(";")[0].strip().lower()
    if normalized_media in IMAGE_MEDIA_TYPES:
        return True
    suffix = Path(filename or "").suffix.lower()
    return suffix in IMAGE_FILE_EXTENSIONS


def analyze_task_input_image(
    data: bytes,
    *,
    filename: str,
    media_type: str | None,
    settings: Settings,
) -> ImageAnalysisResult:
    provider = (settings.vision_provider or "").strip().lower()
    model_id = (settings.vision_model_id or "").strip()
    if provider in {"", "disabled"} or not settings.vision_base_url or not model_id:
        return _fallback_result(
            filename=filename,
            model_id=model_id or None,
            reason=(
                "vision-модель не настроена. Укажите VISION_PROVIDER, "
                "VISION_BASE_URL и VISION_MODEL_ID, чтобы автоматически "
                "описывать содержимое изображения."
            ),
        )

    if provider not in {"openai_compatible", "local_openai_compatible", "ollama"}:
        return _fallback_result(
            filename=filename,
            model_id=model_id,
            reason=f"провайдер {settings.vision_provider!r} не поддерживается",
        )

    prompt = (
        "Опиши изображение как входные данные для ИТ-архитектора. "
        "Если это схема, выдели компоненты, интеграции, "
        "потоки данных, подписи, технологии, роли и заметные риски. "
        "Не выдумывай невидимые детали; "
        "если текст на изображении не читается, явно напиши об этом."
    )
    payload: dict[str, Any] = {
        "model": model_id,
        "temperature": 0.0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": _image_data_url(
                                data, filename=filename, media_type=media_type
                            )
                        },
                    },
                ],
            }
        ],
    }
    headers = {"Content-Type": "application/json"}
    api_key = (settings.vision_api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        url = resolve_openai_compatible_endpoint(
            base_url=settings.vision_base_url,
            endpoint_path="/chat/completions",
            dependency_name="vision_base_url",
            missing_message="VISION_BASE_URL is required for vision provider",
        )
        with httpx.Client(timeout=settings.vision_timeout_sec) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
    except Exception as exc:
        return _fallback_result(
            filename=filename,
            model_id=model_id,
            reason=f"vision-анализ не выполнился: {exc}",
        )

    text = _extract_message_text(body).strip()
    if not text:
        return _fallback_result(
            filename=filename,
            model_id=model_id,
            reason="vision-модель вернула пустое описание",
        )
    return ImageAnalysisResult(text=text, parser_name=f"{provider}_vision", model_id=model_id)


def _fallback_result(*, filename: str, model_id: str | None, reason: str) -> ImageAnalysisResult:
    text = "\n".join(
        [
            f"Изображение: {filename}",
            "",
            "Автоматическое описание изображения не получено.",
            f"Причина: {reason}",
            "",
            (
                "Перед запуском добавьте текстовое описание схемы: "
                "компоненты, связи, потоки данных, технологии, "
                "ограничения и риски."
            ),
        ]
    )
    return ImageAnalysisResult(
        text=text,
        parser_name="image_import_fallback",
        model_id=model_id,
        warning=reason,
    )


def _image_data_url(data: bytes, *, filename: str, media_type: str | None) -> str:
    normalized_media = (media_type or "").split(";")[0].strip().lower()
    if normalized_media not in IMAGE_MEDIA_TYPES:
        normalized_media = _media_type_from_suffix(filename)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{normalized_media};base64,{encoded}"


def _media_type_from_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def _extract_message_text(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""
