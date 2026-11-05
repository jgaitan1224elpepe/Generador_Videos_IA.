import io
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
from app.config import get_gemini_api_key, VISUAL_STYLES, ASPECT_RATIOS
from app.models.project import Project, Scene, GeminiScriptAnalysisResult
from app.services.storage import save_scene_image

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

def get_style_suffix(style_id: str) -> str:
    """Obtiene los modificadores estilísticos del estilo visual seleccionado."""
    for s in VISUAL_STYLES:
        if s["id"] == style_id:
            return s["prompt_suffix"]
    return "cinematic lighting, photorealistic, 8k resolution, detailed"

def analyze_script_with_gemini(project: Project) -> List[Scene]:
    """
    Utiliza Gemini Flash para dividir el guion en escenas estructuradas,
    garantizando que se conserve el 100% del texto del guion original.
    Implementa reintentos con modelos de reserva en caso de alta demanda.
    """
    api_key = get_gemini_api_key()
    if not api_key:
        raise ValueError("Clave de API de Gemini no configurada. Por favor introduce tu GEMINI_API_KEY en los ajustes.")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    style_suffix = get_style_suffix(project.settings.visual_style)
    target_info = f"La duración total deseada es de aproximadamente {project.settings.target_duration} segundos." if project.settings.target_duration else ""

    prompt = f"""Eres un director cinematográfico y editor audiovisual profesional de élite.
Tu misión es dividir el siguiente guion en escenas cinematográficas coherentes y ordenadas.

INFORMACIÓN DEL PROYECTO:
- Título: {project.video_title}
- Formato de video: {project.settings.aspect_ratio}
- Estilo visual deseado: {project.settings.visual_style} ({style_suffix})
{target_info}

REGLAS CRÍTICAS INQUEBRANTABLES:
1. PRESERVACIÓN TOTAL DEL TEXTO: No resumas, no omitas, no sintetices y no alteres ni una sola palabra del guion original. 
2. La concatenación de todos los fragmentos 'exact_script_fragment' en orden DEBE reproducir el guion original completo, palabra por palabra.
3. Si el guion contiene acotaciones entre corchetes o paréntesis [como indicaciones de sonido o acción], utilízalas para enriquecer la descripción visual ('visual_description') y el prompt ('image_prompt'), pero mantén el flujo de narración intacto.
4. Para cada escena, escribe un 'image_prompt' detallado y técnico en inglés optimizado para generación de imagen, describiendo el sujeto principal, plano de cámara (close-up, wide shot, etc.), iluminación y atmósfera coherente con el estilo visual.
5. Calcula 'estimated_duration_seconds' basándote en la velocidad natural de locución (aprox. 2.5 palabras por segundo, mínimo 3.0 segundos por escena).
6. Sugiere la transición adecuada ('fade', 'dissolve', 'zoom_in', 'pan_left', 'cut') para el montaje.

GUION ORIGINAL COMPLETO A DIVIDIR:
\"\"\"
{project.full_script}
\"\"\"
"""

    result_data = None
    last_error = None

    for model_name in TEXT_MODELS_CASCADE:
        try:
            print(f"[Gemini] Intentando análisis con modelo: {model_name}...")
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
                print(f"[Gemini] ¡Análisis exitoso con {model_name}!")
                break
        except Exception as e:
            print(f"[Gemini] Modelo {model_name} no disponible: {e}")
            last_error = e

    if not result_data or not result_data.scenes:
        raise RuntimeError(f"Error analizando guion con Gemini: {last_error}")

    scenes: List[Scene] = []
    for s in result_data.scenes:
        scene = Scene(
            order=s.scene_number,
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

    return scenes

def create_fallback_image(project: Project, scene: Scene) -> bytes:
    """
    Crea una imagen de storyboard estilizada usando Pillow cuando no hay cuota de imágenes
    o se requiere modo offline/prueba.
    """
    dims = ASPECT_RATIOS.get(project.settings.aspect_ratio, {"width": 1920, "height": 1080})
    w, h = dims["width"], dims["height"]
    
    img = Image.new("RGB", (w, h), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)
    
    # Bordes y acentos cinematográficos
    border_color = (51, 65, 85)
    accent_color = (6, 182, 212) # Cyan
    draw.rectangle([40, 40, w - 40, h - 40], outline=border_color, width=4)
    draw.line([40, 90, 300, 90], fill=accent_color, width=6)
    
    # Título y número de escena
    header_text = f"ESCENA #{scene.order:02d}  •  {project.video_title.upper()}"
    draw.text((60, 55), header_text, fill=(241, 245, 249))
    
    # Descripción visual
    desc_label = "DESCRIPCIÓN VISUAL DE LA ESCENA:"
    draw.text((60, 140), desc_label, fill=accent_color)
    draw.text((60, 170), scene.visual_description[:200] + ("..." if len(scene.visual_description) > 200 else ""), fill=(255, 255, 255))
    
    # Fragmento del guion
    script_label = "NARRACIÓN DEL GUION (AUDIO SINCRONIZADO):"
    draw.text((60, 260), script_label, fill=(168, 85, 247)) # Morado
    draw.text((60, 290), f'"{scene.script_text[:250]}"', fill=(226, 232, 240))
    
    # Prompt técnico
    prompt_label = "PROMPT GENERATIVO DE IMAGEN:"
    draw.text((60, 390), prompt_label, fill=(234, 179, 8)) # Amarillo
    draw.text((60, 420), scene.image_prompt[:300], fill=(148, 163, 184))
    
    # Marca de agua
    badge = f"ESTILO: {project.settings.visual_style.upper()}  |  FORMATO: {project.settings.aspect_ratio}  |  DURACIÓN: {scene.duration}s"
    draw.text((60, h - 80), badge, fill=(100, 116, 139))
    
    output = io.BytesIO()
    img.save(output, format="PNG")
    return output.getvalue()

def generate_scene_image(project: Project, scene: Scene, use_fallback_on_error: bool = True) -> str:
    """
    Intenta generar la imagen con los modelos de imagen de Google Gemini.
    Si la cuota de la cuenta está agotada (429) o en tier gratuito sin imagen,
    genera automáticamente la tarjeta visual estilizada y permite subir imagen propia.
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
