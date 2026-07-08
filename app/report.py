"""
Génère le rapport de diagnostic PDF (thème bleu) via reportlab Platypus.
"""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

GREY = colors.HexColor("#555555")

CLASS_LABELS = {
    "normal": "Normal",
    "suspected_opacity": "Suspicion d'opacite",
    "uncertain": "Incertain",
}


# ---------------- Palette bleue (rapport médecin) ----------------
BLUE_DARK = colors.HexColor("#1E3A8A")
BLUE = colors.HexColor("#3B82F6")
BLUE_SOFT = colors.HexColor("#EFF6FF")
BLUE_LINE = colors.HexColor("#BFDBFE")

CLASS_COLORS = {
    "normal": BLUE,
    "suspected_opacity": colors.HexColor("#C9821B"),
    "uncertain": colors.HexColor("#6B7A71"),
}


def _styles_blue():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("TitleBlue", parent=s["Title"],
                         textColor=BLUE_DARK, fontSize=17, spaceAfter=1, leading=20))
    s.add(ParagraphStyle("SubB", parent=s["Normal"],
                         textColor=GREY, fontSize=8, spaceAfter=6, leading=11))
    s.add(ParagraphStyle("HB", parent=s["Heading2"],
                         textColor=BLUE_DARK, fontSize=10.5, spaceBefore=7, spaceAfter=2))
    s.add(ParagraphStyle("BodyB", parent=s["Normal"], fontSize=9, leading=12.5))
    s.add(ParagraphStyle("WarnB", parent=s["Normal"], fontSize=7.5,
                         textColor=colors.HexColor("#8A5A00"), leading=10))
    return s


def build_detailed_report(result: dict, filename: str, variant: str,
                          base_latency: float, detail_latency: float,
                          radio_png: bytes | None) -> bytes:
    """
    Rapport PDF COMPACT (1 page), thème BLEU.
    Affiche la radiographie analysée + synthèse (verdict, localisation, confiance).
    """
    from reportlab.platypus import Image as RLImage

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=15*mm, bottomMargin=12*mm,
                            leftMargin=16*mm, rightMargin=16*mm)
    s = _styles_blue()
    story = []

    cls = result.get("predicted_class", "uncertain")
    conf = result.get("confidence", 0.0)
    cls_label = CLASS_LABELS.get(cls, cls)
    cls_color = CLASS_COLORS.get(cls, BLUE)

    # En-tête
    story.append(Paragraph("Compte rendu — Radiographie thoracique", s["TitleBlue"]))
    story.append(Paragraph(
        f"Prototype pédagogique d'IA multimodale &nbsp;|&nbsp; "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')} &nbsp;|&nbsp; Image : {filename}",
        s["SubB"]))
    story.append(HRFlowable(width="100%", color=BLUE, thickness=2, spaceAfter=8))

    # --- Bloc central : radiographie (gauche) + synthèse (droite) ---
    if radio_png:
        img = RLImage(io.BytesIO(radio_png))
        target_w = 78 * mm
        ratio = img.imageHeight / float(img.imageWidth)
        img.drawWidth = target_w
        img.drawHeight = min(target_w * ratio, 90 * mm)
        left_cell = [
            Paragraph("Radiographie analysée", s["HB"]),
            img,
        ]
    else:
        left_cell = [
            Paragraph("Radiographie analysée", s["HB"]),
            Paragraph("Image non disponible.", s["BodyB"]),
        ]

    # Colonne droite : verdict + localisation + confiance/qualité
    badge = Table([[Paragraph(f"<b>{cls_label}</b>", ParagraphStyle(
        "b", fontSize=11, textColor=colors.white, alignment=1))]], colWidths=[70*mm])
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), cls_color),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    loc = result.get("localisation") or "—"
    meta = Table(
        [["Localisation", loc],
         ["Confiance", f"{conf:.2f}"],
         ["Qualité image", result.get("image_quality", "")],
         ["Latences", f"diag {base_latency:.1f}s · rapport {detail_latency:.1f}s"]],
        colWidths=[26*mm, 44*mm])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), BLUE_SOFT),
        ("TEXTCOLOR", (0, 0), (0, -1), BLUE_DARK),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, BLUE_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BLUE_LINE),
    ]))
    right_cell = [badge, Spacer(1, 6), meta]
    if result.get("signe_principal"):
        right_cell += [Spacer(1, 6), Paragraph("Signe principal", s["HB"]),
                       Paragraph(result["signe_principal"], s["BodyB"])]

    central = Table([[left_cell, right_cell]], colWidths=[85*mm, 78*mm])
    central.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
    ]))
    story.append(central)

    # --- Observations (puces courtes) ---
    obs = result.get("observations", [])
    if obs:
        story.append(Paragraph("Observations", s["HB"]))
        for o in obs[:3]:
            story.append(Paragraph(f"&bull; {o}", s["BodyB"]))

    # --- Justification (1 ligne) ---
    if result.get("justification"):
        story.append(Paragraph("Justification", s["HB"]))
        story.append(Paragraph(result["justification"], s["BodyB"]))

    # --- Limites (1 ligne) ---
    if result.get("limitations"):
        story.append(Paragraph("Limites", s["HB"]))
        story.append(Paragraph(result["limitations"], s["BodyB"]))

    # Avertissement
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", color=BLUE_LINE, thickness=1, spaceAfter=5))
    story.append(Paragraph("<b>Avertissement.</b> " + result.get("warning", ""), s["WarnB"]))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
