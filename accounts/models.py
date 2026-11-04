import random
import string
from django.conf import settings
from django.db import models
from django.utils import timezone


class Guardian(models.Model):
    """Parent/guardian linked to a Django user via OTP login."""

    LANGUAGE_CHOICES = [
        ('en', 'English'),
        ('hi', 'Hindi'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='guardian_profile',
    )
    phone = models.CharField(max_length=15, unique=True, db_index=True)
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default='en')
    consent_given = models.BooleanField(default=False)
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=20, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.phone}"

    class Meta:
        ordering = ['user__first_name']


class StaffProfile(models.Model):
    """Accounts executive or counsellor staff profile."""

    ROLE_CHOICES = [
        ('accounts_exec', 'Accounts Executive'),
        ('counsellor', 'Counsellor'),
        ('admin', 'Admin'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_profile',
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='accounts_exec')
    centre = models.ForeignKey(
        'ledger.Centre',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='staff',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_accounts_exec(self):
        return self.role in ('accounts_exec', 'admin')

    @property
    def is_counsellor(self):
        return self.role in ('counsellor', 'admin')


class OTPLog(models.Model):
    """Tracks OTP generation and verification for rate-limiting and audit."""

    phone = models.CharField(max_length=15, db_index=True)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    verified = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP for {self.phone} at {self.created_at}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @classmethod
    def generate(cls, phone):
        """Generate a new OTP. Returns (otp_log, otp_code)."""
        code = ''.join(random.choices(string.digits, k=getattr(settings, 'OTP_LENGTH', 6)))
        expiry = timezone.now() + timezone.timedelta(
            seconds=getattr(settings, 'OTP_EXPIRY_SECONDS', 300)
        )
        log = cls.objects.create(phone=phone, otp=code, expires_at=expiry)
        return log, code

    @classmethod
    def can_send(cls, phone):
        """Rate limit: only one OTP per minute."""
        cutoff = timezone.now() - timezone.timedelta(
            seconds=getattr(settings, 'OTP_RATE_LIMIT_SECONDS', 60)
        )
        return not cls.objects.filter(phone=phone, created_at__gte=cutoff).exists()


class AuditLog(models.Model):
    """Audit trail for important financial operations."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.CharField(max_length=50, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} by {self.actor} at {self.created_at}"

    @classmethod
    def log(cls, actor, action, target=None, detail=None):
        return cls.objects.create(
            actor=actor,
            action=action,
            target_type=type(target).__name__ if target else '',
            target_id=str(target.pk) if target else '',
            detail=detail or {},
        )
