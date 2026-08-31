from datetime import datetime

# ─── BRAND CONSTANTS ────────────────────────────────────────────
BRAND = {
    "name": "Rental Garage",
    "primary": "#7C3AED",
    "primary_hover": "#6D28D9",
    "secondary": "#D97706",
    "secondary_light": "#FCD34D",
    "ink_primary": "#1C1917",
    "ink_muted": "#57534E",
    "ink_subtle": "#78716C",
    "surface": "#FFFFFF",
    "bg_warm": "#F7F4F0",
    "border": "rgba(44, 38, 32, 0.08)",
    "success": "#065F46",
    "success_bg": "rgba(6, 95, 70, 0.08)",
    "warning": "#92400E",
    "warning_bg": "rgba(146, 64, 14, 0.08)",
    "danger": "#991B1B",
    "danger_bg": "rgba(153, 27, 27, 0.08)",
}


def _format_currency(amount: str, currency: str = "KES") -> str:
    """Format currency with proper spacing."""
    return f"{currency} {amount}"


def _premium_template(
    title: str,
    body: str,
    footer: str = "",
    cta_text: str = "",
    cta_url: str = "",
    preview_text: str = "",
) -> str:
    """
    Multi-billion dollar email template with brand identity.
    """
    # CTA Button HTML
    cta_html = ""
    if cta_text and cta_url:
        cta_html = f"""
        <div style="margin: 28px 0 16px;">
            <a href="{cta_url}" 
               style="display: inline-block; 
                      background: linear-gradient(135deg, {BRAND['primary']} 0%, #5B21B6 100%);
                      color: #FFFFFF;
                      font-family: 'Inter', -apple-system, sans-serif;
                      font-size: 15px;
                      font-weight: 600;
                      padding: 14px 36px;
                      border-radius: 12px;
                      text-decoration: none;
                      box-shadow: 0 2px 16px rgba(124, 58, 237, 0.25);
                      transition: all 0.2s ease;">
                {cta_text}
            </a>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{BRAND['name']}</title>
    <style>
        /* ── Reset & Base ───────────────────────────────────────── */
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: {BRAND['bg_warm']};
            margin: 0;
            padding: 0;
            -webkit-font-smoothing: antialiased;
        }}
        
        /* ── Container ─────────────────────────────────────────── */
        .container {{
            max-width: 600px;
            margin: 40px auto;
            background: {BRAND['surface']};
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 4px 24px rgba(44, 38, 32, 0.06), 0 1px 4px rgba(44, 38, 32, 0.04);
        }}
        
        /* ── Header ────────────────────────────────────────────── */
        .header {{
            background: linear-gradient(145deg, #0E0C0A 0%, #1A1714 50%, #221F1B 100%);
            padding: 36px 40px 32px;
            position: relative;
            overflow: hidden;
        }}
        .header::before {{
            content: '';
            position: absolute;
            top: -50%;
            right: -20%;
            width: 300px;
            height: 300px;
            background: radial-gradient(circle, rgba(124, 58, 237, 0.08) 0%, transparent 70%);
            border-radius: 50%;
        }}
        .header::after {{
            content: '';
            position: absolute;
            bottom: -40%;
            left: -10%;
            width: 200px;
            height: 200px;
            background: radial-gradient(circle, rgba(217, 119, 6, 0.06) 0%, transparent 70%);
            border-radius: 50%;
        }}
        .header-content {{
            position: relative;
            z-index: 1;
        }}
        .header-brand {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .header-logo {{
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, {BRAND['primary']} 0%, #5B21B6 100%);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: 'Space Grotesk', 'Inter', sans-serif;
            font-weight: 700;
            font-size: 16px;
            color: #FFFFFF;
            box-shadow: 0 2px 12px rgba(124, 58, 237, 0.25);
        }}
        .header-title {{
            font-family: 'Space Grotesk', 'Inter', sans-serif;
            color: #FFFFFF;
            font-size: 20px;
            font-weight: 700;
            letter-spacing: -0.02em;
        }}
        .header-title span {{
            color: {BRAND['primary']};
        }}
        .header-subtitle {{
            color: rgba(255, 255, 255, 0.5);
            font-size: 12px;
            font-weight: 400;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            margin-top: 2px;
        }}
        .header-preview {{
            color: rgba(255, 255, 255, 0.4);
            font-size: 13px;
            margin-top: 8px;
            font-weight: 300;
        }}
        
        /* ── Body ────────────────────────────────────────────────── */
        .body {{
            padding: 40px 40px 32px;
            color: {BRAND['ink_primary']};
            font-size: 15px;
            line-height: 1.7;
        }}
        .body h2 {{
            font-family: 'Space Grotesk', 'Inter', sans-serif;
            font-size: 22px;
            font-weight: 700;
            color: {BRAND['ink_primary']};
            letter-spacing: -0.02em;
            margin: 0 0 8px;
        }}
        .body p {{
            margin: 0 0 16px;
            color: {BRAND['ink_muted']};
        }}
        .body p strong {{
            color: {BRAND['ink_primary']};
        }}
        
        /* ── Divider ────────────────────────────────────────────── */
        .divider {{
            height: 1px;
            background: {BRAND['border']};
            margin: 24px 0;
        }}
        
        /* ── Detail Table ───────────────────────────────────────── */
        .detail-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0 20px;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid {BRAND['border']};
        }}
        .detail-table tr {{
            border-bottom: 1px solid {BRAND['border']};
        }}
        .detail-table tr:last-child {{
            border-bottom: none;
        }}
        .detail-table td {{
            padding: 12px 16px;
            font-size: 14px;
        }}
        .detail-table td:first-child {{
            color: {BRAND['ink_subtle']};
            font-weight: 500;
            width: 40%;
            background: {BRAND['bg_warm']};
        }}
        .detail-table td:last-child {{
            color: {BRAND['ink_primary']};
            font-weight: 600;
        }}
        .detail-table .total-row td:last-child {{
            font-size: 16px;
            color: {BRAND['primary']};
        }}
        
        /* ── Badges ──────────────────────────────────────────────── */
        .badge {{
            display: inline-block;
            padding: 4px 14px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.02em;
        }}
        .badge-confirmed {{
            background: #ECFDF5;
            color: {BRAND['success']};
            border: 1px solid rgba(6, 95, 70, 0.12);
        }}
        .badge-active {{
            background: #EEF2FF;
            color: #1E40AF;
            border: 1px solid rgba(30, 64, 175, 0.12);
        }}
        .badge-pending {{
            background: #FFFBEB;
            color: {BRAND['warning']};
            border: 1px solid rgba(146, 64, 14, 0.12);
        }}
        .badge-completed {{
            background: #ECFDF5;
            color: {BRAND['success']};
            border: 1px solid rgba(6, 95, 70, 0.12);
        }}
        .badge-cancelled {{
            background: #FEF2F2;
            color: {BRAND['danger']};
            border: 1px solid rgba(153, 27, 27, 0.12);
        }}
        
        /* ── Footer ───────────────────────────────────────────────── */
        .footer {{
            padding: 24px 40px 32px;
            background: {BRAND['bg_warm']};
            border-top: 1px solid {BRAND['border']};
            font-size: 12px;
            color: {BRAND['ink_subtle']};
            text-align: center;
            line-height: 1.8;
        }}
        .footer a {{
            color: {BRAND['primary']};
            text-decoration: none;
            font-weight: 500;
        }}
        .footer a:hover {{
            color: {BRAND['primary_hover']};
            text-decoration: underline;
        }}
        .footer-brand {{
            font-family: 'Space Grotesk', 'Inter', sans-serif;
            font-weight: 600;
            color: {BRAND['ink_primary']};
            font-size: 13px;
        }}
        .footer-brand span {{
            color: {BRAND['primary']};
        }}
        .footer-divider {{
            display: inline-block;
            margin: 0 8px;
            color: {BRAND['border']};
        }}
        .footer-social {{
            margin: 12px 0 8px;
        }}
        .footer-social a {{
            display: inline-block;
            margin: 0 6px;
            color: {BRAND['ink_subtle']};
            font-size: 13px;
            text-decoration: none;
        }}
        .footer-social a:hover {{
            color: {BRAND['primary']};
        }}
        
        /* ── Responsive ──────────────────────────────────────────── */
        @media (max-width: 480px) {{
            .container {{
                margin: 0;
                border-radius: 0;
            }}
            .header {{
                padding: 28px 24px 24px;
            }}
            .body {{
                padding: 28px 24px 24px;
            }}
            .footer {{
                padding: 20px 24px 24px;
            }}
            .header-title {{
                font-size: 18px;
            }}
            .detail-table td {{
                padding: 10px 12px;
                font-size: 13px;
            }}
            .body h2 {{
                font-size: 19px;
            }}
        }}
    </style>
    </head>
    <body>
    <div class="container">
        <!-- ── Header ────────────────────────────────────────────── -->
        <div class="header">
            <div class="header-content">
                <div class="header-brand">
                    <div class="header-logo">RG</div>
                    <div>
                        <div class="header-title">Rental<span>Garage</span></div>
                        <div class="header-subtitle">Enterprise Fleet Management</div>
                    </div>
                </div>
                {f'<div class="header-preview">{preview_text}</div>' if preview_text else ''}
            </div>
        </div>
        
        <!-- ── Body ────────────────────────────────────────────────── -->
        <div class="body">
            <h2>{title}</h2>
            {body}
            {cta_html}
        </div>
        
        <!-- ── Footer ────────────────────────────────────────────────── -->
        <div class="footer">
            <div class="footer-brand">Rental<span>Garage</span></div>
            <div style="font-size: 11px; color: #A8A39E; margin-top: 4px;">
                Enterprise Fleet Management Platform
            </div>
            <div class="footer-divider" style="margin: 12px 0;"></div>
            <div style="font-size: 12px; color: #78716C;">
                {footer or "This is an automated message from Rental Garage. Please do not reply to this email."}
            </div>
            <div style="margin-top: 12px; font-size: 11px; color: #A8A39E;">
                © {datetime.now().year} Rental Garage. All rights reserved.
            </div>
        </div>
    </div>
    </body>
    </html>
    """
