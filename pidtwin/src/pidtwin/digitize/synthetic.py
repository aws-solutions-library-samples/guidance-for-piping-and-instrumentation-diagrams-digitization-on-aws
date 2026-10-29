"""Generate a synthetic P&ID image with known ground truth for scoring."""
import json
from PIL import Image, ImageDraw, ImageFont

W, H = 2200, 1300
img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)


def font(size):
    for path in ["/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


F, FS, FL = font(20), font(16), font(26)
K = "black"


def text_c(x, y, s, f=F):
    b = d.textbbox((0, 0), s, font=f)
    d.text((x - (b[2] - b[0]) / 2, y - (b[3] - b[1]) / 2), s, fill=K, font=f)


def line(pts, dashed=False, w=3):
    if not dashed:
        d.line(pts, fill=K, width=w)
        return
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        n = int(max(abs(x2 - x1), abs(y2 - y1)) / 12)
        for i in range(0, n, 2):
            a, b = i / n, min((i + 1) / n, 1)
            d.line([(x1 + (x2 - x1) * a, y1 + (y2 - y1) * a), (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b)], fill=K, width=2)


def arrow(x, y, direction="right"):
    s = 12
    pts = {"right": [(x, y), (x - s, y - s / 2), (x - s, y + s / 2)],
           "down": [(x, y), (x - s / 2, y - s), (x + s / 2, y - s)],
           "up": [(x, y), (x - s / 2, y + s), (x + s / 2, y + s)]}[direction]
    d.polygon(pts, fill=K)


def gate_valve(x, y, tag=None):
    d.polygon([(x - 18, y - 12), (x - 18, y + 12), (x, y)], outline=K, width=2, fill="white")
    d.polygon([(x + 18, y - 12), (x + 18, y + 12), (x, y)], outline=K, width=2, fill="white")
    if tag:
        text_c(x, y + 30, tag, FS)


def check_valve(x, y, tag=None):
    d.rectangle([x - 18, y - 12, x + 18, y + 12], outline=K, width=2, fill="white")
    d.line([(x - 18, y + 12), (x + 18, y - 12)], fill=K, width=2)
    d.polygon([(x + 4, y - 12), (x + 18, y - 12), (x + 18, y)], fill=K)
    if tag:
        text_c(x, y + 30, tag, FS)


def control_valve(x, y, tag):
    gate_valve(x, y)
    d.line([(x, y), (x, y - 35)], fill=K, width=2)
    d.chord([x - 18, y - 53, x + 18, y - 17], 180, 360, outline=K, width=2, fill="white")
    d.line([(x - 18, y - 35), (x + 18, y - 35)], fill=K, width=2)
    text_c(x + 55, y - 40, tag, FS)


def instrument(x, y, tag, shared=False):
    r = 34
    d.ellipse([x - r, y - r, x + r, y + r], outline=K, width=2, fill="white")
    if shared:
        d.line([(x - r, y), (x + r, y)], fill=K, width=2)
    letters, num = tag.split("-")
    text_c(x, y - 12 if shared or True else y, letters, FS)
    text_c(x, y + 12, num, FS)


def pump(x, y, tag):
    r = 40
    d.ellipse([x - r, y - r, x + r, y + r], outline=K, width=3, fill="white")
    d.line([(x, y - r), (x + r, y - r)], fill=K, width=3)
    d.polygon([(x - 30, y + 50), (x + 30, y + 50), (x, y + 25)], outline=K, width=2)
    text_c(x, y + 80, tag, F)


LABEL_BOXES = {}


def label_box(x, y, s):
    b = d.textbbox((0, 0), s, font=FS)
    tw = b[2] - b[0]
    d.rectangle([x - tw / 2 - 4, y - 12, x + tw / 2 + 4, y + 12], fill="white")
    text_c(x, y, s, FS)
    LABEL_BOXES[s] = [round(x - tw / 2), y - 10, round(x + tw / 2), y + 10]


# ---- Title block ----
d.rectangle([20, 20, W - 20, H - 20], outline=K, width=3)
d.rectangle([W - 620, H - 160, W - 20, H - 20], outline=K, width=2)
text_c(W - 320, H - 125, "PROCESS FEED SYSTEM", FL)
text_c(W - 320, H - 85, "DWG NO. PID-1001  REV B", F)
text_c(W - 320, H - 50, "UNIT 100", F)

PY = 700  # main process line elevation

# T-101 Feed Tank
d.rectangle([110, 380, 330, 800], outline=K, width=3)
d.arc([110, 340, 330, 420], 180, 360, fill=K, width=3)
text_c(220, 600, "T-101", FL)
text_c(220, 635, "FEED TANK", FS)
line([(330, PY), (430, PY)])
gate_valve(430, PY, "HV-101")
line([(448, PY), (560, PY)])
label_box(500, PY - 25, '4"-P-1001-CS')
line([(560, PY), (560, PY + 40), (580, PY + 40)])
pump(620, PY + 40, "P-101")
# discharge
line([(620, PY), (620, 520), (760, 520)])
label_box(680, 495, '3"-P-1002-CS')
check_valve(778, 520, "CV-101")
line([(796, 520), (1060, 520)])
gate_valve(1078, 520)
control_valve(1078, 520, "FCV-101")
line([(1096, 520), (1300, 520)])
arrow(1300, 520)

# E-101 heat exchanger
d.ellipse([1300, 470, 1420, 570], outline=K, width=3)
d.line([(1320, 545), (1340, 495), (1360, 545), (1380, 495), (1400, 545)], fill=K, width=2)
text_c(1460, 590, "E-101", F)
line([(1360, 470), (1360, 400)]); text_c(1360, 380, "STEAM", FS); arrow(1360, 470, "down")
line([(1360, 570), (1360, 640)]); text_c(1360, 665, "CONDENSATE", FS)

line([(1420, 520), (1700, 520)])
label_box(1560, 495, '3"-P-1003-SS')
arrow(1700, 520)

# V-101 vessel
d.rounded_rectangle([1700, 320, 1880, 880], radius=80, outline=K, width=3)
text_c(1790, 600, "V-101", FL)
text_c(1790, 635, "SURGE DRUM", FS)
line([(1790, 880), (1790, 1000), (1960, 1000)])
label_box(1870, 975, '2"-P-1004-SS')
arrow(1960, 1000)
text_c(2030, 1000, "TO UNIT 200", FS)
# PSV on top
line([(1790, 320), (1790, 260)])
d.polygon([(1772, 260), (1808, 260), (1790, 230)], outline=K, width=2)
d.rectangle([1775, 210, 1805, 230], outline=K, width=2)
text_c(1860, 240, "PSV-101", FS)
text_c(1860, 265, "SET 150 PSIG", FS)

# ---- Instruments ----
# LT-101 on tank, LIC-101 in control room
line([(330, 480), (400, 480)]); instrument(434, 480, "LT-101")
line([(434, 446), (434, 404)], dashed=True); instrument(434, 370, "LIC-101", shared=True)
# PI-101 on pump discharge
line([(620, 520), (620, 420)]); instrument(620, 386, "PI-101")
# FT-101 on discharge, FIC-101 -> FCV-101
line([(920, 520), (920, 440)]); instrument(920, 406, "FT-101")
line([(954, 406), (1000, 406)], dashed=True); instrument(1034, 330, "FIC-101", shared=True)
line([(1000, 406), (1000, 330)], dashed=True)
line([(1068, 330), (1078, 330), (1078, 467)], dashed=True)
# TT-101 / TIC-101 after exchanger
line([(1500, 520), (1500, 440)]); instrument(1500, 406, "TT-101")
line([(1534, 406), (1580, 406)], dashed=True); instrument(1614, 406, "TIC-101", shared=True)
# PT-101 on V-101
line([(1700, 380), (1665, 380), (1665, 260)]); instrument(1665, 226, "PT-101")
# LG-101 on V-101
line([(1880, 450), (1950, 450)]); instrument(1984, 450, "LG-101")

img.save("samples/synthetic_pid_1001.png")

# symbol-graphic bounding boxes in pixels (tag text excluded)
ib = lambda x, y, r=34: [x - r, y - r, x + r, y + r]
boxes = {
    "T-101": [110, 340, 330, 800], "P-101": [580, 700, 660, 790], "E-101": [1300, 470, 1420, 570],
    "V-101": [1700, 320, 1880, 880],
    "HV-101": [412, 688, 448, 712], "CV-101": [760, 508, 796, 532], "FCV-101": [1060, 467, 1096, 532],
    "PSV-101": [1772, 210, 1808, 260],
    "LT-101": ib(434, 480), "LIC-101": ib(434, 370), "PI-101": ib(620, 386), "FT-101": ib(920, 406),
    "FIC-101": ib(1034, 330), "TT-101": ib(1500, 406), "TIC-101": ib(1614, 406), "PT-101": ib(1665, 226),
    "LG-101": ib(1984, 450),
    **LABEL_BOXES,
}

truth = {
    "image": "samples/synthetic_pid_1001.png",
    "image_size": [W, H],
    "boxes": boxes,
    "equipment": ["T-101", "P-101", "E-101", "V-101"],
    "valves": ["HV-101", "CV-101", "FCV-101", "PSV-101"],
    "instruments": ["LT-101", "LIC-101", "PI-101", "FT-101", "FIC-101", "TT-101", "TIC-101", "PT-101", "LG-101"],
    "lines": ['4"-P-1001-CS', '3"-P-1002-CS', '3"-P-1003-SS', '2"-P-1004-SS'],
    "connections": [
        ["T-101", "HV-101"], ["HV-101", "P-101"], ["P-101", "CV-101"], ["CV-101", "FCV-101"],
        ["FCV-101", "E-101"], ["E-101", "V-101"], ["PSV-101", "V-101"],
        ["LT-101", "T-101"], ["PI-101", "P-101"], ["LT-101", "LIC-101"], ["FT-101", "FIC-101"], ["FIC-101", "FCV-101"],
        ["TT-101", "TIC-101"], ["PT-101", "V-101"], ["LG-101", "V-101"],
        ["FT-101", "CV-101"], ["TT-101", "E-101"],  # inline taps on the pipe between those items
        ["STEAM", "E-101"], ["E-101", "CONDENSATE"], ["V-101", "TO UNIT 200"],
    ],
    "offpage": [{"label": k, "bbox": [round(v[0] / W * 1000), round(v[1] / H * 1000), round(v[2] / W * 1000),
                                      round(v[3] / H * 1000)]}
                for k, v in {"STEAM": [1330, 372, 1390, 388], "CONDENSATE": [1310, 657, 1410, 673],
                             "TO UNIT 200": [1985, 992, 2075, 1008]}.items()],
}
json.dump(truth, open("samples/synthetic_pid_1001.truth.json", "w"), indent=2)
print("wrote samples/synthetic_pid_1001.png + .truth.json")
