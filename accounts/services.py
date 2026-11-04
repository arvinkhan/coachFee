"""
Authentication & OTP Services for CoachFee.
- 6-digit OTP generation
- Expiry after 5 minutes
- 60-second rate limiting per phone
- Audit logging
"""
from django.conf import settings
from django.utils import timezone
from accounts.models import OTPLog, Guardian, AuditLog
from django.contrib.auth.models import User


def request_parent_otp(phone_number):
    """
    Generates OTP for a phone number if rate limit permits.
    Returns (success, message, otp_code_for_demo)
    """
    clean_phone = phone_number.strip().replace(' ', '').replace('-', '')
    if clean_phone.startswith('+91'):
        clean_phone = clean_phone[3:]

    # Check if a guardian exists with this phone
    guardian = Guardian.objects.filter(phone=clean_phone).first()
    if not guardian:
        return False, "No parent account found with this phone number.", None

    if not OTPLog.can_send(clean_phone):
        return False, "Please wait 60 seconds before requesting another OTP.", None

    otp_log, code = OTPLog.generate(clean_phone)
    AuditLog.log(
        actor=guardian.user,
        action="otp_requested",
        target=guardian,
        detail={"phone": clean_phone}
    )
    return True, "OTP sent successfully to your phone.", code


def verify_parent_otp(phone_number, entered_otp):
    """
    Verifies the provided OTP for phone number.
    Returns (success, message, user)
    """
    clean_phone = phone_number.strip().replace(' ', '').replace('-', '')
    if clean_phone.startswith('+91'):
        clean_phone = clean_phone[3:]

    otp_record = OTPLog.objects.filter(
        phone=clean_phone,
        verified=False
    ).order_by('-created_at').first()

    if not otp_record:
        return False, "No OTP request found for this phone number.", None

    if otp_record.is_expired:
        return False, "OTP has expired. Please request a new one.", None

    otp_record.attempts += 1
    if otp_record.attempts > 5:
        return False, "Too many failed attempts. Please request a new OTP.", None

    if otp_record.otp != entered_otp.strip():
        otp_record.save(update_fields=['attempts'])
        return False, "Incorrect OTP. Please check and try again.", None

    otp_record.verified = True
    otp_record.save(update_fields=['verified', 'attempts'])

    guardian = Guardian.objects.filter(phone=clean_phone).first()
    if not guardian:
        return False, "Parent profile not found.", None

    AuditLog.log(
        actor=guardian.user,
        action="otp_verified",
        target=guardian,
        detail={"phone": clean_phone}
    )

    return True, "OTP verified successfully.", guardian.user
