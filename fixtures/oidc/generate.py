"""Regenerate synthetic, nonprivate page images with the pinned image's Pillow.

Run from repository root in the candidate container, with this directory mounted.
Original text is immutable input; render mapping describes these exact PNG bytes.
"""

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).parent
original = "SYNTHETIC RESEARCH NOTE\nLeft column: Café naïve résumé — αβ.\nRight column: Corrected Unicode transcription.\fPAGE TWO\nLeft column: Reading order crosses columns.\nRight column: Shared-trust corpus only.\n"
(root / "original.txt").write_text(original, encoding="utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


pages = []
font = ImageFont.load_default(size=24)
for number, text in enumerate(original.split("\f"), 1):
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    lines = text.splitlines()
    draw.text((70, 80), lines[0], fill="black", font=font)
    for x, line in zip([70, 650], lines[1:]):
        # Render ASCII approximation in the raster; correction evidence retains Unicode.
        words = line.split()
        for i in range(0, len(words), 4):
            draw.text((x, 220 + (i // 4) * 42), " ".join(words[i : i + 4]), fill="black", font=font)
    filename = f"page-{number}.png"
    image.save(root / filename)
    pages.append(
        {
            "page_id": f"doc-001/page-{number}",
            "page_number": number,
            "file": filename,
            "sha256": digest((root / filename).read_bytes()),
            "width": 1200,
            "height": 1600,
            "rotation": 0,
            "original_page_sha256": digest((root / filename).read_bytes()),
            "render_sha256": digest((root / filename).read_bytes()),
            "original_page_raster_to_render": [1, 0, 0, 1, 0, 0],
            "coordinate_system": "Native rectangle percentages of this exact raster; x/y top-left",
        }
    )
manifest = {
    "document_id": "doc-001",
    "original_file": "original.txt",
    "original_sha256": digest((root / "original.txt").read_bytes()),
    "render_contract": "Synthetic page-image document, not a PDF editor; one native task per page",
    "source_text_has_geometric_coordinates": False,
    "pages": pages,
}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
tasks = [
    {
        "data": {
            "document_id": "doc-001",
            "page_id": p["page_id"],
            "page_number": p["page_number"],
            "image": "https://labels.localhost:8443/static/oidc-fixture/" + p["file"],
            "original_sha256": manifest["original_sha256"],
            "page_sha256": p["sha256"],
            "original_page_sha256": p["original_page_sha256"],
            "render_sha256": p["render_sha256"],
        }
    }
    for p in pages
]
(root / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n")
results = [
    {
        "id": "left",
        "from_name": "region",
        "to_name": "page",
        "type": "rectanglelabels",
        "original_width": 1200,
        "original_height": 1600,
        "image_rotation": 0,
        "value": {"x": 5, "y": 12, "width": 40, "height": 20, "rotation": 0, "rectanglelabels": ["Paragraph"]},
    },
    {
        "id": "left",
        "from_name": "transcription",
        "to_name": "page",
        "type": "textarea",
        "value": {"text": ["Café naïve résumé — αβ. Corrected transcription."]},
    },
    {
        "id": "right",
        "from_name": "region",
        "to_name": "page",
        "type": "rectanglelabels",
        "original_width": 1200,
        "original_height": 1600,
        "image_rotation": 0,
        "value": {"x": 54, "y": 12, "width": 40, "height": 20, "rotation": 0, "rectanglelabels": ["Paragraph"]},
    },
    {"from_id": "left", "to_id": "right", "type": "relation", "direction": "right", "labels": ["precedes"]},
    {"from_name": "page_class", "to_name": "page", "type": "choices", "value": {"choices": ["Body"]}},
    {"from_name": "document_class", "to_name": "page", "type": "choices", "value": {"choices": ["Research note"]}},
]
(root / "result.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
