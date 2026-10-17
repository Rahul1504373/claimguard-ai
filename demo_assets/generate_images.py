"""
Generates labeled placeholder "evidence" images for the live demo.
IMPORTANT — these are NOT real damage photos. They are simple illustrations
with embedded text describing the depicted damage, designed so Gemini's
real vision capability can genuinely read and reason about them (comparing
stated severity against the claim narrative) rather than the Consistency
Agent's output being scripted or faked. This is an honest simplification
for demo purposes, not a substitute for real evidence in production.
"""
from PIL import Image, ImageDraw, ImageFont

def make_image(filename, title, description, bg_color, accent_color):
    img = Image.new("RGB", (800, 600), color=bg_color)
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
        font_desc = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
        font_label = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except OSError:
        font_title = ImageFont.load_default()
        font_desc = ImageFont.load_default()
        font_label = ImageFont.load_default()

    draw.rectangle([0, 0, 800, 80], fill=accent_color)
    draw.text((30, 20), "CLAIM EVIDENCE PHOTO (DEMO PLACEHOLDER)", font=font_label, fill="white")

    draw.rectangle([40, 120, 760, 480], outline=accent_color, width=4)
    draw.text((60, 150), title, font=font_title, fill=(30, 30, 30))

    y = 230
    for line in description:
        draw.text((60, y), line, font=font_desc, fill=(60, 60, 60))
        y += 40

    draw.text((30, 550), "Illustrative placeholder — not a real photograph", font=font_label, fill=(150, 0, 0))

    img.save(filename)
    print(f"Created {filename}")

make_image(
    "images/minor_bumper_scuff.jpg", "MINOR COSMETIC DAMAGE",
    ["Location: Rear bumper, driver side", "Damage: Surface scratch, ~15cm", "Depth: Cosmetic only, no dent",
     "Structural damage: None visible"],
    (235, 245, 235), (60, 130, 60)
)

make_image(
    "images/major_structural_damage.jpg", "SEVERE STRUCTURAL DAMAGE",
    ["Location: Front-end, full width", "Damage: Frame deformation, airbags deployed", "Depth: Structural collapse",
     "Vehicle status: Undrivable, total loss likely"],
    (250, 235, 235), (170, 40, 40)
)

make_image(
    "images/intact_windshield.jpg", "INTACT WINDSHIELD",
    ["Condition: No cracks or chips visible", "Glass: Fully intact, clear visibility",
     "Wiper blades: Undamaged", "Frame seal: Intact"],
    (235, 240, 250), (50, 90, 160)
)

make_image(
    "images/water_damage_kitchen.jpg", "WATER DAMAGE — KITCHEN",
    ["Location: Under-sink cabinet area", "Damage: Swollen cabinet wood, water staining",
     "Flooring: Warped near cabinet base", "Source: Burst supply pipe (per plumber report)"],
    (235, 245, 250), (40, 120, 150)
)

make_image(
    "images/hospital_itemized_bill.jpg", "ITEMIZED HOSPITAL BILL",
    ["Facility: Network hospital", "Admission: 3 days, general ward",
     "Procedure: Laparoscopic appendectomy", "Total billed: as stated in claim narrative"],
    (245, 245, 235), (140, 120, 40)
)

make_image(
    "images/police_fir_theft.jpg", "POLICE FIR — VEHICLE THEFT",
    ["Report type: First Information Report", "Incident: Vehicle reported stolen overnight",
     "Location: Secured parking garage", "Status: Under police investigation"],
    (240, 240, 245), (80, 80, 130)
)
