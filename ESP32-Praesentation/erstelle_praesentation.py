"""Erstellt eine professionelle, rein deutsche und praegnante 5-seitige PowerPoint-Praesentation
zum ESP32-Handheld-Projekt und speichert sie direkt im Downloads-Ordner sowie im Projektordner.
"""
import os
import shutil
from lxml import etree
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn

BASE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(BASE, "bilder")
GEN = os.path.join(IMG, "_generiert")
os.makedirs(GEN, exist_ok=True)

# ---------------- Design-System ----------------
CANVAS = RGBColor(0xF8, 0xFA, 0xFC)       # Slate 50 - Hintergrund
CARD_BG = RGBColor(0xFF, 0xFF, 0xFF)      # Reines Weiss fuer Karten
CARD_BORDER = RGBColor(0xE2, 0xE8, 0xF0)  # Slate 200 - feine Trennlinien
CAD_BG = RGBColor(0x0A, 0x11, 0x24)       # Deep Midnight fuer CAD-Fenster
CAD_BORDER = RGBColor(0x1E, 0x29, 0x3B)

INK_900 = RGBColor(0x0F, 0x17, 0x2A)      # Slate 900 - Titel
INK_700 = RGBColor(0x33, 0x41, 0x55)      # Slate 700 - Fließtext
INK_500 = RGBColor(0x64, 0x74, 0x8B)      # Slate 500 - Sekundaertext
INK_400 = RGBColor(0x94, 0xA3, 0xB8)      # Slate 400 - Subtiles

BLUE_600 = RGBColor(0x25, 0x63, 0xEB)     # Royal Blue - Primaerer Akzent
BLUE_50 = RGBColor(0xEF, 0xF6, 0xFF)      # Ice Blue - dezente Akzentflaechen
TEAL_600 = RGBColor(0x0D, 0x94, 0x88)     # Teal - Erfolge & Status
TEAL_50 = RGBColor(0xF0, 0xFD, 0xFA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

F_HEAD = "Segoe UI Semibold"
F_BODY = "Segoe UI"

PROJECT = "ESP32-Handheld"
AUTHOR = "Samir"
DATE = "Oktober 2026"
TOTAL = 5


# ---------------- Bild-Aufbereitung ----------------
def make_transparent(name, thresh=24):
    src = os.path.join(IMG, name)
    dst = os.path.join(GEN, os.path.splitext(name)[0] + "_clean.png")
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    for xy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        if sum(im.getpixel(xy)[:3]) < 60:
            ImageDraw.floodfill(im, xy, (0, 0, 0, 0), thresh=thresh)
    bbox = im.getchannel("A").getbbox()
    if bbox:
        im = im.crop(bbox)
    im.save(dst)
    return dst


PCB_FRONT = make_transparent("pcb_3d_vorne.png")
PCB_BACK = make_transparent("pcb_3d_hinten.png")
PCB_2D = make_transparent("pcb_2d.png")

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
SW, SH = 13.333, 7.5
BLANK = prs.slide_layouts[6]
ML = 0.75  # Linker/rechter Rand


# ---------------- Helfer-Funktionen ----------------
def _spPr(shape):
    return shape._element.spPr


def add_subtle_shadow(shape):
    spPr = _spPr(shape)
    lst = spPr.find(qn("a:effectLst"))
    if lst is None:
        lst = etree.SubElement(spPr, qn("a:effectLst"))
    sh = etree.SubElement(lst, qn("a:outerShdw"))
    sh.set("blurRad", str(int(Pt(14))))
    sh.set("dist", str(int(Pt(3))))
    sh.set("dir", "5400000")
    sh.set("algn", "t")
    sh.set("rotWithShape", "0")
    c = etree.SubElement(sh, qn("a:srgbClr"))
    c.set("val", "0F172A")
    a = etree.SubElement(c, qn("a:alpha"))
    a.set("val", "8000")  # 8% Deckkraft


def add_transition(slide):
    slide._element.append(etree.fromstring(
        '<p:transition xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'spd="med"><p:fade/></p:transition>'))


def notes(slide, txt):
    slide.notes_slide.notes_text_frame.text = txt


def rect(s, x, y, w, h, color, shape=MSO_SHAPE.RECTANGLE, line=None, line_w=0.75, radius=None):
    sh = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if color is None:
        sh.fill.background()
    else:
        sh.fill.solid(); sh.fill.fore_color.rgb = color
    if line:
        sh.line.color.rgb = line; sh.line.width = Pt(line_w)
    else:
        sh.line.fill.background()
    if radius is not None:
        sh.adjustments[0] = radius
    sh.shadow.inherit = False
    return sh


def card(s, x, y, w, h, bg=CARD_BG, border=CARD_BORDER, shadow=True, radius=0.04):
    c = rect(s, x, y, w, h, bg, MSO_SHAPE.ROUNDED_RECTANGLE, line=border, radius=radius)
    if shadow:
        add_subtle_shadow(c)
    return c


def hline(s, x, y, w, color=CARD_BORDER, width=0.75):
    return rect(s, x, y, w, 0.012, color, line_w=width)


def text(s, runs, x, y, w, h, size=15, color=INK_900, font=F_BODY, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, spacing=None):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    if isinstance(runs, str):
        runs = [(runs, color, font)]
    p = tf.paragraphs[0]; p.alignment = align
    if spacing:
        p.line_spacing = spacing
    for r in runs:
        t, c, f = (list(r) + [color, font])[:3]
        for i, part in enumerate(t.split("\n")):
            if i > 0:
                p = tf.add_paragraph(); p.alignment = align
                if spacing:
                    p.line_spacing = spacing
            run = p.add_run(); run.text = part
            run.font.size = Pt(size); run.font.color.rgb = c; run.font.name = f
    return tb


def pill(s, label, x, y, w, h, bg=BLUE_50, txt_color=BLUE_600, size=11, font=F_HEAD, border=None):
    p = rect(s, x, y, w, h, bg, MSO_SHAPE.ROUNDED_RECTANGLE, line=border, radius=0.5)
    tf = p.text_frame
    tf.margin_left = tf.margin_right = Inches(0.08); tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    para = tf.paragraphs[0]; para.alignment = PP_ALIGN.CENTER
    r = para.add_run(); r.text = label
    r.font.size = Pt(size); r.font.color.rgb = txt_color; r.font.name = font
    return p


def cad_window(s, x, y, w, h, title_txt):
    win = rect(s, x, y, w, h, CAD_BG, MSO_SHAPE.ROUNDED_RECTANGLE, line=CAD_BORDER, radius=0.03)
    add_subtle_shadow(win)
    top_bar = rect(s, x, y, w, 0.36, RGBColor(0x07, 0x0D, 0x1C), MSO_SHAPE.ROUNDED_RECTANGLE,
                   line=CAD_BORDER, radius=0.03)
    for i, col in enumerate([RGBColor(0xEF, 0x44, 0x44), RGBColor(0xF5, 0x9E, 0x0B), RGBColor(0x10, 0xB9, 0x81)]):
        rect(s, x + 0.15 + i * 0.16, y + 0.13, 0.09, 0.09, col, MSO_SHAPE.OVAL)
    text(s, title_txt, x + 0.72, y + 0.08, w - 0.8, 0.25, size=10, color=INK_400, font=F_HEAD)
    return win


def picture_fit(s, path, x, y, w, h):
    iw, ih = Image.open(path).size
    sc = min(w / iw, h / ih)
    pw, ph = iw * sc, ih * sc
    return s.shapes.add_picture(path, Inches(x + (w - pw) / 2), Inches(y + (h - ph) / 2),
                                Inches(pw), Inches(ph))


def base_slide(nr, kicker, title_txt, sub_txt=None):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid(); s.background.fill.fore_color.rgb = CANVAS
    pill(s, kicker.upper(), ML, 0.42, 2.0, 0.26, bg=BLUE_50, txt_color=BLUE_600, size=9.5, font=F_HEAD)
    text(s, title_txt, ML, 0.74, 10.5, 0.52, size=27, font=F_HEAD)
    if sub_txt:
        text(s, sub_txt, ML, 1.3, 11.5, 0.32, size=12.5, color=INK_500, font=F_BODY)
    hline(s, ML, 7.0, SW - 2 * ML)
    text(s, [(PROJECT, INK_700, F_HEAD), ("   |   Projektpräsentation   ·   Entwickler: " + AUTHOR, INK_500, F_BODY)],
         ML, 7.1, 8.0, 0.25, size=10)
    text(s, [("Folie ", INK_400, F_BODY), (f"{nr:02d}", INK_900, F_HEAD), (f" von {TOTAL:02d}", INK_400, F_BODY)],
         SW - ML - 2.0, 7.1, 2.0, 0.25, size=10, align=PP_ALIGN.RIGHT)
    add_transition(s)
    return s


# =====================================================================
# FOLIE 1 – TITEL (DEUTSCH, KURZ & PROFESSIONELL)
# =====================================================================
s = prs.slides.add_slide(BLANK)
s.background.fill.solid(); s.background.fill.fore_color.rgb = CANVAS

# Linker Bereich: Titel & Eckdaten
pill(s, "HARDWARE-ENTWICKLUNG  ·  ELEKTRONIK", ML, 0.75, 3.8, 0.32,
     bg=BLUE_50, txt_color=BLUE_600, size=11, font=F_HEAD)

text(s, "ESP32-Handheld", ML, 1.2, 6.8, 0.85, size=50, font=F_HEAD, color=INK_900)

text(s, "Kompakte Steuereinheit mit 2\"-Farbdisplay,\n"
        "4 Bedientasten und maßgefertigter 2-Lagen-Platine.",
     ML, 2.1, 6.4, 0.7, size=15.5, color=INK_700, font=F_BODY, spacing=1.2)

# Meta-Kachel Links
meta_card = card(s, ML, 3.1, 6.3, 3.5)
text(s, "PROJEKT-ÜBERSICHT & ECKDATEN", ML + 0.3, 3.3, 5.7, 0.3, size=11, color=BLUE_600, font=F_HEAD)
hline(s, ML + 0.3, 3.65, 5.7)

specs = [
    ("Entwickler", AUTHOR, "Schaltungsentwurf & PCB-Design"),
    ("Prozessor", "ESP32 DevKit (CP2102)", "Dual-Core 240 MHz · WLAN & Bluetooth"),
    ("Anzeige", "2,0\" TFT-Farbdisplay (ST7789)", "240 × 240 Pixel · Schneller SPI-Bus"),
    ("Bedienung", "4 Taktile Drucktaster", "UP, DOWN, SELECT, BACK (GPIO)"),
    ("Platine", "Eigene 2-Lagen-Leiterplatte", "Bauhöhe: ca. 63 mm (2473 mil)"),
]
yy = 3.85
for label, val, sub in specs:
    text(s, label, ML + 0.3, yy, 1.3, 0.25, size=12, color=INK_500, font=F_BODY)
    text(s, [(val, INK_900, F_HEAD), ("  ·  " + sub, INK_500, F_BODY)],
         ML + 1.65, yy, 4.35, 0.25, size=12)
    yy += 0.48

# Rechter Bereich: CAD-Viewer mit 3D-Platine
cad_window(s, 7.45, 0.75, 5.15, 5.85, "3D-CAD-MODELL · ANSICHT OBERSEITE")
picture_fit(s, PCB_FRONT, 7.7, 1.25, 4.65, 4.7)
pill(s, "2 LAGEN  ·  FR4  ·  62,8 × 42,5 mm", 7.7, 6.1, 4.65, 0.38,
     bg=RGBColor(0x16, 0x24, 0x45), txt_color=RGBColor(0x93, 0xC5, 0xFD), size=11, font=F_HEAD)

# Footer
hline(s, ML, 7.0, SW - 2 * ML)
text(s, f"{PROJECT}   |   {AUTHOR}   ·   {DATE}", ML, 7.1, 6.0, 0.25, size=10, color=INK_500)
text(s, "01 / 05", SW - ML - 1.0, 7.1, 1.0, 0.25, size=10, color=INK_500, align=PP_ALIGN.RIGHT)
add_transition(s)
notes(s, "Guten Tag. Ich stelle mein Projekt 'ESP32-Handheld' vor: eine kompakte Steuereinheit "
         "mit Farbdisplay, vier Tasten und einer selbst entwickelten Platine – vom Schaltplan "
         "bis zum fertigen 3D-Modell.")


# =====================================================================
# FOLIE 2 – DIE KOMPONENTEN (PRÄGNANT & DEUTSCH)
# =====================================================================
s = base_slide(2, "Hardware-Übersicht", "Die Komponenten",
               "Vier Kernkomponenten bilden die funktionale Basis der Steuereinheit.")

comp_cards = [
    ("MIKROCONTROLLER", "240 MHz Dual-Core", BLUE_50, BLUE_600,
     "ESP32 DevKit (CP2102)",
     [
         ("Rechenleistung", "Xtensa 32-Bit Dual-Core Prozessor mit bis zu 240 MHz"),
         ("Funkmodule", "Integriertes 2,4 GHz WLAN und Bluetooth 4.2"),
         ("USB-Schnittstelle", "CP2102-Chip für direkte Programmierung & seriellen Monitor"),
         ("Montage", "Standardisiertes 30-Pin-Board, steckbar gesockelt"),
     ]),
    ("DISPLAY", "240 × 240 Pixel", BLUE_50, BLUE_600,
     "2,0\" TFT-Farbdisplay",
     [
         ("Grafiktreiber", "ST7789-Controller mit 16-Bit RGB565 Farbtiefe"),
         ("Anbindung", "Schneller 4-Draht-SPI-Bus für flüssige Bildwechsel"),
         ("Spannung", "Direkter 3,3-V-Betrieb ohne externe Pegelwandler"),
         ("Blickwinkel", "Hoher Kontrast und weite Betrachtungswinkel dank IPS-Panel"),
     ]),
    ("BEDIENUNG", "4 Digitaleingänge", TEAL_50, TEAL_600,
     "4 Taktile Bedientaster",
     [
         ("Funktion", "UP, DOWN, SELECT und BACK zur vollständigen Menüsteuerung"),
         ("Schaltungsprinzip", "Taktile Drucktaster schalten direkt gegen Masse (GND)"),
         ("Pinbelegung", "Angeschlossen an GPIO 12, 13, 14 und 27 (interner Pull-Up)"),
         ("Vorteil", "Taktiles Klick-Feedback, sofortige Reaktion ohne Touch-Latenz"),
     ]),
    ("LEITERPLATTE", "2-Lagen FR4", BLUE_50, BLUE_600,
     "Eigene Trägerplatine",
     [
         ("Lagenaufbau", "2 Kupferlagen mit optimierter Signalführung & Massefläche"),
         ("Abmessungen", "Kompakte Bauhöhe von ca. 63 mm (2473 mil)"),
         ("Mechanik", "Passgenaue Buchsenleisten für ESP32, Display und Taster"),
         ("Signalqualität", "Kurze Leiterbahnlängen am SPI-Bus zur Vermeidung von Störungen"),
     ]),
]

cw, ch = 5.7, 2.48
for i, (tag, badge, bcol, tcol, title_c, bullets) in enumerate(comp_cards):
    x = ML + (i % 2) * (cw + 0.43)
    y = 1.72 + (i // 2) * (ch + 0.22)
    card(s, x, y, cw, ch)
    pill(s, tag, x + 0.3, y + 0.2, 1.8, 0.24, bg=bcol, txt_color=tcol, size=9.5, font=F_HEAD)
    pill(s, badge, x + cw - 0.3 - 1.9, y + 0.2, 1.9, 0.24, bg=CANVAS, txt_color=INK_700, size=9.5, font=F_HEAD)
    text(s, title_c, x + 0.3, y + 0.5, cw - 0.6, 0.32, size=17, font=F_HEAD)
    hline(s, x + 0.3, y + 0.86, cw - 0.6)

    tb = s.shapes.add_textbox(Inches(x + 0.3), Inches(y + 0.95), Inches(cw - 0.6), Inches(1.35))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for idx, (bhead, btext) in enumerate(bullets):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.space_after = Pt(2.5)
        p.line_spacing = 1.15
        r_bullet = p.add_run(); r_bullet.text = "•  "
        r_bullet.font.size = Pt(10.5); r_bullet.font.color.rgb = BLUE_600; r_bullet.font.name = F_HEAD
        r1 = p.add_run(); r1.text = bhead + ": "
        r1.font.size = Pt(10.5); r1.font.color.rgb = INK_900; r1.font.name = F_HEAD
        r2 = p.add_run(); r2.text = btext
        r2.font.size = Pt(10.5); r2.font.color.rgb = INK_700; r2.font.name = F_BODY

notes(s, "Die Hardware besteht aus vier Teilen: Der ESP32 liefert die nötige Rechenleistung "
         "mit 240 MHz und WLAN. Das 2-Zoll-Display wird über schnelles SPI angesteuert. "
         "Vier Taster ermöglichen die Menüsteuerung und die eigene Platine verbindet alles "
         "kompakt und stabil.")


# =====================================================================
# FOLIE 3 – SCHALTPLAN & PINBELEGUNG
# =====================================================================
s = base_slide(3, "Elektronik", "Schaltplan & Pinbelegung",
               "Elektrische Verschaltung der Komponenten mit den GPIO-Pins des ESP32.")

# Links: Schaltplan
cad_window(s, ML, 1.72, 6.7, 5.08, "SCHALTPLAN · ENTWURF IN EASYEDA")
rect(s, ML + 0.15, 2.15, 6.4, 4.5, WHITE, MSO_SHAPE.RECTANGLE, line=CAD_BORDER)
picture_fit(s, os.path.join(IMG, "schaltplan.png"), ML + 0.22, 2.22, 6.26, 4.36)

# Rechts: Pinbelegung
rx, rw = 7.75, 4.83
card(s, rx, 1.72, rw, 5.08)

# Display-Tabelle
pill(s, "DISPLAY-SCHNITTSTELLE (SPI)", rx + 0.3, 1.9, 2.2, 0.24, bg=BLUE_50, txt_color=BLUE_600, size=9.5, font=F_HEAD)
text(s, "ST7789 Display-Anbindung", rx + 0.3, 2.18, rw - 0.6, 0.26, size=15, font=F_HEAD)
hline(s, rx + 0.3, 2.48, rw - 0.6)

disp_rows = [
    ("SDA / MOSI", "GPIO 23", "Datenleitung (Hardware-SPI)"),
    ("SCL / SCK", "GPIO 18", "Taktsignal (Hardware-SPI)"),
    ("DC", "GPIO 2", "Daten / Befehl Steuerung"),
    ("RES", "GPIO 4", "Hardware-Reset Signal"),
    ("BLK", "GPIO 5", "Hintergrundbeleuchtung (PWM)"),
    ("VCC / GND", "3,3 V / GND", "Spannungsversorgung"),
]
yy = 2.58
for pin, gpio, desc in disp_rows:
    text(s, pin, rx + 0.3, yy, 1.25, 0.2, size=11, color=INK_900, font=F_HEAD)
    pill(s, gpio, rx + 1.6, yy - 0.02, 0.95, 0.22, bg=CANVAS, txt_color=BLUE_600, size=10, font=F_HEAD)
    text(s, desc, rx + 2.65, yy, rw - 2.85, 0.2, size=10.5, color=INK_500, font=F_BODY)
    yy += 0.25

# Taster-Tabelle
hline(s, rx + 0.3, yy + 0.06, rw - 0.6)
pill(s, "TASTER-EINGÄNGE", rx + 0.3, yy + 0.16, 1.8, 0.24, bg=TEAL_50, txt_color=TEAL_600, size=9.5, font=F_HEAD)
text(s, "Tastenbelegung (GPIO)", rx + 0.3, yy + 0.43, rw - 0.6, 0.26, size=15, font=F_HEAD)
hline(s, rx + 0.3, yy + 0.72, rw - 0.6)

btn_rows = [
    ("UP", "GPIO 12", "Menü aufwärts"),
    ("DOWN", "GPIO 13", "Menü abwärts"),
    ("SELECT", "GPIO 14", "Bestätigen / Auswählen"),
    ("BACK", "GPIO 27", "Zurück / Abbrechen"),
]
by = yy + 0.8
for name, gpio, desc in btn_rows:
    text(s, name, rx + 0.3, by, 1.25, 0.2, size=11, color=INK_900, font=F_HEAD)
    pill(s, gpio, rx + 1.6, by - 0.02, 0.95, 0.22, bg=CANVAS, txt_color=TEAL_600, size=10, font=F_HEAD)
    text(s, desc, rx + 2.65, by, rw - 2.85, 0.2, size=10.5, color=INK_500, font=F_BODY)
    by += 0.24

# Hinweis
note_box = rect(s, rx + 0.3, 6.25, rw - 0.6, 0.42, BLUE_50, MSO_SHAPE.ROUNDED_RECTANGLE,
                line=RGBColor(0xBF, 0xDB, 0xFE), radius=0.2)
text(s, "Hinweis: Native VSPI-Pins ermöglichen Übertragungsraten von bis zu 80 MHz ohne CPU-Last.",
     rx + 0.42, 6.29, rw - 0.84, 0.34, size=9.5, color=BLUE_600, font=F_BODY)

notes(s, "Hier sehen wir den Schaltplan: Das Display nutzt die nativen VSPI-Pins des ESP32 – "
         "GPIO 23 für Daten und GPIO 18 für den Takt. Die vier Taster sind an GPIO 12, 13, 14 "
         "und 27 angeschlossen und schalten direkt gegen Masse.")


# =====================================================================
# FOLIE 4 – PLATINENENTWICKLUNG
# =====================================================================
s = base_slide(4, "Platinenentwicklung", "Vom Layout zur fertigen Platine",
               "Schrittweiser Entwurf vom Leiterbahn-Routing bis zur räumlichen Kontrolle.")

cad_steps = [
    ("SCHRITT 1", "EDA-Layout & Routing",
     "pcb_layout.png",
     "Top-Layer (rot) und Bottom-Layer (blau) mit 45°-Winkeln geroutet. Signalwege kurz gehalten."),
    ("SCHRITT 2", "2D-Bohrungsprüfung",
     "pcb_2d.png",
     "Prüfung aller Bohrungen, Lötflächen (Pads) und Abstände zur Platinenkante."),
    ("SCHRITT 3", "3D-Modellabgleich",
     "pcb_3d_hinten.png",
     "Räumliche Kontrolle der Bestückung, Sockelhöhe und Gehäuse-Passgenauigkeit."),
]

cw_step = 3.7
gap = 0.36
for i, (phase, title_step, img_file, desc) in enumerate(cad_steps):
    x = ML + i * (cw_step + gap)
    cad_window(s, x, 1.72, cw_step, 3.92, f"{phase} · VERIFIKATION")
    img_path = os.path.join(IMG, img_file) if img_file != "pcb_2d.png" else PCB_2D
    picture_fit(s, img_path, x + 0.15, 2.18, cw_step - 0.3, 2.45)

    rect(s, x, 4.7, cw_step, 0.94, RGBColor(0x07, 0x0D, 0x1C), MSO_SHAPE.RECTANGLE)
    text(s, title_step, x + 0.2, 4.76, cw_step - 0.4, 0.24, size=13, font=F_HEAD, color=WHITE)
    text(s, desc, x + 0.2, 5.02, cw_step - 0.4, 0.54, size=10, color=INK_400, font=F_BODY, spacing=1.12)

# KPI-Streifen
kpi_card = card(s, ML, 5.85, SW - 2 * ML, 0.95)
kpis = [
    ("2 Lagen", "Kupferebenen (Top & Bottom FR4)"),
    ("≈ 63 mm", "Bauhöhe Platine (2473 mil)"),
    ("30 Pins", "Headeraufnahme ESP32 DevKit"),
    ("100 %", "Routen-Vollständigkeit ohne Brücken"),
]
kw = (SW - 2 * ML) / 4
for i, (val, label) in enumerate(kpis):
    kx = ML + i * kw
    if i > 0:
        rect(s, kx, 6.0, 0.012, 0.65, CARD_BORDER)
    text(s, val, kx + 0.25, 5.95, kw - 0.5, 0.35, size=22, font=F_HEAD, color=BLUE_600)
    text(s, label, kx + 0.25, 6.32, kw - 0.5, 0.35, size=11, font=F_BODY, color=INK_500)

notes(s, "Der Entwurfsprozess: Zuerst das Routing auf zwei Kupferlagen. Danach die 2D-Prüfung "
         "aller Pads und Bohrungen und schließlich der 3D-Modellabgleich. Die Platine ist "
         "ca. 63 mm hoch und vollständig ohne Brücken geroutet.")


# =====================================================================
# FOLIE 5 – FAZIT & AUSBLICK
# =====================================================================
s = base_slide(5, "Fazit & Ausblick", "Ergebnisse & Nächste Schritte",
               "Zusammenfassung der Erkenntnisse und geplanter weiterer Projektverlauf.")

fcw = 5.7
# Linke Karte: Gelernt
c1 = card(s, ML, 1.72, fcw, 4.12)
pill(s, "LERNERFOLGE", ML + 0.3, 1.92, 1.8, 0.26, bg=TEAL_50, txt_color=TEAL_600, size=9.5, font=F_HEAD)
text(s, "Was im Projekt gelernt wurde", ML + 0.3, 2.22, fcw - 0.6, 0.32, size=17, font=F_HEAD)
hline(s, ML + 0.3, 2.6, fcw - 0.6)

milestones = [
    ("Schaltungsentwurf & Dimensionierung",
     "Sinnvolle Pin-Aufteilung am ESP32, Vermeidung von Strapping-Pin-Konflikten und sichere 3,3-V-Versorgung."),
    ("Leiterplatten-Layout auf 2 Lagen",
     "Kreuzungsfreies Verlegen von Leiterbahnen, Setzen von Durchkontaktierungen und Einhalten von Abständen."),
    ("Schnelle SPI-Displayanbindung",
     "Verständnis des ST7789-Protokolls und der Hardware-SPI-Architektur für flüssige Grafikausgabe."),
    ("Taster-Abfrage & Eingabekonzept",
     "Sichere Auswertung von vier Bedientasten mit internen Pull-Up-Widerständen gegen Masse."),
]
my = 2.72
for mhead, mdesc in milestones:
    rect(s, ML + 0.3, my + 0.04, 0.22, 0.22, TEAL_50, MSO_SHAPE.OVAL, line=TEAL_600, line_w=1)
    text(s, "✓", ML + 0.3, my + 0.03, 0.22, 0.22, size=10, color=TEAL_600, font=F_HEAD,
         align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    tb = s.shapes.add_textbox(Inches(ML + 0.62), Inches(my), Inches(fcw - 0.95), Inches(0.65))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p1 = tf.paragraphs[0]; p1.line_spacing = 1.15
    r1 = p1.add_run(); r1.text = mhead + "\n"; r1.font.size = Pt(11.5); r1.font.color.rgb = INK_900; r1.font.name = F_HEAD
    r2 = p1.add_run(); r2.text = mdesc; r2.font.size = Pt(10.5); r2.font.color.rgb = INK_700; r2.font.name = F_BODY
    my += 0.73

# Rechte Karte: Roadmap
c2 = card(s, ML + fcw + 0.43, 1.72, fcw, 4.12)
pill(s, "FAHRPLAN", ML + fcw + 0.73, 1.92, 1.4, 0.26, bg=BLUE_50, txt_color=BLUE_600, size=9.5, font=F_HEAD)
text(s, "Nächste Projektschritte", ML + fcw + 0.73, 2.22, fcw - 0.6, 0.32, size=17, font=F_HEAD)
hline(s, ML + fcw + 0.73, 2.6, fcw - 0.6)

roadmap = [
    ("01", "Platinenfertigung & Bestückung",
     "Gerber-Dateien fertigen lassen (z. B. JLCPCB), Bauteile auflöten und Durchgangsprüfung durchführen."),
    ("02", "Firmware- & Menü-Entwicklung",
     "Programmierung in C++ mit TFT_eSPI oder LVGL: Menüführung, Dashboard, kleine Spiele und Statusanzeigen."),
    ("03", "Mobiler Akkubetrieb",
     "Einbau eines 3,7-V-LiPo-Akkus mit TP4056-Lademodul und Deep-Sleep-Modus für lange Laufzeit."),
    ("04", "Gehäusekonstruktion im 3D-Druck",
     "CAD-Konstruktion eines passgenauen Gehäuses mit ergonomischen Tasten für den mobilen Einsatz."),
]
ry = 2.72
for num, rhead, rdesc in roadmap:
    pill(s, num, ML + fcw + 0.73, ry + 0.04, 0.46, 0.26, bg=BLUE_50, txt_color=BLUE_600, size=10.5, font=F_HEAD)
    tb = s.shapes.add_textbox(Inches(ML + fcw + 1.3), Inches(ry), Inches(fcw - 1.6), Inches(0.65))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p1 = tf.paragraphs[0]; p1.line_spacing = 1.15
    r1 = p1.add_run(); r1.text = rhead + "\n"; r1.font.size = Pt(11.5); r1.font.color.rgb = INK_900; r1.font.name = F_HEAD
    r2 = p1.add_run(); r2.text = rdesc; r2.font.size = Pt(10.5); r2.font.color.rgb = INK_700; r2.font.name = F_BODY
    ry += 0.73

# Abschluss-Banner
banner = card(s, ML, 6.02, SW - 2 * ML, 0.82, bg=WHITE, border=BLUE_600)
rect(s, ML, 6.02, 0.08, 0.82, BLUE_600)
pill(s, "STATUS: BEREIT ZUR FERTIGUNG", ML + 0.3, 6.15, 2.5, 0.24, bg=TEAL_50, txt_color=TEAL_600, size=9.5, font=F_HEAD)
text(s, "Vielen Dank für Ihre Aufmerksamkeit!", ML + 0.3, 6.45, 5.5, 0.3, size=17, font=F_HEAD, color=INK_900)
text(s, "Gibt es Fragen zum Hardware-Design oder zur Firmware?",
     SW - ML - 5.8, 6.3, 5.5, 0.35, size=13.5, font=F_HEAD, color=BLUE_600, align=PP_ALIGN.RIGHT)

notes(s, "Zum Abschluss: Der Hardware-Entwurf ist abgeschlossen und bereit zur Fertigung. "
         "Als nächste Schritte folgen die Platinenbestellung, Bestückung, die Firmware-Entwicklung "
         "und das 3D-Druck-Gehäuse. Vielen Dank! Gibt es Fragen?")

# Im Projektordner speichern
out_local = os.path.join(BASE, "ESP32_Projekt_Praesentation.pptx")
prs.save(out_local)
print("Gespeichert (lokal):", out_local)

# Im Downloads-Ordner des Nutzers speichern
user_home = os.path.expanduser("~")
downloads_dir = os.path.join(user_home, "Downloads")
if os.path.exists(downloads_dir):
    out_downloads = os.path.join(downloads_dir, "ESP32_Projekt_Praesentation.pptx")
    shutil.copy2(out_local, out_downloads)
    print("Kopiert nach Downloads:", out_downloads)
