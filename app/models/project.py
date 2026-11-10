from enum import Enum
from typing import Optional, List
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
    metadata_file_path: Optional[str] = None

# 3. Modelo de Metadatos SEO y Empaquetado para YouTube (Funcionalidad 5)
class YouTubeMetadata(BaseModel):
    title_options: List[str] = Field(
        default_factory=list,
        description="Exactamente 3 opciones de título atractivas y de alto CTR (máximo 60 caracteres cada una)."
    )
    description_body: str = Field(
        default="",
        description="Descripción persuasiva de 2 párrafos optimizada para SEO en YouTube."
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Exactamente 10 etiquetas (tags) relevantes de alto volumen de búsqueda."
    )
    thumbnail_idea: str = Field(
        default="",
        description="Idea detallada para la miniatura: composición visual, texto corto de impacto (2-3 palabras) y contraste de color."
    )

# 4. Modelo de Escena (compatible con Gemini, TTS, FFmpeg y Frontend)
class Scene(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    order: int
    chapter_title: str = ""  # Título corto del capítulo para marcas de tiempo de YouTube
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

# 5. Modelo de Configuración del Proyecto
class ProjectSettings(BaseModel):
    aspect_ratio: str = "16:9"  # MVP fijado en 16:9 horizontal (stub preparado para 9:16)
    visual_style: str = "cinematic"
    target_duration: Optional[float] = None  # En segundos si el usuario lo especificó
    narration_language: str = "es"
    voice_id: str = "es-ES-AlvaroNeural"
    voice_speed: float = 1.10  # Factor multiplicador (+10% dinamismo por defecto)
    voice_pitch: float = -2.0  # Ajuste de tono (-2Hz profundidad documental por defecto)
    audio_mode: str = "ai"  # "ai" o "custom"
    enable_ken_burns: bool = True
    enable_subtitles: bool = True  # Subtítulos dinámicos .ass quemados en 1080p
    transition_duration: float = 0.5  # Segundos

# 6. Modelo Principal de Proyecto
class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    video_title: str = ""
    full_script: str = ""
    voice: Optional[str] = "es-ES-AlvaroNeural"  # Sincronizado con settings.voice_id
    status: str = TaskStatus.IDLE.value  # idle, processing, completed, failed, cancelled, draft, etc.
    current_step: int = 1  # Etapa del asistente UI (1 a 6)
    progress: int = Field(default=0, ge=0, le=100)
    step_message: str = ""  # Texto descriptivo de la tarea en segundo plano
    error_message: Optional[str] = None
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    scenes: List[Scene] = Field(default_factory=list)
    youtube_metadata: Optional[YouTubeMetadata] = None
    metadata_file_path: Optional[str] = None
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

# 7. Esquema para la respuesta estructurada de Gemini al dividir el guion + Metadatos YouTube
class GeminiSceneItem(BaseModel):
    scene_number: int = Field(description="Número correlativo de la escena, empezando en 1")
    chapter_title: str = Field(description="Título corto y atractivo para el capítulo de YouTube de esta escena (máx 45 caracteres).")
    exact_script_fragment: str = Field(description="Fragmento textual EXACTO del guion original. NO resumir ni alterar.")
    visual_description: str = Field(description="Descripción visual detallada de lo que aparece en pantalla.")
    image_prompt: str = Field(description="Prompt optimizado en inglés o español para generar la imagen con IA (detallando sujeto, iluminación, fondo y estilo).")
    estimated_duration_seconds: float = Field(description="Duración estimada de lectura del fragmento en segundos.")
    suggested_transition: str = Field(description="Tipo de transición cinematográfica sugerida: fade, dissolve, zoom_in, pan_left o cut.")
    narrative_context: str = Field(description="Breve nota de continuidad con la escena previa y posterior.")

class GeminiScriptAnalysisResult(BaseModel):
    scenes: List[GeminiSceneItem] = Field(description="Lista ordenada y completa de todas las escenas que cubren el 100% del guion.")
    youtube_metadata: YouTubeMetadata = Field(description="Metadatos SEO completos para publicar el video en YouTube.")
