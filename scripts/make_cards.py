"""Make fake insurance card images (front only) for the demo and Step 2's extraction eval.

    uv run --project api scripts/make_cards.py

Writes data/cards/*.png|jpg and data/cards/truth.json (the true field values of each
card). Payers are the fictional ones in data/payers.json. Every card says SAMPLE twice:
a large diagonal watermark and a "not a real insurance card" banner. Deterministic:
member IDs and group numbers come from a fixed seed, so reruns give the same cards.
"""

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "cards"
PAYERS_FILE = ROOT / "data" / "payers.json"

W, H = 1012, 638  # ID-1 card ratio (3.375 x 2.125 in) at 300 dpi
SEED = 5150
SAMPLE_BANNER = "SAMPLE - NOT A REAL INSURANCE CARD - DEMO DATA"

# Demo patients (seeded by scripts/seed.py) and the fictional payer each one's
# Synthea payer maps to (data/payers.json).
PEOPLE = {
    "aja": ("Aja Casper", "Riverbend Health"),
    "bart": ("Bart Brekke", "Liberty Senior Advantage"),
    "marissa": ("Marissa Dori", "Northstar Benefits"),  # out of network
}
COLORS = {  # header color per payer
    "Riverbend Health": (24, 98, 120),
    "Liberty Senior Advantage": (120, 40, 60),
    "Northstar Benefits": (40, 50, 110),
}
# Printed copays (from data/contracts/; Northstar has no contract with us).
COPAYS = {
    "Riverbend Health": "PCP $20   SPEC $50   ER $300",
    "Liberty Senior Advantage": "PCP $0   SPEC $35   ER $110",
    "Northstar Benefits": "PCP $25   SPEC $55   ER $400",
}
ID_PREFIX = {"Riverbend Health": "RBH", "Liberty Senior Advantage": "LSA", "Northstar Benefits": "NSB"}


@dataclass
class CardTruth:
    file: str
    patient: str
    variation: str  # clean | rotated | lowres | alt-layout
    payer: str
    plan_name: str
    member_name: str
    member_id: str
    group_number: str
    in_network: bool


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)  # Pillow's built-in font: same on every machine


def watermark(card: Image.Image, drawn: list[str]) -> Image.Image:
    """Large diagonal SAMPLE across the whole card."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((W // 2, H // 2), "SAMPLE", font=font(190), fill=(200, 30, 30, 70), anchor="mm")
    drawn.append("SAMPLE")
    return Image.alpha_composite(card.convert("RGBA"), layer.rotate(25, center=(W // 2, H // 2)))


def banner(d: ImageDraw.ImageDraw, drawn: list[str]) -> None:
    d.rectangle([0, H - 52, W, H], fill=(200, 30, 30))
    d.text((W // 2, H - 26), SAMPLE_BANNER, font=font(26), fill="white", anchor="mm")
    drawn.append(SAMPLE_BANNER)


def text(d: ImageDraw.ImageDraw, drawn: list[str], xy, s: str, size: int, fill="black", **kw) -> None:
    d.text(xy, s, font=font(size), fill=fill, **kw)
    drawn.append(s)


def classic(t: CardTruth, drawn: list[str]) -> Image.Image:
    """Header bar with payer name; labeled fields below."""
    card = Image.new("RGB", (W, H), (247, 248, 250))
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, W, 120], fill=COLORS[t.payer])
    text(d, drawn, (40, 30), t.payer, 52, "white")
    text(d, drawn, (40, 140), t.plan_name, 34, (40, 40, 40))
    rows = [("Member", t.member_name), ("Member ID", t.member_id), ("Group No.", t.group_number)]
    for i, (label, value) in enumerate(rows):
        text(d, drawn, (40, 215 + i * 78), label.upper(), 22, (110, 110, 110))
        text(d, drawn, (40, 241 + i * 78), value, 38)
    text(d, drawn, (560, 230), "RxBIN 610591", 24, (90, 90, 90))
    text(d, drawn, (560, 264), "RxPCN ADV", 24, (90, 90, 90))
    text(d, drawn, (560, 330), COPAYS[t.payer], 22, (60, 60, 60))
    text(d, drawn, (560, 380), "Member services 1-800-555-0199", 22, (90, 90, 90))
    banner(d, drawn)
    return watermark(card, drawn).convert("RGB")


def alt_layout(t: CardTruth, drawn: list[str]) -> Image.Image:
    """A different design: side stripe, short labels, fields in another order."""
    card = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, 70, H], fill=COLORS[t.payer])
    text(d, drawn, (110, 34), t.payer.upper(), 40, COLORS[t.payer])
    text(d, drawn, (110, 120), f"ID# {t.member_id}", 40)
    text(d, drawn, (110, 185), f"Grp {t.group_number}", 34)
    text(d, drawn, (110, 255), t.member_name.upper(), 36)
    text(d, drawn, (110, 330), f"Plan: {t.plan_name}", 28, (60, 60, 60))
    text(d, drawn, (110, 400), COPAYS[t.payer], 24, (60, 60, 60))
    banner(d, drawn)
    return watermark(card, drawn).convert("RGB")


def rotated(card: Image.Image, rng: random.Random) -> Image.Image:
    """Tilted 7 degrees on a mottled 'table' background, like a quick phone photo."""
    bg = Image.new("RGB", (W + 300, H + 260), (150, 135, 115))
    noise = Image.effect_noise(bg.size, 18).convert("RGB")
    bg = Image.blend(bg, noise, 0.15)
    tilted = card.rotate(7, expand=True, resample=Image.BICUBIC, fillcolor=(150, 135, 115))
    bg.paste(tilted, (rng.randint(60, 110), rng.randint(40, 80)))
    return bg


def low_quality(card: Image.Image) -> Image.Image:
    small = card.resize((W * 2 // 5, H * 2 // 5), Image.BILINEAR)
    return small.filter(ImageFilter.GaussianBlur(0.8))


def truth_for(key: str, variation: str, payers: dict[str, dict], rng: random.Random, filename: str) -> CardTruth:
    name, payer = PEOPLE[key]
    return CardTruth(
        file=filename, patient=name, variation=variation, payer=payer,
        plan_name=payers[payer]["plan_name"], member_name=name,
        member_id=f"{ID_PREFIX[payer]}{rng.randint(10**8, 10**9 - 1)}",
        group_number=f"{rng.randint(10000, 99999)}",
        in_network=payers[payer]["in_network"],
    )


def make_cards(out_dir: Path = OUT_DIR) -> list[tuple[CardTruth, list[str]]]:
    """Write every card and truth.json. Returns (truth, texts drawn on it) per card."""
    rng = random.Random(SEED)
    payers = {p["payer"]: p for p in json.loads(PAYERS_FILE.read_text())["payers"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    # One identity per person, shared by all of their card variations.
    base = {key: truth_for(key, "clean", payers, rng, f"{key}.png") for key in PEOPLE}

    plan = [  # (person, variation, file)
        ("aja", "clean", "aja.png"), ("bart", "clean", "bart.png"), ("marissa", "clean", "marissa.png"),
        ("aja", "rotated", "aja-rotated.png"), ("aja", "lowres", "aja-lowres.jpg"),
        ("bart", "alt-layout", "bart-alt-layout.png"),
    ]
    results = []
    for key, variation, filename in plan:
        truth = CardTruth(**{**asdict(base[key]), "variation": variation, "file": filename})
        drawn: list[str] = []
        image = alt_layout(truth, drawn) if variation == "alt-layout" else classic(truth, drawn)
        if variation == "rotated":
            image = rotated(image, rng)
        if variation == "lowres":
            low_quality(image).save(out_dir / filename, quality=30)
        else:
            image.save(out_dir / filename)
        results.append((truth, drawn))

    (out_dir / "truth.json").write_text(json.dumps({
        "about": "True field values of each sample card (fictional payers, data/payers.json). "
                 "Made by scripts/make_cards.py; every card is marked SAMPLE.",
        "cards": [asdict(t) for t, _ in results],
    }, indent=2) + "\n")
    return results


if __name__ == "__main__":
    for truth, _ in make_cards():
        print(f"  {truth.file:22} {truth.variation:10} {truth.payer} / {truth.member_id} "
              f"({'in' if truth.in_network else 'OUT of'} network)")
    print(f"Wrote {OUT_DIR.relative_to(ROOT)}/ and truth.json")
