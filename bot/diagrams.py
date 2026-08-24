"""Vector Diagram Engine for Cheatsheet and MCQ Handbooks.

Generates native ReportLab vector Drawing objects for:
- Circular Seating Arrangements (Inward/Outward/Mixed facing)
- Linear Row Arrangements (North/South facing with direction boundaries)
- Square / Rectangular Table Arrangements
- Geometric Shapes (Right triangles, circles, polygons)
- Venn Diagrams (2-set and 3-set)
"""
from __future__ import annotations

import json
import math
import re
from typing import Optional, Any
import yaml

from reportlab.graphics.shapes import (
    Drawing, Circle, Rect, Line, String, Group, Polygon
)
from reportlab.lib import colors


def parse_diagram_spec(code_content: str) -> dict[str, Any]:
    """Parse YAML or JSON diagram spec safely."""
    try:
        data = yaml.safe_load(code_content)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    try:
        data = json.loads(code_content)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    res = {}
    for line in code_content.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            res[k.strip().lower()] = v.strip()
    return res


def make_circular_seating_diagram(spec: dict[str, Any], width: float = 380, height: float = 210) -> Drawing:
    """Generate a vector circular seating arrangement drawing."""
    d = Drawing(width, height)
    cx, cy = width / 2.0, height / 2.0
    r_table = 44.0
    r_seats = 76.0
    
    occupants = spec.get("occupants", [])
    if isinstance(occupants, dict):
        occupants = [occupants.get(i, occupants.get(str(i), "-")) for i in range(1, len(occupants) + 1)]
    if not occupants:
        seats_cnt = int(spec.get("seats", 8))
        occupants = [f"P{i}" for i in range(1, seats_cnt + 1)]
        
    facing = str(spec.get("facing", "inward")).lower()
    title = str(spec.get("title", "")).strip()

    # Table background & border
    d.add(Circle(cx, cy, r_table, fillColor=colors.HexColor("#EFF6FF"), strokeColor=colors.HexColor("#3B82F6"), strokeWidth=2))
    d.add(String(cx - 24, cy + 2, "TABLE", fontName="Helvetica-Bold", fontSize=10, fillColor=colors.HexColor("#1E40AF")))
    facing_label = "Facing In" if facing == "inward" else ("Facing Out" if facing == "outward" else facing.title())
    d.add(String(cx - (len(facing_label)*2.5), cy - 10, f"({facing_label})", fontName="Helvetica", fontSize=7.5, fillColor=colors.HexColor("#64748B")))

    if title:
        d.add(String(10, height - 14, title, fontName="Helvetica-Bold", fontSize=9, fillColor=colors.HexColor("#1E3A8A")))

    n = len(occupants)
    for i, name in enumerate(occupants):
        angle = math.pi / 2 - (2 * math.pi * i / n)
        sx = cx + r_seats * math.cos(angle)
        sy = cy + r_seats * math.sin(angle)
        
        # Radial connector
        tx = cx + r_table * math.cos(angle)
        ty = cy + r_table * math.sin(angle)
        d.add(Line(tx, ty, sx, sy, strokeColor=colors.HexColor("#CBD5E1"), strokeWidth=1, strokeDashArray=[2, 2]))
        
        # Seat bubble
        name_str = str(name).strip()
        is_empty = name_str in ("-", "", "None")
        seat_color = colors.HexColor("#FFFFFF") if not is_empty else colors.HexColor("#F8FAFC")
        border_color = colors.HexColor("#1E3A8A") if not is_empty else colors.HexColor("#94A3B8")
        
        d.add(Circle(sx, sy, 13, fillColor=seat_color, strokeColor=border_color, strokeWidth=1.5))
        
        # Occupant text
        display_name = name_str if not is_empty else "?"
        offset_x = 3.5 if len(display_name) == 1 else (7 if len(display_name) == 2 else 10)
        d.add(String(sx - offset_x, sy - 3.5, display_name, fontName="Helvetica-Bold", fontSize=8.5, fillColor=colors.HexColor("#0F172A")))
        
        # Seat position index
        idx_label = f"S{i+1}"
        tag_y = sy + 15 if sy >= cy else sy - 21
        d.add(String(sx - 5, tag_y, idx_label, fontName="Helvetica", fontSize=7, fillColor=colors.HexColor("#64748B")))

    return d


def make_linear_row_diagram(spec: dict[str, Any], width: float = 460, height: float = 75) -> Drawing:
    """Generate a vector linear row arrangement drawing."""
    d = Drawing(width, height)
    slots = spec.get("slots", spec.get("occupants", []))
    if isinstance(slots, dict):
        slots = [slots.get(i, slots.get(str(i), "-")) for i in range(1, len(slots) + 1)]
    if not slots:
        length = int(spec.get("length", spec.get("seats", 7)))
        slots = ["-"] * length

    facing = str(spec.get("facing", "North")).title()
    title = str(spec.get("title", f"Row Facing {facing}"))

    n = len(slots)
    box_w = min(44.0, (width - 80) / max(n, 1))
    box_h = 30.0
    spacing = 8.0
    total_w = n * box_w + (n - 1) * spacing
    start_x = (width - total_w) / 2.0
    y = 22.0
    
    # Orientation Header
    d.add(String(start_x, y + 36, title, fontName="Helvetica-Bold", fontSize=8.5, fillColor=colors.HexColor("#1E40AF")))
    d.add(String(start_x - 30, y + 9, "LEFT", fontName="Helvetica-Bold", fontSize=8, fillColor=colors.HexColor("#DC2626")))
    d.add(String(start_x + total_w + 8, y + 9, "RIGHT", fontName="Helvetica-Bold", fontSize=8, fillColor=colors.HexColor("#16A34A")))

    for i, name in enumerate(slots):
        bx = start_x + i * (box_w + spacing)
        name_str = str(name).strip() if name else "-"
        is_empty = name_str in ("-", "", "None")
        
        # Seat Box
        bg_col = colors.HexColor("#EFF6FF") if not is_empty else colors.HexColor("#F8FAFC")
        border_col = colors.HexColor("#2563EB") if not is_empty else colors.HexColor("#CBD5E1")
        d.add(Rect(bx, y, box_w, box_h, rx=3, ry=3, fillColor=bg_col, strokeColor=border_col, strokeWidth=1.2))
        
        # Occupant Name
        display_name = name_str if not is_empty else "-"
        if " (" in display_name and len(display_name) > 4:
            display_name = re.sub(r"\s*\([^\)]+\)", "", display_name)
        f_size = 9.5 if len(display_name) <= 2 else 8.0
        offset_x = len(display_name) * (f_size * 0.28)
        d.add(String(bx + box_w/2 - offset_x, y + 10, display_name, fontName="Helvetica-Bold", fontSize=f_size, fillColor=colors.HexColor("#0F172A")))
        
        # Position Index
        d.add(String(bx + box_w/2 - 3, y - 10, str(i+1), fontName="Helvetica", fontSize=7.5, fillColor=colors.HexColor("#64748B")))

    return d


def make_geometry_triangle(spec: dict[str, Any], width: float = 280, height: float = 140) -> Drawing:
    """Generate a vector right-angle or general triangle diagram."""
    d = Drawing(width, height)
    ox, oy = 50.0, 20.0
    w, h = 140.0, 95.0
    
    vertices = spec.get("vertices", ["A", "B", "C"])
    base_lbl = str(spec.get("base", "Base (b)"))
    height_lbl = str(spec.get("height", "Height (h)"))
    hyp_lbl = str(spec.get("hypotenuse", spec.get("hyp", "Hypotenuse (c)")))

    # Triangle Polygon
    d.add(Polygon([ox, oy, ox + w, oy, ox, oy + h], fillColor=colors.HexColor("#F0FDF4"), strokeColor=colors.HexColor("#16A34A"), strokeWidth=2))
    # Right angle marker
    d.add(Rect(ox, oy, 12, 12, fillColor=None, strokeColor=colors.HexColor("#16A34A"), strokeWidth=1))
    
    # Vertices
    vA = vertices[0] if len(vertices) > 0 else "A"
    vB = vertices[1] if len(vertices) > 1 else "B"
    vC = vertices[2] if len(vertices) > 2 else "C"
    d.add(String(ox - 14, oy - 2, vB, fontName="Helvetica-Bold", fontSize=10, fillColor=colors.HexColor("#0F172A")))
    d.add(String(ox + w + 4, oy - 2, vC, fontName="Helvetica-Bold", fontSize=10, fillColor=colors.HexColor("#0F172A")))
    d.add(String(ox - 14, oy + h, vA, fontName="Helvetica-Bold", fontSize=10, fillColor=colors.HexColor("#0F172A")))
    
    # Labels
    d.add(String(ox + w/2 - 16, oy - 14, base_lbl, fontName="Helvetica", fontSize=8, fillColor=colors.HexColor("#1E3A8A")))
    d.add(String(ox - 42, oy + h/2 - 4, height_lbl, fontName="Helvetica", fontSize=8, fillColor=colors.HexColor("#1E3A8A")))
    d.add(String(ox + w/2 + 6, oy + h/2 + 6, hyp_lbl, fontName="Helvetica-Bold", fontSize=8, fillColor=colors.HexColor("#15803D")))

    return d


def make_venn_diagram(spec: dict[str, Any], width: float = 340, height: float = 140) -> Drawing:
    """Generate a vector 2-set Venn Diagram."""
    d = Drawing(width, height)
    cx1, cy = width / 2.0 - 35.0, height / 2.0
    cx2 = width / 2.0 + 35.0
    r = 50.0

    sets = spec.get("sets", ["Set A", "Set B"])
    setA_name = sets[0] if len(sets) > 0 else "A"
    setB_name = sets[1] if len(sets) > 1 else "B"
    
    labels = spec.get("labels", {})
    valA = str(labels.get("A", labels.get("only_A", "")))
    valB = str(labels.get("B", labels.get("only_B", "")))
    valAB = str(labels.get("intersection", labels.get("both", "")))

    # Circle A
    d.add(Circle(cx1, cy, r, fillColor=colors.HexColor("#EFF6FF"), strokeColor=colors.HexColor("#2563EB"), strokeWidth=1.5))
    # Circle B
    d.add(Circle(cx2, cy, r, fillColor=colors.HexColor("#FEF2F2"), strokeColor=colors.HexColor("#DC2626"), strokeWidth=1.5))

    # Set Headings
    d.add(String(cx1 - 30, cy + r + 8, setA_name, fontName="Helvetica-Bold", fontSize=9, fillColor=colors.HexColor("#1E40AF")))
    d.add(String(cx2 + 5, cy + r + 8, setB_name, fontName="Helvetica-Bold", fontSize=9, fillColor=colors.HexColor("#991B1B")))

    # Values inside regions
    if valA:
        d.add(String(cx1 - 20, cy - 4, valA, fontName="Helvetica-Bold", fontSize=9, fillColor=colors.HexColor("#1E40AF")))
    if valB:
        d.add(String(cx2 + 10, cy - 4, valB, fontName="Helvetica-Bold", fontSize=9, fillColor=colors.HexColor("#991B1B")))
    if valAB:
        d.add(String(width / 2.0 - 6, cy - 4, valAB, fontName="Helvetica-Bold", fontSize=9, fillColor=colors.HexColor("#0F172A")))

    return d


def render_diagram_flowable(kind: str, spec_text: str) -> Optional[Drawing]:
    """Parse spec and return appropriate ReportLab Drawing flowable."""
    spec = parse_diagram_spec(spec_text)
    kind_clean = kind.lower().strip()
    
    if "circular" in kind_clean or kind_clean in ("arrangement:circular", "diagram:circular"):
        return make_circular_seating_diagram(spec)
    elif "linear" in kind_clean or "row" in kind_clean or kind_clean in ("arrangement:linear", "diagram:linear"):
        return make_linear_row_diagram(spec)
    elif "triangle" in kind_clean or "geometry" in kind_clean or kind_clean in ("diagram:triangle", "diagram:geometry"):
        return make_geometry_triangle(spec)
    elif "venn" in kind_clean or kind_clean in ("diagram:venn", "diagram:set"):
        return make_venn_diagram(spec)
    return None
