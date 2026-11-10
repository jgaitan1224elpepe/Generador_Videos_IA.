import io
import json
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple, Literal
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFont

from app.config import get_gemini_api_key, VISUAL_STYLES, ASPECT_RATIOS, BASE_DIR
from app.models.project import (
    Project,
    Scene as ProjectScene,
    YouTubeMetadata,
    GeminiScriptAnalysisResult,
)
from app.services.storage import save_scene_image, ensure_project_dirs
from app.services.tts_service import get_audio_duration_ffprobe

# =====================================================================
# 1. ESQUEMAS ESTRICTOS PYDANTIC PARA MOTOR MOVIEPY ("CASUALLY EXPLAINED")
# =====================================================================

class Scene(BaseModel):
    """
    Modelo estricto de escena para el motor minimalista estilo 'Casually Explained'.
    """
    id: int = Field(description="Identificador numérico secuencial de la escena (1, 2, 3...).")
    texto_narracion: str = Field(description="Fragmento exacto del guion que dirá la voz del narrador.")
    emocion_personaje: Literal["normal", "feliz", "triste", "sorprendido"] = Field(
        default="normal",
        description="Emoción del personaje SVG (debe ser exactamente: 'normal', 'feliz', 'triste' o 'sorprendido')."
    )
    texto_pantalla: str = Field(
        default="",
        description="Texto corto humorístico o sarcástico para mostrar en la parte superior de la pantalla (puede estar vacío)."
    )
    prop_svg_codigo: str = Field(
        description="Código <svg> puro minimalista estilo line-art negro (viewBox='0 0 400 400', sin fondo) que ilustre la utilería/prop de la escena."
    )


class ScriptResponse(BaseModel):
    """
    Respuesta estructurada de Gemini con la lista completa de escenas para MoviePy.
    """
    scenes: List[Scene] = Field(description="Lista ordenada de escenas para ensamblar en MoviePy.")


# Lista de modelos de texto ordenados por preferencia con fallback automático
TEXT_MODELS_CASCADE = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-flash-latest"
]

# Lista de modelos de imagen
IMAGE_MODELS_CASCADE = [
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image"
]


def analyze_script_for_moviepy(script_text: str) -> ScriptResponse:
    """
    Analiza un guion completo con Gemini y devuelve un objeto 'ScriptResponse'
    validado con Pydantic para el motor de animación 'Casually Explained' (MoviePy + SVG).
    """
    api_key = get_gemini_api_key()
    if not api_key:
        raise ValueError("Clave de API de Gemini no configurada en .env (GEMINI_API_KEY).")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    prompt = f"""Eres el director creativo y guionista visual de un canal estilo 'Casually Explained' / 'Casually Finance'.
Tu tarea es dividir el siguiente guion en escenas estructuradas para un motor de animación minimalista sobre fondo blanco.

REGLAS ESTRICTAS DE SALIDA JSON (esquema ScriptResponse):
1. 'id': Número correlativo entero empezando en 1.
2. 'texto_narracion': Fragmento exacto del guion que pronunciará el narrador. No omitas ni resumas información del guion.
3. 'emocion_personaje': Elige únicamente uno de estos 4 valores exactos según el tono de la frase:
   - "normal"
   - "feliz"
   - "triste"
   - "sorprendido"
4. 'texto_pantalla': Frase muy breve e ingeniosa (máximo 5 palabras) para el rótulo superior de la escena (o cadena vacía "" si no requiere texto).
5. 'prop_svg_codigo': Código XML `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400">...</svg>` puro y válido, estilo dibujo de líneas negras ('stroke="#000000" stroke-width="8" fill="none"') con fondo 100% transparente que represente el objeto o concepto de la escena (ej. gráfica, reloj, moneda, flecha, cohete, libro).

GUION A PROCESAR:
\"\"\"
{script_text}
\"\"\"
"""

    last_error = None
    for model_name in TEXT_MODELS_CASCADE:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ScriptResponse,
                    temperature=0.2,
                ),
            )
            if response.parsed and response.parsed.scenes:
                return response.parsed
        except Exception as e:
            last_error = e

    raise RuntimeError(f"Error estructurando guion para MoviePy con Gemini: {last_error}")


# =====================================================================
# 2. FUNCIONES DEL PIPELINE STUDIO WEB & METADATOS YOUTUBE
# =====================================================================

def get_style_suffix(style_id: str) -> str:
    """Obtiene los modificadores estilísticos del estilo visual seleccionado."""
    for s in VISUAL_STYLES:
        if s["id"] == style_id:
            return s["prompt_suffix"]
    return "minimalist black line art on pure white background, Casually Explained style, clean vector illustration"


def _truncate_title_60(title: str) -> str:
    """Garantiza que cada opción de título tenga como máximo 60 caracteres."""
    clean = re.sub(r"\s+", " ", title.strip())
    if len(clean) <= 60:
        return clean
    truncated = clean[:57].rsplit(" ", 1)[0]
    return (truncated if len(truncated) >= 25 else clean[:57]).rstrip(" ,;:-") + "..."


def format_mm_ss(seconds: float) -> str:
    """Formatea segundos al estándar de capítulos de YouTube (MM:SS)."""
    seconds = max(0.0, float(seconds))
    total_sec = int(round(seconds))
    mins = total_sec // 60
    secs = total_sec % 60
    return f"{mins:02d}:{secs:02d}"


def _derive_default_chapter_title(scene: ProjectScene) -> str:
    """Genera un título corto para el capítulo a partir del texto de la escena si no fue provisto."""
    if scene.chapter_title and scene.chapter_title.strip():
        return scene.chapter_title.strip()[:45]
    cleaned = re.sub(r"\[.*?\]", " ", scene.script_text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    words = cleaned.split(" ")[:6]
    title = " ".join(words).rstrip(".,;:!?")
    return title if title else f"Escena {scene.order}"


def compute_exact_scene_chapter_timestamps(project: Project) -> List[Tuple[str, str]]:
    """
    Calcula las marcas de tiempo exactas (MM:SS) de los capítulos de YouTube
    sincronizadas con los tiempos reales de Whisper / Edge-TTS ('word_timings.json'
    o duraciones medidas por ffprobe en cada escena).
    """
    paths = ensure_project_dirs(project.id)
    timings_file = paths["audio"] / "word_timings.json"

    scene_start_map = {}
    if timings_file.exists():
        try:
            data = json.loads(timings_file.read_text(encoding="utf-8"))
            for w in data.get("words", []):
                s_order = w.get("scene_order")
                if s_order is not None and s_order not in scene_start_map:
                    scene_start_map[int(s_order)] = float(w.get("start", 0.0))
        except Exception:
            scene_start_map = {}

    chapters: List[Tuple[str, str]] = []
    cumulative_sec = 0.0

    for idx, scene in enumerate(project.scenes):
        if idx == 0:
            start_sec = 0.0
        elif scene.order in scene_start_map:
            start_sec = scene_start_map[scene.order]
        else:
            start_sec = cumulative_sec

        chapter_label = _derive_default_chapter_title(scene)
        chapters.append((format_mm_ss(start_sec), chapter_label))

        scene_dur = float(scene.duration or 4.0)
        if scene.audio_path and project.settings.audio_mode != "custom":
            fname = scene.audio_path.split("?")[0].split("/")[-1]
            local_audio = paths["audio"] / fname
            if local_audio.exists():
                probed = get_audio_duration_ffprobe(local_audio)
                if probed > 0:
                    scene_dur = probed
        cumulative_sec = max(start_sec, cumulative_sec) + scene_dur

    return chapters


def ensure_youtube_metadata(project: Project) -> YouTubeMetadata:
    """
    Garantiza que el proyecto cuente con un objeto YouTubeMetadata válido y completo.
    """
    base_title = (project.video_title or project.name or "Video Documental IA").strip()
    meta = project.youtube_metadata

    if meta and meta.title_options and meta.description_body and meta.tags:
        meta.title_options = [_truncate_title_60(t) for t in meta.title_options[:3]]
        while len(meta.title_options) < 3:
            meta.title_options.append(_truncate_title_60(f"{base_title} - Parte {len(meta.title_options) + 1}"))
        meta.tags = [t.strip() for t in meta.tags if t.strip()][:10]
        return meta

    clean_script = re.sub(r"\[.*?\]", " ", project.full_script or "")
    clean_script = re.sub(r"\s+", " ", clean_script).strip()

    opt1 = _truncate_title_60(base_title)
    opt2 = _truncate_title_60(f"La Verdad Oculta: {base_title}")
    opt3 = _truncate_title_60(f"Cómo Funciona Realmente: {base_title}")

    desc = (
        f"En este análisis documental exploramos a fondo {base_title}.\n\n"
        f"{clean_script[:280]}{'...' if len(clean_script) > 280 else ''}\n\n"
        "Suscríbete para más ensayos visuales de alto nivel sobre estrategia, tecnología y finanzas."
    )

    words_pool = [
        w.lower().strip(".,;:!?\"'()")
        for w in (base_title + " " + clean_script).split()
        if len(w.strip(".,;:!?\"'()")) >= 5
    ]
    unique_keywords = []
    for w in words_pool:
        if w not in unique_keywords:
            unique_keywords.append(w)

    default_tags = [
        base_title.lower()[:30],
        "documental financiero",
        "estrategia y negocios",
        "educacion financiera",
        "historia y tecnologia",
        "analisis profundo",
        "casually finance",
        "desarrollo personal",
        "economia moderna",
        "video ensayo",
    ]
    merged_tags = unique_keywords[:5] + [t for t in default_tags if t not in unique_keywords[:5]]
    final_tags = merged_tags[:10]

    first_visual = project.scenes[0].visual_description if project.scenes else "Composición minimalista en alto contraste"
    thumb_idea = (
        f"Composición estilo documental (16:9): {first_visual}. "
        f"En primer plano, personaje minimalista junto al objeto clave con acentos dorados (#FFD700). "
        f"Texto corto de impacto (3 palabras máximo) en tipografía Sans-Serif ExtraBold: "
        f"\"{_truncate_title_60(base_title).upper()[:22]}\"."
    )

    project.youtube_metadata = YouTubeMetadata(
        title_options=[opt1, opt2, opt3],
        description_body=desc,
        tags=final_tags,
        thumbnail_idea=thumb_idea,
    )
    return project.youtube_metadata


def generate_youtube_metadata_file(project: Project) -> str:
    """
    Genera y guarda el archivo 'metadatos.txt' en la carpeta del proyecto y junto al
    render final ('projects/{id}/export/metadatos.txt').
    """
    paths = ensure_project_dirs(project.id)
    meta = ensure_youtube_metadata(project)
    chapters = compute_exact_scene_chapter_timestamps(project)

    chapters_block = "\n".join([f"{ts} - {label}" for ts, label in chapters]) if chapters else "00:00 - Introducción"
    titles_block = "\n".join([
        f"Opción {i} ({len(t)} caracteres): {t}"
        for i, t in enumerate(meta.title_options[:3], start=1)
    ])
    tags_csv = ", ".join(meta.tags[:10])
    tags_list = "\n".join([f"  {i}. {tag}" for i, tag in enumerate(meta.tags[:10], start=1)])

    content = (
        "====================================================================\n"
        f"PROYECTO: {(project.video_title or project.name).upper()}\n"
        "EMPAQUETADO SEO Y METADATOS PARA YOUTUBE (FORMATO 16:9 FULL HD)\n"
        "====================================================================\n\n"
        "1. OPCIONES DE TÍTULO (MÁXIMO 60 CARACTERES)\n"
        "--------------------------------------------------------------------\n"
        f"{titles_block}\n\n"
        "2. DESCRIPCIÓN CON MARCAS DE TIEMPO / CAPÍTULOS\n"
        "--------------------------------------------------------------------\n"
        f"{meta.description_body.strip()}\n\n"
        "📌 CAPÍTULOS DEL VIDEO (TIMESTAMPS SINCRONIZADOS):\n"
        f"{chapters_block}\n\n"
        "3. ETIQUETAS / TAGS (10 ETIQUETAS SEO)\n"
        "--------------------------------------------------------------------\n"
        f"Lista para copiar y pegar:\n{tags_csv}\n\n"
        f"Desglose:\n{tags_list}\n\n"
        "4. IDEA PARA LA MINIATURA (THUMBNAIL CONCEPT)\n"
        "--------------------------------------------------------------------\n"
        f"{meta.thumbnail_idea.strip()}\n"
        "====================================================================\n"
    )

    root_meta_path = paths["root"] / "metadatos.txt"
    export_meta_path = paths["export"] / "metadatos.txt"

    root_meta_path.write_text(content, encoding="utf-8")
    export_meta_path.write_text(content, encoding="utf-8")

    web_path = f"/projects/{project.id}/export/metadatos.txt?t={int(time.time())}"
    project.metadata_file_path = web_path
    return web_path


def analyze_script_with_gemini(project: Project) -> List[ProjectScene]:
    """
    Utiliza Gemini Flash para dividir el guion en escenas estructuradas y generar
    simultáneamente los metadatos SEO de YouTube.
    """
    api_key = get_gemini_api_key()
    if not api_key:
        raise ValueError("Clave de API de Gemini no configurada. Por favor introduce tu GEMINI_API_KEY en los ajustes.")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    style_suffix = get_style_suffix(project.settings.visual_style)
    target_info = f"La duración total deseada es de aproximadamente {project.settings.target_duration} segundos." if project.settings.target_duration else ""

    prompt = f"""Eres un director cinematográfico y estratega SEO de YouTube de élite (especialista en canales estilo Casually Explained / Casually Finance).
Tu misión es dividir el siguiente guion en escenas coherentes y generar el paquete completo de metadatos SEO para YouTube.

INFORMACIÓN DEL PROYECTO:
- Título base: {project.video_title or project.name}
- Formato de video: 16:9 Horizontal (1920x1080 Full HD)
- Estilo visual deseado: {project.settings.visual_style} ({style_suffix})
{target_info}

REGLAS CRÍTICAS INQUEBRANTABLES PARA LAS ESCENAS:
1. PRESERVACIÓN TOTAL DEL TEXTO: No resumas, no omitas, no sintetices y no alteres ni una sola palabra del guion original.
2. La concatenación de todos los fragmentos 'exact_script_fragment' en orden DEBE reproducir el guion original completo, palabra por palabra.
3. Si el guion contiene acotaciones entre corchetes o paréntesis [como indicaciones de sonido o acción], utilízalas para enriquecer la descripción visual ('visual_description') y el prompt ('image_prompt'), pero mantén el flujo de narración intacto.
4. Para cada escena, incluye un 'chapter_title' breve y magnético (máximo 45 caracteres) que servirá como título de capítulo en las marcas de tiempo de YouTube.
5. Para cada escena, escribe un 'image_prompt' detallado en inglés optimizado para ilustración minimalista o cinematográfica 16:9.
6. Calcula 'estimated_duration_seconds' basándote en la velocidad natural de locución (aprox. 2.5 palabras por segundo, mínimo 3.0 segundos por escena).
7. Sugiere la transición adecuada ('fade', 'dissolve', 'zoom_in', 'pan_left', 'cut') para el montaje.

REGLAS CRÍTICAS PARA 'youtube_metadata':
1. 'title_options': Genera EXACTAMENTE 3 opciones de título de alto CTR en el idioma del guion. CADA TÍTULO DEBE TENER MÁXIMO 60 CARACTERES.
2. 'description_body': Escribe una descripción persuasiva y optimizada para SEO de 2 párrafos que enganche al espectador.
3. 'tags': Genera EXACTAMENTE 10 etiquetas (tags) altamente relevantes para posicionamiento en YouTube.
4. 'thumbnail_idea': Describe una idea visual concreta y de alto impacto para la miniatura 16:9.

GUION ORIGINAL COMPLETO A DIVIDIR:
\"\"\"
{project.full_script}
\"\"\"
"""

    result_data = None
    last_error = None

    for model_name in TEXT_MODELS_CASCADE:
        try:
            print(f"[Gemini] Intentando análisis + metadatos SEO con modelo: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GeminiScriptAnalysisResult,
                    temperature=0.2,
                ),
            )
            result_data = response.parsed
            if result_data and result_data.scenes:
                print(f"[Gemini] ¡Análisis y metadatos exitosos con {model_name}!")
                break
        except Exception as e:
            print(f"[Gemini] Modelo {model_name} no disponible: {e}")
            last_error = e

    if not result_data or not result_data.scenes:
        raise RuntimeError(f"Error analizando guion con Gemini: {last_error}")

    scenes: List[ProjectScene] = []
    for s in result_data.scenes:
        scene = ProjectScene(
            order=s.scene_number,
            chapter_title=s.chapter_title.strip()[:45] if getattr(s, "chapter_title", None) else f"Escena {s.scene_number}",
            script_text=s.exact_script_fragment.strip(),
            visual_description=s.visual_description.strip(),
            image_prompt=s.image_prompt.strip(),
            duration=round(max(3.0, s.estimated_duration_seconds), 1),
            suggested_transition=s.suggested_transition,
            transition=s.suggested_transition,
            context_notes=s.narrative_context.strip(),
            image_status="pending",
            audio_status="pending"
        )
        scenes.append(scene)

    project.scenes = scenes

    if getattr(result_data, "youtube_metadata", None):
        yt = result_data.youtube_metadata
        yt.title_options = [_truncate_title_60(t) for t in (yt.title_options or [])[:3]]
        yt.tags = [t.strip() for t in (yt.tags or []) if t.strip()][:10]
        project.youtube_metadata = yt

    generate_youtube_metadata_file(project)
    return scenes


def create_fallback_image(project: Project, scene: ProjectScene) -> bytes:
    """
    Crea un fotograma minimalista estilo 'Casually Explained' (fondo blanco, personaje SVG
    a la izquierda, prop SVG a la derecha y título superior en negro) cuando no se usa Imagen 3.
    """
    w, h = 1920, 1080
    canvas = Image.new("RGBA", (w, h), color=(255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    try:
        from svg_renderer import convert_svg_to_png
        import tempfile

        emotions = ["normal", "feliz", "triste", "sorprendido"]
        chosen_emotion = emotions[(scene.order - 1) % len(emotions)]
        char_svg = BASE_DIR / "assets" / "character" / f"{chosen_emotion}.svg"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            if char_svg.exists():
                char_png = tmp_path / "char.png"
                convert_svg_to_png(char_svg, char_png, width=420)
                if char_png.exists():
                    with Image.open(char_png).convert("RGBA") as c_img:
                        canvas.alpha_composite(c_img, dest=(220, 260))

            prop_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400">
              <g stroke="#000000" stroke-width="8" fill="none" stroke-linecap="round" stroke-linejoin="round">
                <rect x="60" y="80" width="280" height="220" fill="#FFFFFF"/>
                <polyline points="90,260 155,190 210,225 295,120"/>
                <circle cx="295" cy="120" r="10" fill="#000000"/>
              </g>
            </svg>"""
            prop_png = tmp_path / "prop.png"
            convert_svg_to_png(prop_svg, prop_png, width=420)
            if prop_png.exists():
                with Image.open(prop_png).convert("RGBA") as p_img:
                    canvas.alpha_composite(p_img, dest=(1240, 300))
    except Exception:
        pass

    header = (scene.chapter_title or f"Escena #{scene.order}").upper()
    try:
        font = ImageFont.truetype("arialbd.ttf", 52)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), header, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) // 2, 85), header, fill=(0, 0, 0, 255), font=font)

    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def generate_scene_image(project: Project, scene: ProjectScene, use_fallback_on_error: bool = True) -> str:
    """
    Genera la imagen para la escena o utiliza el compositor minimalista SVG sobre fondo blanco.
    """
    api_key = get_gemini_api_key()
    style_suffix = get_style_suffix(project.settings.visual_style)
    full_prompt = f"{scene.image_prompt}, {style_suffix}"
    
    image_bytes = None
    
    if api_key:
        from google import genai
        client = genai.Client(api_key=api_key)

        for model_name in IMAGE_MODELS_CASCADE:
            try:
                print(f"[Gemini Image] Intentando generar imagen con {model_name}...")
                resp = client.models.generate_content(
                    model=model_name,
                    contents=f"Generate an image: {full_prompt}"
                )
                if resp.candidates and resp.candidates[0].content and resp.candidates[0].content.parts:
                    for part in resp.candidates[0].content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            image_bytes = part.inline_data.data
                            print(f"[Gemini Image] ¡Imagen generada con éxito con {model_name}!")
                            break
                if image_bytes:
                    break
            except Exception as e:
                print(f"[Gemini Image] Modelo {model_name} no disponible o cuota limitada: {e}")

    if not image_bytes:
        if use_fallback_on_error:
            image_bytes = create_fallback_image(project, scene)
        else:
            raise RuntimeError("No se pudo generar la imagen.")

    web_path = save_scene_image(project.id, scene.id, image_bytes, ext="png")
    scene.image_path = web_path
    scene.image_status = "approved" if image_bytes else "pending"
    return web_path
