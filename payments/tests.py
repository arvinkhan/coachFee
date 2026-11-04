import uuid
from datetime import date
from django.test import TestCase
from django.contrib.auth.models import User

from accounts.models import Guardian
from ledger.models import Centre, Batch, FeePlan, Student, Instalment, Payment, PaymentAllocation
from payments.models import PaymentLink, GatewayEvent, UnmatchedPayment
from payments.services import (
    generate_hmac_signature,
    verify_hmac_signature,
    process_webhook,
    get_or_create_payment_link
)


class PaymentWebhookAndSecurityTest(TestCase):
    """Automated tests for payment processing, idempotency and webhook security."""

    def setUp(self):
        self.centre = Centre.objects.create(name='Gopalpura', code='GPL')
        self.plan = FeePlan.objects.create(name='JEE Plan', total_amount=12000000, registration_fee=500000, gst_rate=18)
        self.batch = Batch.objects.create(centre=self.centre, name='JEE 2027', start_date=date(2026, 4, 1), end_date=date(2027, 3, 31))
        
        self.user = User.objects.create_user(username='guardian_test', password='password')
        self.guardian = Guardian.objects.create(user=self.user, phone='9829099999')
        self.student = Student.objects.create(
            student_id='STU-PAYTEST',
            name='Test Student',
            batch=self.batch,
            guardian=self.guardian,
            fee_plan=self.plan,
            enrollment_date=date(2026, 4, 1)
        )
        self.inst1 = Instalment.objects.create(student=self.student, sequence=1, amount=3000000, due_date=date(2026, 4, 10))
        self.inst2 = Instalment.objects.create(student=self.student, sequence=2, amount=3000000, due_date=date(2026, 7, 10))
        self.link = get_or_create_payment_link(self.inst1)

    def test_hmac_signature_verification(self):
        data = f"GW-12345|3000000|{self.link.token}"
        sig = generate_hmac_signature(data)
        self.assertTrue(verify_hmac_signature(data, sig))
        # Tampered data should fail
        self.assertFalse(verify_hmac_signature("TAMPERED_DATA", sig))

    def test_successful_webhook_processing_allocates_and_receipts(self):
        gateway_ref = f"GW-TEST-{uuid.uuid4().hex[:8]}"
        data = f"{gateway_ref}|3000000|{self.link.token}"
        sig = generate_hmac_signature(data)

        success, msg, payment = process_webhook(
            gateway_ref=gateway_ref,
            amount_paise=3000000,
            signature=sig,
            payment_link_token=self.link.token
        )

        self.assertTrue(success)
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, 3000000)
        self.assertEqual(payment.student, self.student)
        
        # Verify receipt created with GST
        self.assertTrue(hasattr(payment, 'receipt'))
        self.assertEqual(payment.receipt.total_amount, 3000000)

        # Verify instalment 1 allocated and link updated
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, 'paid')

    def test_duplicate_webhook_idempotency(self):
        gateway_ref = f"GW-IDEMPOTENT-{uuid.uuid4().hex[:8]}"
        data = f"{gateway_ref}|3000000|{self.link.token}"
        sig = generate_hmac_signature(data)

        # First call: succeeds
        success1, msg1, p1 = process_webhook(gateway_ref, 3000000, sig, self.link.token)
        self.assertTrue(success1)
        count_payments = Payment.objects.filter(gateway_ref=gateway_ref).count()
        self.assertEqual(count_payments, 1)

        # Second call with same gateway_ref: must be idempotent and not create duplicate payment
        success2, msg2, p2 = process_webhook(gateway_ref, 3000000, sig, self.link.token)
        self.assertTrue(success2)
        self.assertEqual(Payment.objects.filter(gateway_ref=gateway_ref).count(), 1)

    def test_invalid_webhook_signature_sent_to_unmatched_queue(self):
        gateway_ref = f"GW-INVALID-SIG-{uuid.uuid4().hex[:8]}"
        invalid_sig = "bogus_signature_12345"

        success, msg, payment = process_webhook(
            gateway_ref=gateway_ref,
            amount_paise=3000000,
            signature=invalid_sig,
            payment_link_token=self.link.token
        )

        self.assertFalse(success)
        self.assertIsNone(payment)
        # Instalment must NOT be marked paid
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, 'pending')

        # Must be logged in UnmatchedPayment queue
        unmatched = UnmatchedPayment.objects.filter(gateway_ref=gateway_ref).first()
        self.assertIsNotNone(unmatched)
        self.assertEqual(unmatched.amount, 3000000)

    def test_unknown_payment_link_sent_to_unmatched_queue(self):
        gateway_ref = f"GW-UNKNOWN-LINK-{uuid.uuid4().hex[:8]}"
        fake_token = uuid.uuid4()
        sig = generate_hmac_signature(f"{gateway_ref}|2000000|{fake_token}")

        success, msg, payment = process_webhook(
            gateway_ref=gateway_ref,
            amount_paise=2000000,
            signature=sig,
            payment_link_token=fake_token
        )

        self.assertFalse(success)
        self.assertIn("sent to unmatched queue", msg)
        self.assertTrue(UnmatchedPayment.objects.filter(gateway_ref=gateway_ref).exists())
