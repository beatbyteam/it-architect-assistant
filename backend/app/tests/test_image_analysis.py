from __future__ import annotations

from app.core.config import Settings
from app.integrations.vision.image_analysis import (
    analyze_task_input_image,
    is_supported_image_file,
)


def test_supported_image_detection_uses_media_type_and_suffix() -> None:
    assert is_supported_image_file("scheme.bin", "image/png") is True
    assert is_supported_image_file("scheme.webp", None) is True
    assert is_supported_image_file("scheme.txt", "text/plain") is False


def test_image_analysis_returns_actionable_fallback_when_disabled() -> None:
    result = analyze_task_input_image(
        b"fake-image",
        filename="schema.png",
        media_type="image/png",
        settings=Settings(VISION_PROVIDER="disabled"),
    )

    assert result.parser_name == "image_import_fallback"
    assert "Автоматическое описание изображения не получено" in result.text
    assert "schema.png" in result.text


def test_image_analysis_calls_openai_compatible_vision(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "На схеме показаны frontend, backend и PostgreSQL."
                        }
                    }
                ]
            }

    class _Client:
        def __init__(self, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> _Response:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _Response()

    monkeypatch.setattr("app.integrations.vision.image_analysis.httpx.Client", _Client)

    result = analyze_task_input_image(
        b"fake-image",
        filename="schema.png",
        media_type="image/png",
        settings=Settings(
            VISION_PROVIDER="openai_compatible",
            VISION_BASE_URL="http://vision:11434/v1",
            VISION_API_KEY="secret",
            VISION_MODEL_ID="qwen2.5vl:7b",
            VISION_TIMEOUT_SEC=33,
        ),
    )

    assert result.parser_name == "openai_compatible_vision"
    assert result.model_id == "qwen2.5vl:7b"
    assert "frontend, backend" in result.text
    assert captured["timeout"] == 33
    assert captured["url"] == "http://vision:11434/v1/chat/completions"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer secret",
    }
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "qwen2.5vl:7b"
