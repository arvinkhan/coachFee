from django.db import models


class Reminder(models.Model):
    """Reminder sent (or skipped) for an instalment."""

    KIND_CHOICES = [
        ('before', 'Before Due'),
        ('on', 'On Due Date'),
        ('after', 'After Due Date'),
    ]
    CHANNEL_CHOICES = [
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
    ]

    instalment = models.ForeignKey(
        'ledger.Instalment', on_delete=models.PROTECT, related_name='reminders'
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    day_offset = models.SmallIntegerField(
        help_text='Days relative to due date (-3=before, 0=on, +1/+7/+15=after)'
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default='whatsapp')
    language = models.CharField(max_length=2, default='en')
    message_text = models.TextField()
    sent_at = models.DateTimeField(null=True, blank=True)
    skipped = models.BooleanField(default=False)
    skipped_reason = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['instalment', 'day_offset'],
                name='unique_reminder_per_offset',
            )
        ]

    def __str__(self):
        return f"Reminder {self.kind} ({self.day_offset}d) — {self.instalment}"


class MessageLog(models.Model):
    """Mock WhatsApp/SMS message log for demo purposes."""

    phone = models.CharField(max_length=15)
    channel = models.CharField(max_length=20, default='whatsapp')
    message = models.TextField()
    language = models.CharField(max_length=2, default='en')
    sent_at = models.DateTimeField(auto_now_add=True)
    reminder = models.ForeignKey(
        Reminder, on_delete=models.SET_NULL, null=True, blank=True, related_name='message_logs'
    )

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f"Msg to {self.phone} at {self.sent_at}"
