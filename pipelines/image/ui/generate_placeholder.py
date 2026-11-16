"""One-off helper: generates assets/placeholder.png, a simple "no result yet"
image used by the mock backend in app.py. Run once via:
    python generate_placeholder.py
Not needed at app runtime once the placeholder image exists.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_PATH = Path(__file__).parent / "assets" / "placeholder.png"


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    width, height = 960, 540
    img = Image.new("RGB", (width, height), color=(30, 33, 38))
    draw = ImageDraw.Draw(img)

    # Simple frame
    draw.rectangle([0, 0, width - 1, height - 1], outline=(70, 74, 82), width=2)

    text = "NO RESULT YET"
    subtext = "(mock render — swap in real backend at run_query())"

    try:
        font_big = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42
        )
        font_small = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18
        )
    except OSError:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()

    def centered(text_str, font, y):
        bbox = draw.textbbox((0, 0), text_str, font=font)
        text_w = bbox[2] - bbox[0]
        draw.text(((width - text_w) / 2, y), text_str, font=font, fill=(200, 203, 209))

    centered(text, font_big, height / 2 - 40)
    centered(subtext, font_small, height / 2 + 20)

    img.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
