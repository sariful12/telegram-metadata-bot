"""Tests for clean.py — no token, no network, no Telegram needed.

Builds test images with Pillow (JPEG with EXIF+GPS, JPEG with an XMP
AI label, JPEG with a C2PA JUMBF block, PNG with text chunks + eXIf,
WebP with EXIF, and already-clean images) and verifies that
clean_image() finds the metadata, removes it, keeps the pixels and
the size, and reports an AI label where one was planted.

Run:  python tests/test_clean.py
"""

from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageChops  # noqa: E402

from clean import clean_image, scan_bytes  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS  " if cond else "FAIL  ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def mean_abs_diff(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    hist = diff.histogram()
    total = sum(hist)
    return sum(i * n for i, n in enumerate(hist)) / total if total else 0.0


def make_base(path: Path, size=(120, 80), color=(200, 60, 40)) -> Image.Image:
    img = Image.new("RGB", size, color)
    # a bit of variation so re-encode differences are measurable
    px = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = ((x * 2) % 256, (y * 3) % 256, 128)
    img.save(path)
    return img


def exif_with_gps() -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "TestCamera"          # Make
    exif[0x0110] = "TestModel 1"         # Model
    exif[0x0131] = "TestSoft 1.0"        # Software
    exif[0x8825] = {                     # GPSInfo
        1: "N",
        2: (23.0, 33.0, 0.0),
        3: "E",
        4: (90.0, 24.0, 0.0),
    }
    return exif


def insert_segment(jpeg_bytes: bytes, marker: int, payload: bytes) -> bytes:
    seg = bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload
    return jpeg_bytes[:2] + seg + jpeg_bytes[2:]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="meta-bot-test-") as tmp:
        tmp = Path(tmp)

        # --- 1. JPEG with EXIF + GPS -------------------------------------
        jpg_exif = tmp / "exif.jpg"
        img = Image.new("RGB", (120, 80), (200, 60, 40))
        img.save(jpg_exif, "JPEG", quality=95, exif=exif_with_gps())
        out = tmp / "exif-clean.jpg"
        rep = clean_image(jpg_exif, out)
        labels = [f["label"] for f in rep["found"]]
        check("JPEG EXIF found", "EXIF data block" in labels, str(labels))
        check("JPEG GPS found", "GPS location data" in labels, str(labels))
        check("JPEG camera found", "Camera / device" in labels, str(labels))
        check("JPEG not AI", rep["ai_label"] is False)
        check("JPEG output clean", rep["verified_clean"] is True)
        check("JPEG size kept", (rep["width"], rep["height"]) == (120, 80))
        check("JPEG pixels survive",
              mean_abs_diff(Image.open(jpg_exif), Image.open(out)) < 3.0)
        check("JPEG output has no EXIF",
              not Image.open(out).getexif())

        # --- 2. JPEG with XMP AI label (OpenAI / DALL-E) -----------------
        base_jpg = tmp / "base.jpg"
        Image.new("RGB", (100, 60), (30, 120, 200)).save(base_jpg, "JPEG", quality=95)
        xmp = (
            b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF>'
            b'<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            b'<dc:creator>OpenAI DALL-E</dc:creator>'
            b'<dc:description>ai-generated image</dc:description>'
            b'</rdf:Description></rdf:RDF></x:xmpmeta>'
        )
        payload = b"http://ns.adobe.com/xap/1.0/\x00" + xmp
        jpg_xmp = tmp / "xmp.jpg"
        jpg_xmp.write_bytes(insert_segment(base_jpg.read_bytes(), 0xE1, payload))
        out = tmp / "xmp-clean.jpg"
        rep = clean_image(jpg_xmp, out)
        labels = [f["label"] for f in rep["found"]]
        check("JPEG XMP block found", "XMP metadata block" in labels, str(labels))
        check("JPEG XMP flagged AI", rep["ai_label"] is True)
        check("JPEG XMP output clean", rep["verified_clean"] is True)
        check("JPEG XMP bytes gone",
              b"openai" not in out.read_bytes().lower()
              and b"dall" not in out.read_bytes().lower())

        # --- 3. JPEG with C2PA JUMBF block -------------------------------
        jumbf = (b"JUMBF" + b"\x00\x00\x00\x10jumb" + b"c2pa"
                 + b" ai-generated content credentials openai")
        jpg_c2pa = tmp / "c2pa.jpg"
        jpg_c2pa.write_bytes(insert_segment(base_jpg.read_bytes(), 0xEB, jumbf))
        out = tmp / "c2pa-clean.jpg"
        rep = clean_image(jpg_c2pa, out)
        labels = [f["label"] for f in rep["found"]]
        check("JPEG C2PA block found", "AI / C2PA data block" in labels, str(labels))
        check("JPEG C2PA flagged AI", rep["ai_label"] is True)
        check("JPEG C2PA output clean", rep["verified_clean"] is True)
        check("JPEG C2PA bytes gone",
              b"c2pa" not in out.read_bytes().lower()
              and b"jumbf" not in out.read_bytes().lower())

        # --- 4. PNG with text chunks + eXIf ------------------------------
        from PIL.PngImagePlugin import PngInfo
        png = tmp / "text.png"
        info = PngInfo()
        info.add_text("Software", "TestSoft 1.0")
        info.add_text("Generator", "Midjourney v6")
        info.add_text("Description", "ai-generated landscape")
        Image.new("RGB", (90, 70), (40, 180, 90)).save(
            png, "PNG", pnginfo=info, exif=exif_with_gps().tobytes())
        out = tmp / "text-clean.png"
        rep = clean_image(png, out)
        labels = [f["label"] for f in rep["found"]]
        check("PNG text chunks found",
              any(l.startswith("PNG text chunk") for l in labels), str(labels))
        check("PNG eXIf found", "EXIF data block" in labels, str(labels))
        check("PNG flagged AI", rep["ai_label"] is True)
        check("PNG output clean", rep["verified_clean"] is True)
        check("PNG pixels exact",
              list(Image.open(png).convert("RGB").getdata())
              == list(Image.open(out).convert("RGB").getdata()))
        check("PNG bytes clean",
              b"midjourney" not in out.read_bytes().lower()
              and b"testsoft" not in out.read_bytes().lower())

        # --- 5. WebP with EXIF -------------------------------------------
        webp = tmp / "exif.webp"
        Image.new("RGB", (110, 75), (90, 90, 200)).save(
            webp, "WEBP", quality=95, exif=exif_with_gps().tobytes())
        out = tmp / "exif-clean.webp"
        rep = clean_image(webp, out)
        labels = [f["label"] for f in rep["found"]]
        check("WebP EXIF found", "EXIF data block" in labels, str(labels))
        check("WebP output clean", rep["verified_clean"] is True)
        check("WebP size kept", (rep["width"], rep["height"]) == (110, 75))
        check("WebP pixels survive",
              mean_abs_diff(Image.open(webp), Image.open(out)) < 5.0)

        # --- 6. Already-clean images -------------------------------------
        clean_jpg = tmp / "clean.jpg"
        Image.new("RGB", (64, 48), (10, 200, 100)).save(clean_jpg, "JPEG", quality=95)
        rep = clean_image(clean_jpg, tmp / "clean-out.jpg")
        check("Clean JPEG reported already-clean", rep["already_clean"] is True)
        check("Clean JPEG not AI", rep["ai_label"] is False)

        clean_png = tmp / "clean.png"
        Image.new("RGB", (64, 48), (10, 200, 100)).save(clean_png, "PNG")
        rep = clean_image(clean_png, tmp / "clean-out.png")
        check("Clean PNG reported already-clean", rep["already_clean"] is True)

        # --- 7. Invalid file ---------------------------------------------
        bad = tmp / "bad.txt"
        bad.write_text("this is not an image")
        try:
            clean_image(bad, tmp / "bad-out.jpg")
            check("Invalid file rejected", False, "no error raised")
        except ValueError:
            check("Invalid file rejected", True)

        # --- 8. Independent re-scan of a cleaned file --------------------
        scan = scan_bytes((tmp / "xmp-clean.jpg").read_bytes(), "JPEG")
        check("Independent re-scan finds nothing",
              scan["found"] == [] and scan["ai"] is False)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES: {FAILURES}")
        return 1
    print("All tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
