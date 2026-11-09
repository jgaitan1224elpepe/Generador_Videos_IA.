from enum import Enum
from typing import Optional, List, Union
from pydantic import BaseModel, Field, field_validator
import time
import uuid

# 1. Enumeración explícita para el control de tareas en segundo plano
class TaskStatus(str, Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # Estados adicionales del flujo de estudio para compatibilidad total
    DRAFT = "draft"
    ANALYZED = "analyzed"
    IMAGES_GENERATED = "images_generated"
    AUDIO_READY = "audio_ready"
    RENDERED = "rendered"

# 2. Modelo de respuesta para el endpoint GET /api/projects/{id}/status
class ProjectStatusUpdate(BaseModel):
    status: TaskStatus
    progress: int = Field(default=0, ge=0, le=100)
    current_step: str = ""
    error_message: Optional[str] = None
    final_video_path: Optional[str] = None

# 3. Modelo de Escena (compatible con Gemini, TTS, FFmpeg y Frontend)
class Scene(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    order: int
    script_text: str = ""  # Fragmento exacto del guion sin modificaciones
    visual_description: str = ""  # Descripción visual de lo que debe verse
    image_prompt: str = ""  # Prompt detallado para el generador de imágenes
    image_path: Optional[str] = None  # Ruta relativa al proyecto
    image_status: str = "pending"  # pending, generating, approved, generated, failed
    duration: float = 4.0  # Duración calculada o fijada en segundos
    suggested_transition: str = "fade"  # fade, dissolve, zoom_in, pan_left, cut
    transition: str = "fade"
    context_notes: Optional[str] = ""  # Relación con escena anterior y posterior
    audio_path: Optional[str] = None  # Audio generado o recortado para esta escena
    audio_status: str = "pending"  # pending, generating, ready, custom_synced, failed

# 4. Modelo de Configuración del Proyecto
class ProjectSettings(BaseModel):
    aspect_ratio: str = "16:9"  # 16:9, 9:16, 1:1
    visual_style: str = "cinematic"
    target_duration: Optional[float] = None  # En segundos si el usuario lo especificó
    narration_language: str = "es"
    voice_id: str = "es-ES-AlvaroNeural"
    voice_speed: float = 1.0  # Factor multiplicador (1.0 = normal)
    voice_pitch: float = 0.0  # Ajuste de tono
    audio_mode: str = "ai"  # "ai" o "custom"
    enable_ken_burns: bool = True
    enable_subtitles: bool = True  # Subtítulos dinámicos .ass quemados en 1080p
    transition_duration: float = 0.5  # Segundos

# 5. Modelo Principal de Proyecto
class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    video_title: str = ""
    full_script: str = ""
    status: str = TaskStatus.IDLE.value  # idle, processing, completed, failed, cancelled, draft, etc.
    current_step: int = 1  # Etapa del asistente UI (1 a 6)
    progress: int = Field(default=0, ge=0, le=100)
    step_message: str = ""  # Texto descriptivo de la tarea en segundo plano
    error_message: Optional[str] = None
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    scenes: List[Scene] = Field(default_factory=list)
    custom_audio_path: Optional[str] = None
    full_audio_path: Optional[str] = None
    final_video_path: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @field_validator("current_step", mode="before")
    @classmethod
    def coerce_current_step(cls, v):
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
        return 1

    class Config:
        use_enum_values = True

# 6. Esquema para la respuesta estructurada de Gemini al dividir el guion
class GeminiSceneItem(BaseModel):
    scene_number: int = Field(description="Número correlativo de la escena, empezando en 1")
    exact_script_fragment: str = Field(description="Fragmento textual EXACTO del guion original. NO resumir ni alterar.")
    visual_description: str = Field(description="Descripción visual detallada de lo que aparece en pantalla.")
    image_prompt: str = Field(description="Prompt optimizado en inglés o español para generar la imagen con IA (detallando sujeto, iluminación, fondo y estilo).")
    estimated_duration_seconds: float = Field(description="Duración estimada de lectura del fragmento en segundos.")
    suggested_transition: str = Field(description="Tipo de transición cinematográfica sugerida: fade, dissolve, zoom_in, pan_left o cut.")
    narrative_context: str = Field(description="Breve nota de continuidad con la escena previa y posterior.")

class GeminiScriptAnalysisResult(BaseModel):
    scenes: List[GeminiSceneItem] = Field(description="Lista ordenada y completa de todas las escenas que cubren el 100% del guion.")
