import html
import re

M_PARA = "0 0 5px 0"
M_HEAD = "9px 0 4px 0"
M_LIST = "4px 0 6px 0"
M_ITEM = "0 0 4px 0"
M_SUBHEAD = "8px 0 4px 0"

INK = "#0f172a"
MUTED = "#475569"
ACCENT = "#B45309"

NUM_LEAD_BOLD = re.compile(r"^\*\*(\d+[.)])\s+([^*]+?:)\*\*\s+([\s\S]+)$")
NUM_LEAD_PLAIN = re.compile(r"^(\d+[.)])\s+\*\*([^*]+?:)\*\*\s+([\s\S]+)$")
NUM_PLAIN = re.compile(r"^(\d+[.)])\s+([\s\S]+)$")
NUM_SUBHEAD = re.compile(r"^\*\*\d+[.)]\s+([^*]+?)\*\*:?\s*$")
FULL_HEAD_RE = re.compile(r"^\*\*([^*]+)\*\*$")
LEAD_RE = re.compile(r"^\*\*([^*]+?:)\*\*\s+([\s\S]+)$")


def _esc(s: str) -> str:
    return html.escape(s)


def render_inline(text: str) -> str:
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
    m = LEAD_RE.match(text)
    if m:
        return f"{_lead_label(m.group(1))} {render_inline(m.group(2))}"
    return render_inline(text)


def _hang_row(marker: str, inner: str, bullet: bool = False, margin: str = M_ITEM, indent: bool = False) -> str:
    weight = "400" if bullet else "800"
    # ✅ FIX: Bullets get pushed right (1.5rem) to align with the TEXT of the parent number.
    padding = "padding-left:1.5rem;" if indent else ""
    return (
        f'<div style="display:flex;gap:6px;margin:{margin};{padding}">'
        f'<span style="flex:0 0 auto;min-width:1.1em;font-weight:{weight};color:{INK};">'
        f"{_esc(marker)}</span>"
        f'<span style="flex:1 1 auto;line-height:1.5;">{inner}</span>'
        f"</div>"
    )


def markdown_to_html(text: str) -> str:
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
        
        nm = re.match(r"^(\d+[.)])\s+(.*)$", t)
        if nm:
            # ✅ FIX: Check if text after number has bold label.
            # If yes -> list item. If no -> paragraph (like item 7).
            has_bold_label = re.search(r"\*\*[^*]+:\*\*", nm.group(2))
            if has_bold_label:
                blocks.append(("numbered", nm.group(2)))
            else:
                blocks.append(("paragraph", t))
            continue
            
        blocks.append(("paragraph", t))

    out = []
    cur = []
    curtype = None

    subhead_indent = "1.25rem"

    def flush():
        nonlocal cur, curtype
        if not cur:
            return
        rows = []
        for idx, (_, t) in enumerate(cur):
            marker = "•" if curtype == "bullet" else f"{idx + 1}."
            rows.append(_hang_row(marker, render_rich(t), bullet=(curtype == "bullet"), indent=(curtype == "bullet")))
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

            # ✅ FIX: Catches "7. Please do not..." -> strips number, renders as paragraph.
            npl = NUM_PLAIN.match(s)
            if npl:
                inner = render_rich(npl.group(2))
                out.append(f'<p style="margin:{M_PARA};line-height:1.5;">{inner}</p>')
                continue

            ns = NUM_SUBHEAD.match(s)
            if ns:
                inner = render_inline(ns.group(1))
                out.append(
                    f'<div style="margin:{M_SUBHEAD};padding-left:{subhead_indent};'
                    f'font-weight:800;color:{INK};font-size:9.5pt;letter-spacing:0.01em;">'
                    f"{inner}</div>"
                )
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
