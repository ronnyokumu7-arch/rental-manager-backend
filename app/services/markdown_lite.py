# app/services/markdown_lite.py
import html
import re

def render_inline(text: str) -> str:
    """
    Render **bold** inline markers into <strong>, escaping everything else.
    Matches frontend: split by (\*\*[^*]+\*\*), wrap matches, escape rest.
    """
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    result = []
    for p in parts:
        if p.startswith("**") and p.endswith("**") and len(p) > 4:
            inner = html.escape(p[2:-2])
            result.append(f"<strong>{inner}</strong>")
        else:
            result.append(html.escape(p))
    return "".join(result)


def markdown_to_html(text: str) -> str:
    """
    Lightweight markdown to HTML converter, matching MarkdownLitePreview.
    Supports: **bold**, - bullet lists, 1. numbered lists, \n paragraph breaks.
    """
    if not text or not text.strip():
        return ""

    lines = text.split("\n")
    blocks = []
    
    for line in lines:
        t = line.rstrip()
        bullet_match = re.match(r"^[-*]\s+(.*)$", t)
        if bullet_match:
            blocks.append({"type": "bullet", "text": bullet_match.group(1)})
            continue
            
        num_match = re.match(r"^\d+[.)]\s+(.*)$", t)
        if num_match:
            blocks.append({"type": "numbered", "text": num_match.group(1)})
            continue
            
        blocks.append({"type": "paragraph", "text": t})

    html_parts = []
    current_list = []
    current_list_type = None

    def flush_list():
        nonlocal current_list, current_list_type
        if not current_list:
            return
        
        items_html = "".join(f"<li>{render_inline(item['text'])}</li>" for item in current_list)
        if current_list_type == "bullet":
            html_parts.append(
                f'<ul style="margin-left: 1.5rem; list-style-type: disc; margin-bottom: 0.5rem;">{items_html}</ul>'
            )
        else:
            html_parts.append(
                f'<ol style="margin-left: 1.5rem; list-style-type: decimal; margin-bottom: 0.5rem;">{items_html}</ol>'
            )
        
        current_list = []
        current_list_type = None

    for block in blocks:
        if block["type"] == "paragraph":
            flush_list()
            if block["text"].strip():
                # Styling matches frontend "contract" variant: 9.5pt, leading-relaxed, slate-600 (#475569), font-medium
                html_parts.append(
                    f'<p style="margin-bottom: 0.5rem; font-size: 9.5pt; line-height: 1.5; color: #475569; font-weight: 500;">'
                    f'{render_inline(block["text"])}</p>'
                )
        else:
            if current_list_type and current_list_type != block["type"]:
                flush_list()
            current_list_type = block["type"]
            current_list.append(block)

    flush_list()
    return "".join(html_parts)
