"""Draw the Kaggle cover of each dataset: the logo with the year written over it.

Run with `uv run --with pillow python scripts/make_thumbnails.py`. It reads `thumbnails/thumbnail.jpg`
and `thumbnails/Shrikhand-Regular.ttf`, and writes one PNG per dataset next to them.
"""

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

THUMBNAILS_DIR = Path(__file__).parents[1] / "thumbnails"
# Kaggle shows a cover twice as wide as it is high, and cuts its thumbnail from the square in the middle.
SIZE = (4608, 2304)
LOGO_WIDTH = 3456
ORANGE = "#ff751f"
FIRST_YEAR = 2014

# Font sizes are the ones of the Canva mock-up, where a point is 1.334 px with the logo this wide.
PX_PER_POINT = 1.334
YEAR_POINTS = 500
LITE_POINTS = 270

# Centre of the text, a little under the middle so it sits on the bottom of the shield.
TEXT_CENTRE_Y = 1715


def cover(logo: Image.Image, text: str, points: int) -> Image.Image:
    # The logo sits at the top, in the middle, and its background colour fills the rest.
    image = Image.new("RGB", SIZE, logo.getpixel((0, 0)))
    resized = logo.resize((LOGO_WIDTH, round(logo.height * LOGO_WIDTH / logo.width)), Image.Resampling.LANCZOS)
    image.paste(resized, ((SIZE[0] - LOGO_WIDTH) // 2, 0))
    font = ImageFont.truetype(THUMBNAILS_DIR / "Shrikhand-Regular.ttf", round(points * PX_PER_POINT))
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((SIZE[0] - left - right) / 2, TEXT_CENTRE_Y - (top + bottom) / 2),
        text,
        font=font,
        fill=ORANGE,
    )
    return image


def main() -> None:
    logo = Image.open(THUMBNAILS_DIR / "thumbnail.jpg").convert("RGB")
    this_year = date.today().year
    for year in range(FIRST_YEAR, this_year + 1):
        cover(logo, str(year), YEAR_POINTS).save(THUMBNAILS_DIR / f"thumbnail_smogon_dataset_{year}.png")
    cover(logo, f"{FIRST_YEAR}-{this_year}", LITE_POINTS).save(THUMBNAILS_DIR / "thumbnail_smogon_dataset_lite.png")


if __name__ == "__main__":
    main()
