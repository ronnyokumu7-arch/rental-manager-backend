# app/services/markdown_lite.py
"""
✅ Markdown-lite → HTML converter for the contract PDF.
Mirrors src/lib/markdownLite.tsx exactly: numbered run-in leads, block
sub-headings, run-in leads, and bullet/numbered lists — all rendered with a
flex hanging-indent row so wrapped detail aligns under the first letter of the
text, never under the marker. Inline styles (no classes) because the PDF
template has no stylesheet for these tokens.
"""
import html
import re

# Unified rhythm constants (parity with the React component).
M_PARA = "0 0 5px 0"
M_HEAD = "9px 0 4px 0"
M_LIST = "4px 0 6px 0"
M_ITEM = "0 0 4px 0"

# Theme constants.
INK = "#0f172a"
MUTED = "#475569"
ACCENT = "#B45309"

# Numbered run-in lead: number inside the bold label, e.g. **1. Provided Clean:** body
NUM_LEAD_BOLD = re.compile(r"^\*\*(\d+[.)])\s+([^*]+?:)\*\*\s+([\s\S]+)$")
# Numbered run-in lead: plain number then bold label, e.g. 1. **Provided Clean:** body
NUM_LEAD_PLAIN = re.compile(r"^(\d+[.)])\s+\*\*([^*]+?:)\*\*\s+([\s\S]+)$")
# Fully-bold line → block sub-heading.
FULL_HEAD_RE = re.compile(r"^\*\*([^*]+)\*\*$")
# Run-in lead: bold label ending in a colon, then body.
LEAD_RE = re.compile(r"^\*\*([^*]+?:)\*\*\s+([\s\S]+)$")


def _esc(s: str) -> str:
    return html.escape(s)


def render_inline(text: str) -> str:
    """Render **bold** inline markers into <strong>, escaping everything else."""
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    out = []
    for p in parts:
        if p.startswith("**") and p.endswith("**") and len(p) > 4:
            inner = _esc(p[2:-2])
            out.append(
                f'<strong style="color:{INK};font-weight:700;letter-spacing:0.01em;">'
                f"{inner}</strong>"
            )
        else:
            out.append(_esc(p))
    return "".join(out)


def _lead_label(text: str) -> str:
    return (
        f'<span style="color:{INK};font-weight:800;letter-spacing:0.015em;">'
        f"{_esc(text)}</span>"
    )


def render_rich(text: str) -> str:
    """Body for a list item / lead paragraph: promote a leading **Label:** to a lead."""
    m = LEAD_RE.match(text)
    if m:
        return f"{_lead_label(m.group(1))} {render_inline(m.group(2))}"
    return render_inline(text)


def _hang_row(marker: str, inner: str, bullet: bool = False, margin: str = M_ITEM) -> str:
    weight = "400" if bullet else "800"
    return (
        f'<div style="display:flex;gap:6px;margin:{margin};">'
        f'<span style="flex:0 0 auto;min-width:1.1em;font-weight:{weight};color:{INK};">'
        f"{_esc(marker)}</span>"
        f'<span style="flex:1 1 auto;line-height:1.5;">{inner}</span>'
        f"</div>"
    )


def markdown_to_html(text: str) -> str:
    """
    Lightweight markdown → HTML, matching MarkdownLitePreview(variant="contract").
    Supports: **bold**, - bullet lists, 1. numbered lists, \n paragraph breaks,
    numbered run-in leads (**1. Label:** body), run-in leads (**Label:** body),
    and fully-bold block sub-headings. All list/numbered rows use a flex
    hanging indent so wrapped detail aligns under the text, not the marker.
    """
    if not text or not text.strip():
        return ""

    lines = text.split("\n")
    blocks = []
    for line in lines:
        t = line.rstrip()
        bm = re.match(r"^[-*]\s+(.*)$", t)
        if bm:
            blocks.append(("bullet", bm.group(1)))
            continue
        nm = re.match(r"^\d+[.)]\s+(.*)$", t)
        if nm:
            blocks.append(("numbered", nm.group(1)))
            continue
        blocks.append(("paragraph", t))

    out = []
    cur = []
    curtype = None

    def flush():
        nonlocal cur, curtype
        if not cur:
            return
        rows = []
        for idx, (_, t) in enumerate(cur):
            marker = "•" if curtype == "bullet" else f"{idx + 1}."
            rows.append(_hang_row(marker, render_rich(t), bullet=(curtype == "bullet")))
        out.append(f'<div style="margin:{M_LIST};">{"".join(rows)}</div>')
        cur = []
        curtype = None

    for typ, t in blocks:
        if typ == "paragraph":
            flush()
            s = t.strip()
            if not s:
                continue

            nb = NUM_LEAD_BOLD.match(s)
            np = None if nb else NUM_LEAD_PLAIN.match(s)
            if nb or np:
                m = nb or np
                inner = f"{_lead_label(m.group(2))} {render_inline(m.group(3))}"
                out.append(_hang_row(m.group(1), inner, margin=M_PARA))
                continue

            fh = FULL_HEAD_RE.match(s)
            if fh:
                inner = render_inline(fh.group(1).rstrip(":"))
                out.append(
                    f'<p style="margin:{M_HEAD};padding-left:8px;'
                    f"border-left:2px solid {ACCENT};color:{INK};font-weight:800;"
                    f'font-size:9.5pt;letter-spacing:0.02em;line-height:1.4;">{inner}</p>'
                )
                continue

            ld = LEAD_RE.match(s)
            if ld:
                inner = f"{_lead_label(ld.group(1))} {render_inline(ld.group(2))}"
                out.append(
                    f'<p style="margin:{M_PARA};line-height:1.5;">{inner}</p>'
                )
                continue

            out.append(
                f'<p style="margin:{M_PARA};line-height:1.5;">{render_rich(s)}</p>'
            )
        else:
            if curtype and curtype != typ:
                flush()
            curtype = typ
            cur.append((typ, t))

    flush()
    return "".join(out)
