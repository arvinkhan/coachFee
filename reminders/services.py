"""
Reminders service:
- Generates reminders at -3 (before), 0 (on due date), +1, +7, +15 (after) days.
- English & Hindi language templates.
- Immediate recheck of balance at send time: stops the instant an instalment is paid.
- Duplicate prevention via unique constraint on (instalment, day_offset).
- Mock WhatsApp & SMS logging to MessageLog.
"""
from datetime import date, timedelta
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum
from ledger.models import Instalment, PaymentAllocation
from reminders.models import Reminder, MessageLog


TEMPLATES = {
    'en': {
        'before': "Dear Parent, this is a gentle reminder that Instalment #{sequence} of ₹{amount:,.0f} for {student_name} is due on {due_date}. Pay online here: {pay_url}",
        'on': "Dear Parent, Instalment #{sequence} of ₹{amount:,.0f} for {student_name} is due today ({due_date}). Please pay promptly: {pay_url}",
        'after': "Dear Parent, Instalment #{sequence} of ₹{amount:,.0f} for {student_name} is overdue by {days} days. Please clear the pending dues immediately: {pay_url}",
    },
    'hi': {
        'before': "नमस्ते, कृपया ध्यान दें कि {student_name} की किस्त #{sequence} (राशि ₹{amount:,.0f}) {due_date} को देय है। ऑनलाइन भुगतान लिंक: {pay_url}",
        'on': "नमस्ते, {student_name} की किस्त #{sequence} (राशि ₹{amount:,.0f}) का भुगतान आज ({due_date}) देय है। कृपया भुगतान करें: {pay_url}",
        'after': "नमस्ते, {student_name} की किस्त #{sequence} (राशि ₹{amount:,.0f}) {days} दिनों से बकाया है। कृपया शीघ्र भुगतान करें: {pay_url}",
    }
}


def build_reminder_message(kind, language, context):
    lang_templates = TEMPLATES.get(language, TEMPLATES['en'])
    tmpl = lang_templates.get(kind, TEMPLATES['en'][kind])
    return tmpl.format(**context)


def process_daily_reminders(target_date=None):
    """
    Scans for instalments due for reminder delivery on target_date:
    Offsets: -3 (before), 0 (on due), +1, +7, +15 (after)
    Rechecks balance immediately before dispatching.
    Stops sending if paid or already reminded for this offset.
    Returns summary stats dict.
    """
    target_date = target_date or date.today()
    stats = {'checked': 0, 'sent': 0, 'skipped_paid': 0, 'skipped_duplicate': 0}

    # Offsets configuration
    offsets = [
        (-3, 'before'),
        (0, 'on'),
        (1, 'after'),
        (7, 'after'),
        (15, 'after'),
    ]

    for offset_days, kind in offsets:
        # If instalment due_date + offset_days == target_date, then due_date = target_date - offset_days
        matching_due_date = target_date - timedelta(days=offset_days)
        candidates = Instalment.objects.select_related(
            'student__guardian__user',
            'student__batch'
        ).filter(due_date=matching_due_date)

        for inst in candidates:
            stats['checked'] += 1

            # 1. STOP-ON-PAY: Check real-time balance
            allocated = PaymentAllocation.objects.filter(instalment=inst).aggregate(
                total=Sum('amount')
            )['total'] or 0
            balance = inst.amount - allocated

            if balance <= 0:
                stats['skipped_paid'] += 1
                continue

            # 2. Check if already dispatched for this offset
            if Reminder.objects.filter(instalment=inst, day_offset=offset_days).exists():
                stats['skipped_duplicate'] += 1
                continue

            # 3. Formulate message in parent's preferred language
            guardian = inst.student.guardian
            lang = guardian.language or 'en'
            student_name = inst.student.name
            pay_url = f"/payments/pay/{inst.id}/"

            msg_text = build_reminder_message(
                kind=kind,
                language=lang,
                context={
                    'sequence': inst.sequence,
                    'amount': balance / 100,
                    'student_name': student_name,
                    'due_date': inst.due_date.strftime('%d-%b-%Y'),
                    'days': max(offset_days, 0),
                    'pay_url': pay_url,
                }
            )

            # 4. Create Reminder entry
            reminder = Reminder.objects.create(
                instalment=inst,
                kind=kind,
                day_offset=offset_days,
                channel='whatsapp',
                language=lang,
                message_text=msg_text,
                sent_at=timezone.now(),
                skipped=False
            )

            # 5. Log to MessageLog (mock WhatsApp delivery)
            MessageLog.objects.create(
                phone=guardian.phone,
                channel='whatsapp',
                message=msg_text,
                language=lang,
                reminder=reminder
            )

            stats['sent'] += 1

    return stats
