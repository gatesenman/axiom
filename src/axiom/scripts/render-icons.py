#!/usr/bin/env python3
"""Rasterize assets/icon/axiom.svg into the Windows, Linux, and web icon sets."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "assets" / "icon"
SVG = ICON / "axiom.svg"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def raster(size: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["rsvg-convert", "-w", str(size), "-h", str(size), "-o", str(dest), str(SVG)]
    )


def bmp(image: Image.Image, dest: Path) -> None:
    image.convert("RGB").save(dest, "BMP")


def sidebar(master: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (164, 314), "#172454")
    icon = master.resize((112, 112), Image.Resampling.LANCZOS)
    canvas.paste(icon, ((164 - 112) // 2, 78), icon)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((24, 292, 140, 296), fill="#F5B431")
    return canvas


def header(master: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (150, 57), "#172454")
    icon = master.resize((40, 40), Image.Resampling.LANCZOS)
    canvas.paste(icon, (100, 8), icon)
    return canvas


def sheet(images: dict[int, Image.Image], dest: Path) -> None:
    labels = (16, 32, 48, 256)
    pad = 28
    label_w = 72
    cell_w = 300
    cell_h = 300
    width = pad + label_w + cell_w * 2 + pad
    height = pad + 36 + cell_h * len(labels) + pad
    canvas = Image.new("RGB", (width, height), "#0E0E10")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((pad + label_w + 16, 12), "light", fill="#F4F4F5", font=font)
    draw.text((pad + label_w + cell_w + 16, 12), "dark", fill="#F4F4F5", font=font)
    for row, size in enumerate(labels):
        y = pad + 36 + row * cell_h
        draw.text((pad, y + cell_h // 2 - 6), f"{size}px", fill="#D4D4D8", font=font)
        for col, bg in enumerate(("#F4F5F7", "#1A1B1E")):
            x = pad + label_w + col * cell_w
            draw.rectangle((x + 16, y + 16, x + cell_w - 16, y + cell_h - 16), fill=bg)
            icon = images[size]
            ox = x + (cell_w - size) // 2
            oy = y + (cell_h - size) // 2
            canvas.paste(icon, (ox, oy), icon)
    canvas.save(dest)


def main() -> None:
    pngs: dict[int, Image.Image] = {}
    for size in SIZES:
        dest = ICON / f"axiom-{size}.png"
        raster(size, dest)
        pngs[size] = Image.open(dest).convert("RGBA")

    linux = ICON / "linux"
    linux.mkdir(parents=True, exist_ok=True)
    pngs[256].save(linux / "256x256.png")
    pngs[512].save(linux / "512x512.png")

    ico_images = [pngs[size] for size in ICO_SIZES]
    ico_path = ICON / "axiom.ico"
    ico_images[-1].save(ico_path, format="ICO", sizes=[(size, size) for size in ICO_SIZES], append_images=ico_images[:-1])

    public = ROOT / "frontend" / "public"
    public.mkdir(parents=True, exist_ok=True)
    (public / "favicon.svg").write_text(SVG.read_text(encoding="utf-8"), encoding="utf-8")
    ico_path_public = public / "favicon.ico"
    ico_images[-1].save(ico_path_public, format="ICO", sizes=[(size, size) for size in ICO_SIZES], append_images=ico_images[:-1])
    pngs[256].save(public / "icon-256.png")
    pngs[512].save(public / "icon-512.png")

    bmp(sidebar(pngs[256]), ICON / "installer-sidebar.bmp")
    bmp(sidebar(pngs[256]), ICON / "uninstaller-sidebar.bmp")
    bmp(header(pngs[256]), ICON / "installer-header.bmp")
    sheet(pngs, ICON / "axiom-sheet.png")
    print("rendered", ico_path, "bytes", ico_path.stat().st_size)


if __name__ == "__main__":
    main()
