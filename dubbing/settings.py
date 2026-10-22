import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .languages import LANGUAGES, validate_language

ASR_MODEL = "mlx-community/whisper-large-v3-turbo"
TRANSLATION_MODEL = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
TTS_MODELS = {
    "balanced": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
    "quality": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
}
INDEXTTS_MODEL = "vanch007/mlx-indextts2-2.5-8bit"
INDEXTTS_REVISION = "3170ceff8032ab6d0c2945e72068a03ea8c68461"


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str
    quality: str = Field(default="balanced", pattern="^(balanced|quality)$")
    tts_engine: str = Field(default="qwen", pattern="^(qwen|indextts25)$")
    emotion_strength: float = Field(default=0.8, ge=0, le=1)
    indextts_text_tokens: int = Field(default=40, ge=20, le=40)
    reference_mode: str = Field(default="passage", pattern="^(passage|stable)$")
    translation_engine: str = Field(default="hymt", pattern="^(qwen|opus|madlad|hymt)$")
    translation_context: str = Field(default="",max_length=2000)
    semantic_translation: bool = True
    max_semantic_seconds: float = Field(default=60,ge=25,le=90)
    source_language: str = Field(default="en", pattern="^(en|auto)$")
    temperature: float = Field(default=0.6, ge=0.1, le=1.2)
    max_segment_seconds: float = Field(default=15, ge=5, le=25)
    pause_threshold: float = Field(default=0.65, ge=0.2, le=2)
    max_speedup: float = Field(default=1.2, ge=1, le=1.35)
    timing: str = Field(default="natural", pattern="^(natural|aligned)$")
    gap_audio: str = Field(default="ambient", pattern="^(ambient|original|silence)$")
    seed: int = Field(default=42, ge=0, le=2147483647)
    synthesis_retries: int = Field(default=2, ge=0, le=2)
    audio_enhancement: bool = True
    enhancement_strength: str = Field(default="gentle", pattern="^(gentle|balanced|strong)$")

    @model_validator(mode='after')
    def supported_target(self):
        validate_language(self.language, self.tts_engine, self.translation_engine, self.quality)
        return self


def options_for_job(job):
    # Jobs created before complete-thought mode keep their original audio slots.
    values={"semantic_translation":False,"audio_enhancement":False,**job['options']}
    return Options(**values)


def home() -> Path:
    desktop = os.environ.get('DUBBING_DESKTOP_WORKSPACE')
    if desktop:
        workspace = Path(desktop).expanduser()
        if not workspace.is_absolute():
            raise RuntimeError('Desktop workspace must be an absolute path')
        workspace = workspace.resolve()
        # Never silently replace a disconnected user-selected workspace.
        if not workspace.is_dir():
            raise RuntimeError('Selected desktop workspace is unavailable')
        path = workspace / 'Jobs'
        configured = os.environ.get('DUBBING_HOME')
        if configured and Path(configured).resolve() != path:
            raise RuntimeError('Desktop and backend storage settings disagree')
        path.mkdir(exist_ok=True)
        return path
    value = os.environ.get("DUBBING_HOME", str(Path.home()/"Library/Application Support/LocalDub/Jobs"))
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RuntimeError("DUBBING_HOME must be an absolute path")
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
