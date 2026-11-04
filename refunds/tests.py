from datetime import date, timedelta
from django.test import TestCase
from django.contrib.auth.models import User

from accounts.models import Guardian
from ledger.models import Centre, Batch, FeePlan, Student, Instalment, Payment, PaymentAllocation
from refunds.services import calculate_refund


class ProRataRefundPolicyTest(TestCase):
    """Unit tests for pro-rata refund calculations and edge cases."""

    def setUp(self):
        self.centre = Centre.objects.create(name='Jaipur Central', code='JPR')
        # Total fee ₹1,20,000; reg fee ₹5,000; course 100 days
        self.plan = FeePlan.objects.create(
            name='Standard Plan',
            total_amount=12000000,
            registration_fee=500000,
            gst_rate=18,
            number_of_instalments=4
        )
        self.batch = Batch.objects.create(
            centre=self.centre,
            name='Batch 100 Days',
            start_date=date(2026, 4, 1),
            end_date=date(2026, 7, 10),  # 100 days
        )
        self.user = User.objects.create_user(username='guardian_ref', password='password')
        self.guardian = Guardian.objects.create(user=self.user, phone='9829011111')
        self.student = Student.objects.create(
            student_id='STU-REFUND',
            name='Leaving Student',
            batch=self.batch,
            guardian=self.guardian,
            fee_plan=self.plan,
            enrollment_date=date(2026, 4, 1)
        )

        # Student paid ₹60,000 (6,000,000 paise)
        p = Payment.objects.create(student=self.student, amount=6000000, mode='bank')

    def test_pro_rata_refund_at_20_days_attended(self):
        # Leave date is 20 days after start date
        leave_date = date(2026, 4, 21)
        res = calculate_refund(self.student.student_id, leave_date)

        # Total days: 100
        # Days attended: 20
        # Paid: ₹60,000 (6,000,000 paise)
        # Reg fee: ₹5,000 (500,000 paise)
        # Tuition: ₹1,15,000 (11,500,000 paise)
        # Pro rata tuition used: 20/100 * 11,500,000 = 2,300,000 paise (₹23,000)
        # Total deduction: ₹5,000 + ₹23,000 = ₹28,000 (2,800,000 paise)
        # Expected refund: ₹60,000 - ₹28,000 = ₹32,000 (3,200,000 paise)
        self.assertEqual(res['days_attended'], 20)
        self.assertEqual(res['registration_fee_paise'], 500000)
        self.assertEqual(res['pro_rata_usage_paise'], 2300000)
        self.assertEqual(res['refund_amount_paise'], 3200000)
        self.assertEqual(res['refund_amount_display'], 32000.0)

        # Deadline is 10 days after leave date
        expected_due = (leave_date + timedelta(days=10)).isoformat()
        self.assertEqual(res['due_by'], expected_due)

    def test_leaving_before_batch_start_date(self):
        # Leaves before classes begin -> 0 days attended, only reg fee deducted
        leave_date = date(2026, 3, 25)
        res = calculate_refund(self.student.student_id, leave_date)
        self.assertEqual(res['days_attended'], 0)
        self.assertEqual(res['pro_rata_usage_paise'], 0)
        # Refund = 60,000 - 5,000 = 55,000
        self.assertEqual(res['refund_amount_paise'], 5500000)

    def test_leaving_after_course_completion_floored_at_zero(self):
        # Leaves after batch end date -> 100% attended, deduction exceeds amount paid
        leave_date = date(2026, 8, 1)
        res = calculate_refund(self.student.student_id, leave_date)
        self.assertEqual(res['refund_amount_paise'], 0)
        self.assertEqual(res['refund_amount_display'], 0.0)
