"""Email alerts.

Composes a digest of new deals and sends it. The email shows exactly what the
brief requires per deal: **product name, size, website, direct link, price** —
plus colour, discount and condition for context.

Transport is auto-detected from environment variables, in priority order:

    SMTP        -> SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_TLS
    SendGrid    -> SENDGRID_API_KEY  (+ ALERT_EMAIL_FROM)
    Resend      -> RESEND_API_KEY    (+ ALERT_EMAIL_FROM)
    (none)      -> dry run: writes dist/last_email.html and prints a summary

Recipients come from config.yml ``email.to`` or the ALERT_EMAIL_TO env var.
A rendered copy is always written to dist/last_email.html for inspection.
"""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import requests

from ..config import Config, ROOT
from ..models import Deal

_CURRENCY_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "ARS": "$"}


def _fmt_price(price: float, currency: str) -> str:
    sym = _CURRENCY_SYMBOL.get(currency, "")
    return f"{sym}{price:,.2f} {currency}".strip()


def _recipients(cfg: Config) -> list[str]:
    return [r for r in (cfg.get("email.to", []) or []) if r]


# --------------------------------------------------------------------------- #
# Rendering                                                                    #
# --------------------------------------------------------------------------- #
_TIER = {
    "excellent": ("#0a7d33", "Excelente"), "great": ("#127a4a", "Muy buena"),
    "good": ("#3a7a5a", "Buena"), "suspect": ("#b26a00", "Verificar"),
    "target": ("#2a6a8a", "Objetivo"),
}


def render_html(cfg: Config, deals: list[Deal]) -> str:
    site = cfg.get("site.title", "Elite Brand Engine")
    rows = []
    for d in sorted(deals, key=lambda x: x.score, reverse=True):
        eff_disc = d.effective_discount_pct if d.effective_discount_pct is not None else d.discount_pct
        disc = f'<span style="color:#0a7d33;font-weight:700">-{eff_disc:.0f}%</span>' if eff_disc else "—"
        ref = f'<span style="color:#8a8a8a;text-decoration:line-through">{_fmt_price(d.reference_price, d.currency)}</span>' if d.reference_price else ""
        size = d.size or "—"
        color = f" · {d.color.title()}" if d.color else ""
        cond = "" if d.condition == "new" else f' <span style="color:#b26a00">({d.condition})</span>'
        tcolor, tlabel = _TIER.get(d.tier, ("#3a7a5a", d.tier or ""))
        badge = (f'<span style="background:{tcolor};color:#fff;padding:2px 7px;'
                 f'border-radius:9px;font-size:11px;font-weight:700;">{tlabel}</span>')
        season = (f'<div style="color:#0a7d33;font-size:12px;margin-top:2px;">❄️☀️ {d.season_note}</div>'
                  if d.seasonal and d.season_note else "")
        stacked = bool(d.stack_note and d.effective_price is not None)
        stack = (f'<div style="color:#0a7d33;font-size:12px;margin-top:2px;">🧩 {d.stack_note}</div>'
                 if stacked else "")
        headline = _fmt_price(d.effective_price if stacked else d.price, d.currency)
        subprice = (f'<div style="font-size:11px;color:#8a8a8a;">sticker {_fmt_price(d.price, d.currency)} · efectivo</div>'
                    if stacked else "")
        rows.append(f"""
        <tr>
          <td style="padding:12px 10px;border-bottom:1px solid #eee;">
            <div style="font-weight:700;color:#12222b;font-size:15px;">{d.brand} — {d.product_name} &nbsp;{badge}</div>
            <div style="color:#5a6b73;font-size:13px;">Talla: <b>{size}</b>{color}{cond}</div>
            <div style="color:#5a6b73;font-size:12px;margin-top:2px;">{d.reason}</div>
            {season}{stack}
          </td>
          <td style="padding:12px 10px;border-bottom:1px solid #eee;white-space:nowrap;">
            <span style="background:#eef6f0;color:#12222b;padding:3px 8px;border-radius:10px;font-size:12px;">{d.source}</span>
          </td>
          <td style="padding:12px 10px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;">
            <div style="font-size:17px;font-weight:800;color:#12222b;">{headline}</div>
            {subprice}
            <div style="font-size:12px;">{ref} {disc}</div>
          </td>
          <td style="padding:12px 10px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;">
            <a href="{d.url}" style="background:#12684f;color:#fff;text-decoration:none;padding:8px 14px;border-radius:8px;font-size:13px;font-weight:700;">Ver oferta →</a>
          </td>
        </tr>""")

    return f"""<!doctype html><html><body style="margin:0;background:#f4f6f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
      <div style="max-width:680px;margin:0 auto;padding:24px 12px;">
        <div style="background:#12222b;color:#fff;border-radius:14px 14px 0 0;padding:20px 22px;">
          <div style="font-size:20px;font-weight:800;">🏔️ {site}</div>
          <div style="color:#9fb7bf;font-size:13px;">{len(deals)} nueva(s) oferta(s) detectada(s)</div>
        </div>
        <div style="background:#fff;border-radius:0 0 14px 14px;padding:8px 12px 18px;">
          <table style="width:100%;border-collapse:collapse;">{''.join(rows)}</table>
          <p style="color:#8a9aa1;font-size:11px;padding:14px 8px 0;margin:0;">
            Precios de comparación obtenidos por vías legítimas (APIs oficiales y datafeeds de afiliados).
            Verifica siempre el precio final en el sitio del comercio antes de comprar.
          </p>
        </div>
      </div>
    </body></html>"""


def render_text(cfg: Config, deals: list[Deal]) -> str:
    lines = [f"{cfg.get('site.title', 'Elite Brand Engine')} — {len(deals)} nueva(s) oferta(s)\n"]
    for d in sorted(deals, key=lambda x: x.score, reverse=True):
        eff_disc = d.effective_discount_pct if d.effective_discount_pct is not None else d.discount_pct
        disc = f" (-{eff_disc:.0f}%)" if eff_disc else ""
        _, tlabel = _TIER.get(d.tier, ("", d.tier or ""))
        stacked = bool(d.stack_note and d.effective_price is not None)
        price_line = (f"    Precio efectivo: {_fmt_price(d.effective_price, d.currency)}{disc}"
                      f"  (sticker {_fmt_price(d.price, d.currency)})\n"
                      if stacked else
                      f"    Precio: {_fmt_price(d.price, d.currency)}{disc}\n")
        lines.append(
            f"• [{tlabel}] {d.brand} — {d.product_name}\n"
            f"    Talla: {d.size or '—'}"
            + (f" · {d.color.title()}" if d.color else "")
            + (f" · {d.condition}" if d.condition != 'new' else "")
            + "\n"
            f"    Website: {d.source}\n"
            + price_line
            + f"    Motivo: {d.reason}\n"
            + (f"    Apilado: {d.stack_note}\n" if stacked else "")
            + (f"    Temporada: {d.season_note}\n" if d.seasonal and d.season_note else "")
            + f"    Link: {d.url}\n"
        )
    lines.append("\nVerifica el precio final en el sitio del comercio antes de comprar.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Sending                                                                      #
# --------------------------------------------------------------------------- #
def _subject(cfg: Config, deals: list[Deal]) -> str:
    prefix = cfg.get("email.subject_prefix", "")
    top = max(deals, key=lambda x: x.score)
    extra = f" — {top.brand} {top.product_name}" if len(deals) == 1 else ""
    return f"{prefix}{len(deals)} oferta(s) nueva(s){extra}"


def _send_smtp(subject, html, text, sender, to) -> bool:
    host = os.getenv("SMTP_HOST")
    if not host:
        return False
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pw = os.getenv("SMTP_PASS")
    use_tls = os.getenv("SMTP_TLS", "true").lower() != "false"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(host, port, timeout=30) as server:
        if use_tls:
            server.starttls()
        if user and pw:
            server.login(user, pw)
        server.sendmail(sender, to, msg.as_string())
    print(f"[email] sent via SMTP to {len(to)} recipient(s)")
    return True


def _send_sendgrid(subject, html, text, sender, to) -> bool:
    key = os.getenv("SENDGRID_API_KEY")
    if not key:
        return False
    r = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "personalizations": [{"to": [{"email": a} for a in to]}],
            "from": {"email": sender},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text},
                {"type": "text/html", "value": html},
            ],
        },
        timeout=30,
    )
    r.raise_for_status()
    print(f"[email] sent via SendGrid to {len(to)} recipient(s)")
    return True


def _send_resend(subject, html, text, sender, to) -> bool:
    key = os.getenv("RESEND_API_KEY")
    if not key:
        return False
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"from": sender, "to": to, "subject": subject, "html": html, "text": text},
        timeout=30,
    )
    r.raise_for_status()
    print(f"[email] sent via Resend to {len(to)} recipient(s)")
    return True


def send_deal_alerts(cfg: Config, deals: list[Deal]) -> bool:
    """Send (or dry-run) an alert email for ``deals``. Returns True if handled."""
    if not deals:
        print("[email] no new deals; nothing to send")
        return True
    if not cfg.get("email.enabled", True):
        print("[email] disabled in config")
        return False

    html = render_html(cfg, deals)
    text = render_text(cfg, deals)
    subject = _subject(cfg, deals)

    # Always leave a rendered copy for inspection / CI artifact.
    out = ROOT / "dist" / "last_email.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    to = _recipients(cfg)
    sender = (
        os.getenv("SMTP_FROM")
        or os.getenv("ALERT_EMAIL_FROM")
        or os.getenv("SMTP_USER")
        or "alerts@example.com"
    )

    if not to:
        print(f"[email] DRY RUN — no recipients configured. "
              f"{len(deals)} deal(s) rendered to {out}")
        return True

    for sender_fn in (_send_smtp, _send_sendgrid, _send_resend):
        try:
            if sender_fn(subject, html, text, sender, to):
                return True
        except Exception as exc:  # noqa: BLE001 - try next transport, stay non-fatal
            print(f"[email] {sender_fn.__name__} failed: {exc}")

    print(f"[email] DRY RUN — no transport configured. "
          f"{len(deals)} deal(s) rendered to {out}")
    return True
