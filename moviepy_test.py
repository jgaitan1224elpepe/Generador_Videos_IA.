import os
import sys
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from app.config import FFMPEG_BIN, BASE_DIR
from svg_renderer import convert_svg_to_png

# Asegurar que MoviePy / imageio_ffmpeg utilice el binario FFmpeg detectado en Windows 11
if FFMPEG_BIN and os.path.isabs(FFMPEG_BIN):
    os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_BIN
    os.environ["FFMPEG_BINARY"] = FFMPEG_BIN


def ensure_default_character_svg(character_svg_path: Path) -> None:
    """Crea 'assets/character/normal.svg' si aún no existe para garantizar que la prueba corra."""
    if character_svg_path.exists():
        return
    character_svg_path.parent.mkdir(parents=True, exist_ok=True)
    default_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 600" width="400" height="600">
  <g stroke="#000000" stroke-width="8" fill="none" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="200" cy="140" r="70" fill="#FFFFFF"/>
    <circle cx="175" cy="130" r="6" fill="#000000"/>
    <circle cx="225" cy="130" r="6" fill="#000000"/>
    <line x1="175" y1="165" x2="225" y2="165"/>
    <line x1="200" y1="210" x2="200" y2="410"/>
    <line x1="200" y1="255" x2="120" y2="335"/>
    <line x1="200" y1="255" x2="285" y2="310"/>
    <line x1="200" y1="410" x2="140" y2="550"/>
    <line x1="200" y1="410" x2="260" y2="550"/>
  </g>
</svg>"""
    character_svg_path.write_text(default_svg, encoding="utf-8")


def _set_clip_duration(clip, duration: float):
    """Compatibilidad transparente entre MoviePy 1.x (.set_duration) y MoviePy 2.x (.with_duration)."""
    if hasattr(clip, "with_duration"):
        return clip.with_duration(duration)
    return clip.set_duration(duration)


def _set_clip_position(clip, pos):
    """Compatibilidad transparente entre MoviePy 1.x (.set_position) y MoviePy 2.x (.with_position)."""
    if hasattr(clip, "with_position"):
        return clip.with_position(pos)
    return clip.set_position(pos)


def _create_title_clip(text: str, duration: float, temp_dir: Path):
    """
    Crea el TextClip superior central con fuente 'Arial', color negro y fontsize=70.
    Si ImageMagick no está instalado en Windows 11, genera un ImageClip transparente equivalente.
    """
    try:
        try:
            from moviepy import TextClip  # MoviePy 2.x
            try:
                txt_clip = TextClip(text=text, font="Arial", font_size=70, color="black")
            except Exception:
                txt_clip = TextClip(text=text, font="arial.ttf", font_size=70, color="black")
        except ImportError:
            from moviepy.editor import TextClip  # MoviePy 1.x
            txt_clip = TextClip(text, font="Arial", fontsize=70, color="black")

        txt_clip = _set_clip_duration(txt_clip, duration)
        txt_clip = _set_clip_position(txt_clip, ("center", 60))
        return txt_clip
    except Exception as e:
        print(f"[Aviso] TextClip nativo requirió fallback sin ImageMagick ({e}). Renderizando texto con Pillow...")
        try:
            from moviepy import ImageClip
        except ImportError:
            from moviepy.editor import ImageClip

        img = Image.new("RGBA", (1600, 140), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 70)
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((1600 - tw) // 2, (140 - th) // 2), text, fill=(0, 0, 0, 255), font=font)

        txt_png = temp_dir / "title_text.png"
        img.save(txt_png, format="PNG")
        fallback_clip = ImageClip(str(txt_png))
        fallback_clip = _set_clip_duration(fallback_clip, duration)
        fallback_clip = _set_clip_position(fallback_clip, ("center", 60))
        return fallback_clip


def _render_with_ffmpeg_fallback(
    char_png_path: Path,
    prop_png_path: Path,
    title_text: str,
    output_video: Path,
    duration: float = 5.0,
    fps: int = 24
) -> None:
    """
    Si 'moviepy' aún no ha sido instalado en el entorno virtual (.venv),
    compone el fotograma exacto 1920x1080 (fondo blanco, personaje a la izquierda,
    prop a la derecha y título Arial 70 negro arriba) y exporta 'prueba_estilo.mp4'
    con FFmpeg a 24 FPS con libx264.
    """
    import subprocess
    canvas = Image.new("RGBA", (1920, 1080), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    with Image.open(char_png_path).convert("RGBA") as c_img:
        cy = (1080 - c_img.height) // 2
        canvas.alpha_composite(c_img, dest=(220, max(0, cy)))

    with Image.open(prop_png_path).convert("RGBA") as p_img:
        py = (1080 - p_img.height) // 2
        canvas.alpha_composite(p_img, dest=(1250, max(0, py)))

    try:
        font = ImageFont.truetype("arial.ttf", 70)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), title_text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((1920 - tw) // 2, 60), title_text, fill=(0, 0, 0, 255), font=font)

    frame_path = char_png_path.parent / "composite_frame.png"
    canvas.convert("RGB").save(frame_path, format="PNG")

    cmd = [
        FFMPEG_BIN,
        "-y",
        "-loop", "1",
        "-i", str(frame_path),
        "-t", str(duration),
        "-r", str(fps),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output_video)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_moviepy_test() -> None:
    """
    Ensambla una escena de prueba estilo 'Casually Explained' (1920x1080, 5s, 24 FPS):
      - Fondo blanco (ColorClip 1920x1080)
      - Personaje SVG ('assets/character/normal.svg') a la izquierda
      - Prop SVG simulado (gráfica/círculo line-art) a la derecha
      - TextClip superior central ('Arial', negro, fontsize=70)
      - Exporta a 'prueba_estilo.mp4' con codec 'libx264' y fps=24
    """
    duration = 5.0
    fps = 24
    output_video = BASE_DIR / "prueba_estilo.mp4"
    character_svg = BASE_DIR / "assets" / "character" / "normal.svg"
    ensure_default_character_svg(character_svg)
    title_text = "Cuando descubres el interés compuesto"

    # Código SVG simulado para el prop/utilería (círculo + gráfica minimalista line-art)
    simulated_prop_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400">
  <g stroke="#000000" stroke-width="8" fill="none" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="200" cy="200" r="140" fill="#FFFFFF"/>
    <rect x="115" y="135" width="170" height="130" fill="none"/>
    <polyline points="130,240 175,190 215,215 265,155"/>
    <circle cx="265" cy="155" r="8" fill="#000000"/>
  </g>
</svg>"""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        char_png_path = tmp_path / "character_normal.png"
        prop_png_path = tmp_path / "prop_scene.png"

        # 1. Convertir SVGs a PNG con fondo transparente usando svg_renderer.py
        print("[1/4] Renderizando 'assets/character/normal.svg' a PNG...")
        convert_svg_to_png(character_svg, char_png_path, width=450)

        print("[2/4] Renderizando código SVG del prop a PNG...")
        convert_svg_to_png(simulated_prop_svg, prop_png_path, width=450)

        try:
            try:
                from moviepy import ColorClip, ImageClip, CompositeVideoClip
            except ImportError:
                from moviepy.editor import ColorClip, ImageClip, CompositeVideoClip

            # 2. Crear fondo blanco 1920x1080
            bg_clip = ColorClip(size=(1920, 1080), color=(255, 255, 255))
            bg_clip = _set_clip_duration(bg_clip, duration)

            # 3. Posicionar personaje a la izquierda y prop a la derecha
            char_clip = ImageClip(str(char_png_path))
            char_clip = _set_clip_duration(char_clip, duration)
            char_clip = _set_clip_position(char_clip, (220, "center"))

            prop_clip = ImageClip(str(prop_png_path))
            prop_clip = _set_clip_duration(prop_clip, duration)
            prop_clip = _set_clip_position(prop_clip, (1250, "center"))

            # 4. Crear TextClip superior central (Arial, negro, fontsize=70)
            title_clip = _create_title_clip(
                text=title_text,
                duration=duration,
                temp_dir=tmp_path
            )

            # 5. Componer y exportar a prueba_estilo.mp4
            print("[3/4] Ensamblando CompositeVideoClip (1920x1080, 5s, 24 FPS)...")
            final_clip = CompositeVideoClip([bg_clip, char_clip, prop_clip, title_clip], size=(1920, 1080))
            final_clip = _set_clip_duration(final_clip, duration)

            print(f"[4/4] Exportando video a: {output_video}")
            final_clip.write_videofile(
                str(output_video),
                fps=fps,
                codec="libx264",
                audio=False,
                preset="faster",
                ffmpeg_params=["-pix_fmt", "yuv420p"]
            )
        except ImportError:
            print("[Aviso] 'moviepy' no está instalado aún en .venv. Exportando 'prueba_estilo.mp4' con FFmpeg directo...")
            _render_with_ffmpeg_fallback(char_png_path, prop_png_path, title_text, output_video, duration, fps)

        print(f"[OK] ¡Video generado exitosamente en: {output_video}!")


if __name__ == "__main__":
    run_moviepy_test()
