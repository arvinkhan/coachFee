from datetime import date
from django.test import TestCase
from django.contrib.auth.models import User

from accounts.models import Guardian
from ledger.models import Centre, Batch, FeePlan, Student, Instalment, Payment, PaymentAllocation
from reminders.models import Reminder, MessageLog
from reminders.services import process_daily_reminders, build_reminder_message


class RemindersAutomationTest(TestCase):
    """Automated tests for reminder generation, stop-on-pay, and duplicate prevention."""

    def setUp(self):
        self.centre = Centre.objects.create(name='Jaipur', code='JPR')
        self.plan = FeePlan.objects.create(name='Plan', total_amount=12000000, registration_fee=500000, gst_rate=18)
        self.batch = Batch.objects.create(centre=self.centre, name='Batch 1', start_date=date(2026, 4, 1), end_date=date(2027, 3, 31))
        
        # English speaking guardian
        self.u1 = User.objects.create_user(username='parent_en', password='password')
        self.g_en = Guardian.objects.create(user=self.u1, phone='9829000001', language='en')
        self.s1 = Student.objects.create(student_id='STU-REM-EN', name='Aman', batch=self.batch, guardian=self.g_en, fee_plan=self.plan, enrollment_date=date(2026, 4, 1))

        # Hindi speaking guardian
        self.u2 = User.objects.create_user(username='parent_hi', password='password')
        self.g_hi = Guardian.objects.create(user=self.u2, phone='9829000002', language='hi')
        self.s2 = Student.objects.create(student_id='STU-REM-HI', name='Pooja', batch=self.batch, guardian=self.g_hi, fee_plan=self.plan, enrollment_date=date(2026, 4, 1))

    def test_reminder_message_templates_en_and_hi(self):
        ctx = {'sequence': 2, 'amount': 30000, 'student_name': 'Aman', 'due_date': '10-Nov-2026', 'pay_url': '/pay/1/'}
        msg_en = build_reminder_message('before', 'en', ctx)
        self.assertIn("gentle reminder", msg_en)
        self.assertIn("Aman", msg_en)

        msg_hi = build_reminder_message('before', 'hi', ctx)
        self.assertIn("नमस्ते", msg_hi)
        self.assertIn("किस्त #2", msg_hi)

    def test_stop_on_pay_suppresses_reminders(self):
        target_date = date(2026, 11, 4)
        # Due on target_date (offset 0)
        inst = Instalment.objects.create(student=self.s1, sequence=1, amount=3000000, due_date=target_date)

        # Before paying: running reminders should dispatch
        stats1 = process_daily_reminders(target_date)
        self.assertEqual(stats1['sent'], 1)
        self.assertTrue(Reminder.objects.filter(instalment=inst, day_offset=0).exists())

        # Now student pays full balance
        pay = Payment.objects.create(student=self.s1, amount=3000000, mode='gateway')
        PaymentAllocation.objects.create(payment=pay, instalment=inst, amount=3000000)

        # Create another instalment due today for Student 2
        inst2 = Instalment.objects.create(student=self.s2, sequence=1, amount=3000000, due_date=target_date)
        # Fully pay inst2 immediately
        pay2 = Payment.objects.create(student=self.s2, amount=3000000, mode='gateway')
        PaymentAllocation.objects.create(payment=pay2, instalment=inst2, amount=3000000)

        # Process reminders: inst1 is already sent & paid, inst2 is paid -> sent should be 0, skipped_paid >= 1
        stats2 = process_daily_reminders(target_date)
        self.assertEqual(stats2['sent'], 0)
        self.assertGreaterEqual(stats2['skipped_paid'], 1)
        # Reminder table must NOT have an entry for inst2
        self.assertFalse(Reminder.objects.filter(instalment=inst2).exists())

    def test_duplicate_reminder_prevention(self):
        target_date = date(2026, 11, 4)
        # Instalment due in 3 days (offset -3, matching target_date = due_date - 3 => due_date = target_date + 3)
        due_date = target_date + date.resolution * 3
        inst = Instalment.objects.create(student=self.s1, sequence=2, amount=3000000, due_date=due_date)

        # First run: sends 1 reminder
        stats1 = process_daily_reminders(target_date)
        self.assertEqual(stats1['sent'], 1)

        # Second run on same day: should NOT send duplicate, must skip
        stats2 = process_daily_reminders(target_date)
        self.assertEqual(stats2['sent'], 0)
        self.assertEqual(stats2['skipped_duplicate'], 1)
        # Only 1 Reminder and 1 MessageLog record exists
        self.assertEqual(Reminder.objects.filter(instalment=inst, day_offset=-3).count(), 1)
