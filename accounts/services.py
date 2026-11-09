"""
Authentication & OTP Services for CoachFee.
- Supports Parent login via Email ID or Phone number
- 6-digit OTP generation
- Expiry after 5 minutes
- Rate limiting per identifier
- Audit logging
"""
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from accounts.models import OTPLog, Guardian, AuditLog
from django.contrib.auth.models import User


def normalize_identifier(identifier):
    raw = (identifier or '').strip()
    if '@' in raw:
        return raw.lower(), 'email'
    clean = raw.replace(' ', '').replace('-', '')
    if clean.startswith('+91'):
        clean = clean[3:]
    return clean, 'phone'


def find_guardian(identifier):
    clean, id_type = normalize_identifier(identifier)
    if not clean:
        return None, ''
    if id_type == 'email':
        guardian = Guardian.objects.filter(Q(email__iexact=clean) | Q(user__email__iexact=clean)).first()
    else:
        guardian = Guardian.objects.filter(phone=clean).first()
    return guardian, clean


def request_parent_otp(identifier):
    """
    Generates OTP for a parent email (or phone) if rate limit permits.
    Returns (success, message, otp_code_for_demo)
    """
    guardian, clean_id = find_guardian(identifier)
    if not guardian:
        return False, f"No parent account found for '{identifier}'. Please check the email ID.", None

    if not OTPLog.can_send(clean_id):
        return False, "Please wait 60 seconds before requesting another OTP.", None

    otp_log, code = OTPLog.generate(clean_id)
    AuditLog.log(
        actor=guardian.user,
        action="otp_requested",
        target=guardian,
        detail={"identifier": clean_id}
    )
    return True, "OTP sent successfully.", code


def verify_parent_otp(identifier, entered_otp):
    """
    Verifies the provided OTP for parent email or phone.
    Returns (success, message, user)
    """
    guardian, clean_id = find_guardian(identifier)
    if not guardian:
        return False, "Parent profile not found.", None

    otp_record = OTPLog.objects.filter(
        phone=clean_id,
        verified=False
    ).order_by('-created_at').first()

    if not otp_record:
        return False, f"No OTP request found for '{identifier}'.", None

    if otp_record.is_expired:
        return False, "OTP has expired. Please request a new one.", None

    otp_record.attempts += 1
    if otp_record.attempts > 5:
        return False, "Too many failed attempts. Please request a new OTP.", None

    if otp_record.otp != (entered_otp or '').strip():
        otp_record.save(update_fields=['attempts'])
        return False, "Incorrect OTP. Please check and try again.", None

    otp_record.verified = True
    otp_record.save(update_fields=['verified', 'attempts'])

    AuditLog.log(
        actor=guardian.user,
        action="otp_verified",
        target=guardian,
        detail={"identifier": clean_id}
    )

    return True, "OTP verified successfully.", guardian.user
