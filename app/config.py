import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE_DIR / "projects"
ENV_PATH = BASE_DIR / ".env"

# Cargar variables de entorno
load_dotenv(ENV_PATH)

def find_binary(binary_name: str) -> str:
    """Busca un ejecutable en PATH o en las rutas comunes de Windows."""
    # 1. Comprobar en PATH
    found = shutil.which(binary_name)
    if found:
        return found
    
    # 2. Rutas conocidas de WinGet en AppData
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_path = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_path.exists():
            matches = list(winget_path.glob(f"**/{binary_name}.exe"))
            if matches:
                return str(matches[0])
                
    # 3. Comprobar directorio local de usuario
    user_bin = Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / f"{binary_name}.exe"
    if user_bin.exists():
        return str(user_bin)
        
    return binary_name  # Retornar por defecto

FFMPEG_BIN = find_binary("ffmpeg")
FFPROBE_BIN = find_binary("ffprobe")

# Estilos visuales predeterminados
VISUAL_STYLES = [
    {
        "id": "cinematic",
        "name": "Cinematográfico Realista",
        "prompt_suffix": "cinematic lighting, 8k resolution, photorealistic, dramatic atmosphere, 35mm film aesthetic, shallow depth of field, masterpiece"
    },
    {
        "id": "anime",
        "name": "Anime / Manga Studio Ghibli",
        "prompt_suffix": "studio ghibli aesthetic, anime concept art, vibrant and lush colors, hand-drawn look, detailed scenery, nostalgic lighting"
    },
    {
        "id": "3d_animation",
        "name": "Animación 3D Estilo Pixar / Disney",
        "prompt_suffix": "3D stylized animation, pixar render style, raytracing, soft subsurface scattering, charming expressive lighting, 8k"
    },
    {
        "id": "cyberpunk",
        "name": "Cyberpunk Neón Futurista",
        "prompt_suffix": "cyberpunk style, neon glow, reflective rain-slick surfaces, high tech futuristic atmosphere, volumetric fog, vivid contrast"
    },
    {
        "id": "watercolor",
        "name": "Acuarela & Pintura Tradicional",
        "prompt_suffix": "expressive watercolor painting, rich ink outlines, soft artistic gradients, handcrafted traditional art texture"
    },
    {
        "id": "documentary",
        "name": "Documental Histórico / Fotoperiodismo",
        "prompt_suffix": "archival documentary photography, natural ambient lighting, authentic details, historic atmosphere, National Geographic style"
    }
]

# Formatos y relaciones de aspecto
ASPECT_RATIOS = {
    "16:9": {"width": 1920, "height": 1080, "name": "Horizontal (YouTube / Pantalla)", "ratio": "16:9"},
    "9:16": {"width": 1080, "height": 1920, "name": "Vertical (TikTok / Shorts / Reels)", "ratio": "9:16"},
    "1:1": {"width": 1080, "height": 1080, "name": "Cuadrado (Instagram / Feed)", "ratio": "1:1"}
}

# Catálogo de voces IA (Edge-TTS neuronales)
AVAILABLE_VOICES = [
    {"id": "es-ES-AlvaroNeural", "name": "Álvaro (España - Masculina, Narrador cálido)", "gender": "Male", "lang": "es-ES"},
    {"id": "es-ES-ElviraNeural", "name": "Elvira (España - Femenina, Clara y profesional)", "gender": "Female", "lang": "es-ES"},
    {"id": "es-MX-DaliaNeural", "name": "Dalia (México - Femenina, Dinámica y expresiva)", "gender": "Female", "lang": "es-MX"},
    {"id": "es-MX-JorgeNeural", "name": "Jorge (México - Masculina, Firme y formal)", "gender": "Male", "lang": "es-MX"},
    {"id": "es-AR-TomasNeural", "name": "Tomás (Argentina - Masculina, Acento rioplatense)", "gender": "Male", "lang": "es-AR"},
    {"id": "es-CO-GonzaloNeural", "name": "Gonzalo (Colombia - Masculina, Neutra y natural)", "gender": "Male", "lang": "es-CO"},
    {"id": "en-US-GuyNeural", "name": "Guy (EE.UU. - Masculina, Locutor documental)", "gender": "Male", "lang": "en-US"},
    {"id": "en-US-JennyNeural", "name": "Jenny (EE.UU. - Femenina, Amigable y clara)", "gender": "Female", "lang": "en-US"}
]

def get_gemini_api_key() -> str:
    """Obtiene la clave de API de Gemini desde el entorno o archivo .env."""
    load_dotenv(ENV_PATH, override=True)
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")

def set_gemini_api_key(key: str) -> None:
    """Guarda la clave de API de Gemini de forma segura en el archivo .env."""
    os.environ["GEMINI_API_KEY"] = key
    lines = []
    if ENV_PATH.exists():
        lines = [l for l in ENV_PATH.read_text(encoding="utf-8").splitlines() if not l.startswith("GEMINI_API_KEY=") and not l.startswith("GOOGLE_API_KEY=")]
    lines.append(f"GEMINI_API_KEY={key}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

