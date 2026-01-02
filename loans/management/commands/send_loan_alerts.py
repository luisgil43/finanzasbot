from __future__ import annotations

from datetime import timedelta

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from bot_telegram.models import TelegramLink
from loans.models import LoanAlertLog, LoanInstallment


def _bot_token() -> str:
    tok = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or getattr(settings, "TELEGRAM_TOKEN", "")
    if not tok:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN")
    return tok


def tg_send_message(chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{_bot_token()}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=12)


class Command(BaseCommand):
    help = "Envía alertas de cuotas (vence hoy / vence pronto / atrasada)"

    def handle(self, *args, **options):
        today = timezone.localdate()
        soon_days = 3

        qs = LoanInstallment.objects.select_related("loan", "loan__user").filter(
            status__in=[LoanInstallment.STATUS_PENDING, LoanInstallment.STATUS_OVERDUE]
        )

        sent = 0
        for inst in qs:
            inst.refresh_overdue_status()

            alert_type = None
            if inst.status == LoanInstallment.STATUS_OVERDUE:
                alert_type = LoanAlertLog.ALERT_OVERDUE
            elif inst.due_date == today:
                alert_type = LoanAlertLog.ALERT_DUE_TODAY
            elif today < inst.due_date <= (today + timedelta(days=soon_days)):
                alert_type = LoanAlertLog.ALERT_DUE_SOON

            if not alert_type:
                continue

            link = TelegramLink.objects.filter(profile__user=inst.loan.user).first()
            if not link:
                continue

            # idempotencia simple (no repetir en 24h)
            since = timezone.now() - timedelta(hours=24)
            if LoanAlertLog.objects.filter(
                installment=inst,
                alert_type=alert_type,
                channel=LoanAlertLog.CHANNEL_TELEGRAM,
                sent_at__gte=since,
            ).exists():
                continue

            person = inst.loan.person_name
            txt = (
                f"🔔 Cuota {inst.n}/{inst.loan.installments_count} · {person}\n"
                f"Vence: {inst.due_date}\n"
                f"Monto: {inst.amount_original} {inst.currency_original}"
            )

            tg_send_message(link.telegram_chat_id, txt)
            LoanAlertLog.objects.create(
                installment=inst,
                alert_type=alert_type,
                channel=LoanAlertLog.CHANNEL_TELEGRAM,
            )
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Alertas enviadas: {sent}"))