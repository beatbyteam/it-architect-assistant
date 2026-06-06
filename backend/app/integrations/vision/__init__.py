from __future__ import annotations

from app.integrations.vision.image_analysis import (
    IMAGE_FILE_EXTENSIONS,
    ImageAnalysisResult,
    analyze_task_input_image,
    is_supported_image_file,
)

analyze_knowledge_document_image = analyze_task_input_image

__all__ = [
    "IMAGE_FILE_EXTENSIONS",
    "ImageAnalysisResult",
    "analyze_knowledge_document_image",
    "analyze_task_input_image",
    "is_supported_image_file",
]
