# app/services/markdown_lite.py
"""
✅ Markdown-lite → HTML converter for the contract PDF.
Mirrors src/lib/markdownLite.tsx byte-for-byte so the PDF and the public web
page render identical hierarchy: run-in **Label:** leads, fully-bold block
sub-headings, lists, and vertical rhythm. Inline styles (not classes) because
the PDF template has no stylesheet for these tokens.
"""
import html
import re

# A line that is entirely bold → block sub-heading.
FULL_HEAD_RE = re.compile(r"^\*\*([^*]+)\*\*$")
# A line that starts with a bold label ending in a colon, then body → run-in heading.
LEAD_RE = re.compile(r"^\*\*([^*]+?:)\*\*\s+(.+)$", re.S)

# Theme constants (match the React component's fallbacks).
INK = "#0f172a"
MUTED = "#475569"
ACCENT = "#B45309"


def render_inline(text: str) -> str:
    """Render **bold** inline markers into <strong>, escaping everything else."""
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    out = []
    for p in parts:
        if p.startswith("**") and p.endswith("**") and len(p) > 4:
            inner = html.escape(p[2:-2])
            out.append(
                f'<strong style="color:{INK};font-weight:700;letter-spacing:0.01em;">{inner}</strong>'
            )
        else:
            out.append(html.escape(p))
    return "".join(out)


def render_rich(text: str) -> str:
    """Promote a leading **Label:** into an emphasized lead span."""
    m = LEAD_RE.match(text)
    if m:
        label = html.escape(m.group(1))
        rest = render_inline(m.group(2))
        return (
            f'<span style="color:{INK};font-weight:800;letter-spacing:0.015em;">{label}</span> '
            f"{rest}"
        )
    return render_inline(text)


def markdown_to_html(text: str) -> str:
    """
    Lightweight markdown → HTML, matching MarkdownLitePreview(variant="contract").
    Supports: **bold**, - bullet lists, 1. numbered lists, \n paragraph breaks,
    run-in **Label:** leads, and fully-bold block sub-headings.
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
        items = "".join(
            f'<li style="margin-bottom:2px;color:{MUTED};">{render_rich(t)}</li>'
            for _, t in cur
        )
        tag = "ul" if curtype == "bullet" else "ol"
        ls = "disc" if curtype == "bullet" else "decimal"
        out.append(
            f'<{tag} style="margin:5px 0 5px 0;padding-left:16px;list-style-type:{ls};">{items}</{tag}>'
        )
        cur = []
        curtype = None

    for typ, t in blocks:
        if typ == "paragraph":
            flush()
            s = t.strip()
            if not s:
                continue
            fh = FULL_HEAD_RE.match(s)
            if fh:
                inner = html.escape(fh.group(1).rstrip(":"))
                out.append(
                    f'<p style="margin:10px 0 5px 0;padding-left:8px;'
                    f'border-left:2px solid {ACCENT};color:{INK};font-weight:800;'
                    f'font-size:9.5pt;letter-spacing:0.02em;line-height:1.4;">'
                    f"{render_inline(inner)}</p>"
                )
            else:
                out.append(
                    f'<p style="margin:0 0 5px 0;color:{MUTED};line-height:1.5;">'
                    f"{render_rich(s)}</p>"
                )
        else:
            if curtype and curtype != typ:
                flush()
            curtype = typ
            cur.append((typ, t))

    flush()
    return "".join(out)
