"""Notification transports (currently: email)."""
from .email import send_deal_alerts

__all__ = ["send_deal_alerts"]
