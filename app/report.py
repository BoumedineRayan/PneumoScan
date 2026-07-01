"""
Génère un rapport de diagnostic PDF épuré à partir d'un résultat JSON.
Thème vert, mise en page sobre via reportlab Platypus.
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

# Palette verte de l'application
GREEN_DARK = colors.HexColor("#1B5E3F")
GREEN = colors.HexColor("#2E8B57")
GREEN_LIGHT = colors.HexColor("#E6F4EC")
GREY = colors.HexColor("#555555")

CLASS_LABELS = {
    "normal": "Normal",
    "suspected_opacity": "Suspicion d'opacite",
    "uncertain": "Incertain",
}


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("TitleGreen", parent=s["Title"],
                         textColor=GREEN_DARK, fontSize=20, spaceAfter=2))
    s.add(ParagraphStyle("Sub", parent=s["Normal"],
                         textColor=GREY, fontSize=9, spaceAfter=10))
    s.add(ParagraphStyle("H", parent=s["Heading2"],
                         textColor=GREEN_DARK, fontSize=12, spaceBefore=10, spaceAfter=4))
    s.add(ParagraphStyle("Body", parent=s["Normal"], fontSize=10, leading=15))
    s.add(ParagraphStyle("Warn", parent=s["Normal"], fontSize=9,
                         textColor=colors.HexColor("#8A5A00"), leading=13))
    return s


def build_report(result: dict, filename: str, variant: str, latency: float) -> bytes:
    """Construit le PDF en mémoire et renvoie ses octets."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=20*mm, bottomMargin=18*mm,
                            leftMargin=20*mm, rightMargin=20*mm)
    s = _styles()
    story = []

    # En-tete
    story.append(Paragraph("Rapport d'analyse - Radiographie thoracique", s["TitleGreen"]))
    story.append(Paragraph(
        f"Prototype pedagogique d'IA multimodale &nbsp;|&nbsp; "
        f"Genere le {datetime.now().strftime('%d/%m/%Y a %H:%M')}", s["Sub"]))
    story.append(HRFlowable(width="100%", color=GREEN, thickness=2, spaceAfter=12))

    # Bloc resultat principal (tableau)
    cls = result.get("predicted_class", "uncertain")
    conf = result.get("confidence", 0.0)
    rows = [
        ["Image analysee", filename],
        ["Variante de prompt", variant],
        ["Classe predite", CLASS_LABELS.get(cls, cls)],
        ["Confiance", f"{conf:.2f}"],
        ["Qualite d'image", result.get("image_quality", "")],
        ["Latence", f"{latency:.1f} s"],
    ]
    t = Table(rows, colWidths=[55*mm, 105*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), GREEN_LIGHT),
        ("TEXTCOLOR", (0, 0), (0, -1), GREEN_DARK),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, GREEN),
    ]))
    story.append(t)

    # Observations visuelles
    ve = result.get("visual_evidence", [])
    if ve:
        story.append(Paragraph("Observations visuelles", s["H"]))
        for obs in ve:
            story.append(Paragraph(f"&bull; {obs}", s["Body"]))

    # Justification
    just = result.get("justification", "")
    if just:
        story.append(Paragraph("Justification", s["H"]))
        story.append(Paragraph(just, s["Body"]))

    # Limites
    lim = result.get("limitations", [])
    if lim:
        story.append(Paragraph("Limites de l'analyse", s["H"]))
        for l in lim:
            story.append(Paragraph(f"&bull; {l}", s["Body"]))

    # Avertissement
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", color=GREEN_LIGHT, thickness=1, spaceAfter=8))
    story.append(Paragraph(
        "<b>Avertissement.</b> " + result.get("warning", ""), s["Warn"]))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
