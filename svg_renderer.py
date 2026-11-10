import io
import os
import re
import tempfile
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Union
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


def _is_svg_code(svg_source: Union[str, Path]) -> bool:
    """Determina si 'svg_source' es código XML/SVG en texto o una ruta de archivo."""
    if isinstance(svg_source, Path):
        return False
    s = str(svg_source).strip()
    return s.startswith("<") or "<svg" in s.lower()


def _resize_png_to_width(png_path: Path, target_width: int) -> None:
    """Ajusta el PNG renderizado al ancho objetivo manteniendo relación de aspecto y canal alfa."""
    if not png_path.exists() or target_width <= 0:
        return
    with Image.open(png_path) as img:
        img = img.convert("RGBA")
        w, h = img.size
        if w > 0 and w != target_width:
            target_height = max(1, int(round(h * (target_width / float(w)))))
            resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
            resized.save(png_path, format="PNG")


def _render_with_pillow_svg_fallback(svg_xml: str, output_path: Path, width: int = 800) -> str:
    """
    Motor de respaldo nativo en Python (Pillow RGBA) para Windows 11 cuando no están
    presentes las librerías nativas GTK3/Cairo ni rlPyCairo en el entorno.
    Interpreta primitivas SVG line-art (<circle>, <rect>, <line>, <ellipse>, <polyline>, <polygon>, <path>)
    sobre lienzo transparente RGBA.
    """
    clean_xml = re.sub(r"xmlns\s*=\s*['\"][^'\"]*['\"]", "", svg_xml, count=1)
    root = ET.fromstring(clean_xml)

    vb = root.attrib.get("viewBox", "0 0 400 400").replace(",", " ").split()
    vb_w = float(vb[2]) if len(vb) == 4 else float(re.sub(r"[^\d.]", "", root.attrib.get("width", "400")) or 400)
    vb_h = float(vb[3]) if len(vb) == 4 else float(re.sub(r"[^\d.]", "", root.attrib.get("height", "400")) or 400)

    scale = float(width) / max(1.0, vb_w)
    out_w = int(round(vb_w * scale))
    out_h = max(1, int(round(vb_h * scale)))

    img = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def parse_color(val: str, default=(0, 0, 0, 255)):
        if not val or val.lower() == "none" or val.lower() == "transparent":
            return None
        v = val.strip()
        if v.startswith("#"):
            h = v.lstrip("#")
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            if len(h) == 6:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        color_map = {
            "black": (0, 0, 0, 255),
            "white": (255, 255, 255, 255),
            "red": (220, 38, 38, 255),
            "gold": (212, 175, 55, 255),
            "blue": (37, 99, 235, 255),
            "green": (22, 163, 74, 255),
        }
        return color_map.get(v.lower(), default)

    def walk(node, inherited_stroke="#000000", inherited_fill="none", inherited_sw=6.0):
        stroke_attr = node.attrib.get("stroke", inherited_stroke)
        fill_attr = node.attrib.get("fill", inherited_fill)
        sw_raw = re.sub(r"[^\d.]", "", str(node.attrib.get("stroke-width", inherited_sw)))
        sw = float(sw_raw) if sw_raw else inherited_sw
        px_sw = max(2, int(round(sw * scale)))

        stroke_rgba = parse_color(stroke_attr, (0, 0, 0, 255))
        fill_rgba = parse_color(fill_attr, None)
        tag = node.tag.split("}")[-1].lower()

        if tag == "circle":
            cx = float(node.attrib.get("cx", 0)) * scale
            cy = float(node.attrib.get("cy", 0)) * scale
            r = float(node.attrib.get("r", 0)) * scale
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill_rgba, outline=stroke_rgba, width=px_sw)
        elif tag == "ellipse":
            cx = float(node.attrib.get("cx", 0)) * scale
            cy = float(node.attrib.get("cy", 0)) * scale
            rx = float(node.attrib.get("rx", 0)) * scale
            ry = float(node.attrib.get("ry", 0)) * scale
            draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill_rgba, outline=stroke_rgba, width=px_sw)
        elif tag == "rect":
            x = float(node.attrib.get("x", 0)) * scale
            y = float(node.attrib.get("y", 0)) * scale
            rw = float(node.attrib.get("width", 0)) * scale
            rh = float(node.attrib.get("height", 0)) * scale
            draw.rectangle([x, y, x + rw, y + rh], fill=fill_rgba, outline=stroke_rgba, width=px_sw)
        elif tag == "line":
            x1 = float(node.attrib.get("x1", 0)) * scale
            y1 = float(node.attrib.get("y1", 0)) * scale
            x2 = float(node.attrib.get("x2", 0)) * scale
            y2 = float(node.attrib.get("y2", 0)) * scale
            if stroke_rgba:
                draw.line([x1, y1, x2, y2], fill=stroke_rgba, width=px_sw)
        elif tag in ("polyline", "polygon"):
            pts_raw = re.findall(r"-?\d+\.?\d*", node.attrib.get("points", ""))
            pts = [(float(pts_raw[i]) * scale, float(pts_raw[i + 1]) * scale) for i in range(0, len(pts_raw) - 1, 2)]
            if len(pts) >= 2:
                if tag == "polygon":
                    draw.polygon(pts, fill=fill_rgba, outline=stroke_rgba)
                if stroke_rgba:
                    draw.line(pts + ([pts[0]] if tag == "polygon" else []), fill=stroke_rgba, width=px_sw)
        elif tag == "path":
            # Soporte básico para curvas cuadráticas M x y Q cx cy ex ey y líneas M/L
            d = node.attrib.get("d", "")
            nums = [float(n) for n in re.findall(r"-?\d+\.?\d*", d)]
            if "Q" in d.upper() and len(nums) >= 6:
                x0, y0, cx, cy, x1, y1 = [n * scale for n in nums[:6]]
                curve_pts = []
                for step in range(21):
                    t = step / 20.0
                    px = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
                    py = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
                    curve_pts.append((px, py))
                if stroke_rgba:
                    draw.line(curve_pts, fill=stroke_rgba, width=px_sw)
            elif len(nums) >= 4:
                pts = [(nums[i] * scale, nums[i + 1] * scale) for i in range(0, len(nums) - 1, 2)]
                if stroke_rgba and len(pts) >= 2:
                    draw.line(pts, fill=stroke_rgba, width=px_sw)

        for child in node:
            walk(child, stroke_attr, fill_attr, sw)

    walk(root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG")
    return str(output_path)


def convert_svg_to_png(
    svg_source: Union[str, Path],
    output_path: Union[str, Path],
    width: int = 800
) -> str:
    """
    Convierte un archivo SVG local o un string de código SVG puro en una imagen PNG
    con fondo transparente escalada a 'width' píxeles.
    
    Orden de motores en Windows 11:
      1. Motor primario: cairosvg.svg2png
      2. Fallback oficial: svglib.svglib.svg2rlg + reportlab.graphics.renderPM.drawToFile
      3. Respaldo de emergencia sin DLLs externas: Rasterizador vectorial Pillow RGBA
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    is_code = _is_svg_code(svg_source)
    if is_code:
        svg_xml_str = str(svg_source).strip()
        svg_file_path = None
    else:
        svg_file_path = Path(svg_source)
        if not svg_file_path.exists():
            raise FileNotFoundError(f"No se encontró el archivo SVG en: {svg_file_path}")
        svg_xml_str = svg_file_path.read_text(encoding="utf-8")

    # 1. INTENTO PRINCIPAL: CairoSVG
    try:
        import cairosvg  # type: ignore
        if is_code:
            cairosvg.svg2png(
                bytestring=svg_xml_str.encode("utf-8"),
                write_to=str(out_file),
                output_width=width
            )
        else:
            cairosvg.svg2png(
                url=str(svg_file_path),
                write_to=str(out_file),
                output_width=width
            )
        logger.info(f"[svg_renderer] Renderizado exitoso con CairoSVG -> {out_file}")
        return str(out_file)

    except (ImportError, OSError, Exception) as cairo_err:
        logger.warning(f"[svg_renderer] CairoSVG no disponible en Windows ({cairo_err}). Activando fallback svglib + reportlab...")

    # 2. FALLBACK SECUNDARIO: svglib + reportlab.graphics.renderPM
    temp_svg_path = None
    try:
        from svglib.svglib import svg2rlg  # type: ignore
        from reportlab.graphics import renderPM  # type: ignore

        if is_code:
            fd, tmp_name = tempfile.mkstemp(suffix=".svg")
            os.close(fd)
            temp_svg_path = Path(tmp_name)
            temp_svg_path.write_text(svg_xml_str, encoding="utf-8")
            source_for_rlg = str(temp_svg_path)
        else:
            source_for_rlg = str(svg_file_path)

        drawing = svg2rlg(source_for_rlg)
        if drawing is None:
            raise ValueError("svg2rlg retornó None al procesar el SVG.")

        if getattr(drawing, "width", 0) and drawing.width > 0 and width > 0:
            scale_factor = float(width) / float(drawing.width)
            drawing.width = width
            drawing.height = drawing.height * scale_factor
            drawing.scale(scale_factor, scale_factor)

        renderPM.drawToFile(drawing, str(out_file), fmt="PNG")
        _resize_png_to_width(out_file, width)
        logger.info(f"[svg_renderer] Renderizado exitoso con svglib + reportlab -> {out_file}")
        return str(out_file)

    except (ImportError, OSError, Exception) as rl_err:
        logger.warning(f"[svg_renderer] Fallback svglib/reportlab no disponible ({rl_err}). Usando rasterizador vectorial nativo Pillow...")
    finally:
        if temp_svg_path and temp_svg_path.exists():
            try:
                temp_svg_path.unlink()
            except Exception:
                pass

    # 3. RESPALDO DE EMERGENCIA GARANTIZADO EN WINDOWS 11 (Pillow RGBA)
    return _render_with_pillow_svg_fallback(svg_xml_str, out_file, width=width)

