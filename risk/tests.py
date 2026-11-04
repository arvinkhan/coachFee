from datetime import date, timedelta
from django.test import TestCase
from django.contrib.auth.models import User

from accounts.models import Guardian
from ledger.models import Centre, Batch, FeePlan, Student, Instalment, Payment, PaymentAllocation
from risk.models import RiskFlag, CounsellorTask, Attendance, TestScore
from risk.services import evaluate_student_risk, scan_student_and_create_task


class RiskEngineAndSafetyTest(TestCase):
    """Automated tests for transparent risk scoring, task creation and safety constraints."""

    def setUp(self):
        self.centre = Centre.objects.create(name='Jaipur', code='JPR')
        self.plan = FeePlan.objects.create(name='Plan', total_amount=12000000, registration_fee=500000, gst_rate=18)
        self.batch = Batch.objects.create(centre=self.centre, name='Batch 1', start_date=date(2026, 4, 1), end_date=date(2027, 3, 31))
        
        self.user = User.objects.create_user(username='guardian_risk', password='password')
        self.guardian = Guardian.objects.create(user=self.user, phone='9829077777')
        self.student = Student.objects.create(
            student_id='STU-RISK-TEST',
            name='At Risk Student',
            batch=self.batch,
            guardian=self.guardian,
            fee_plan=self.plan,
            enrollment_date=date(2026, 4, 1)
        )

    def test_insufficient_data_handles_gracefully(self):
        # Fresh student with no attendance or test records
        today = date(2026, 11, 4)
        score, reasons = evaluate_student_risk(self.student, as_of_date=today)
        self.assertEqual(score, 0)
        self.assertTrue(reasons['attendance'].get('insufficient_data'))
        self.assertTrue(reasons['academics'].get('insufficient_data'))

    def test_high_risk_scoring_and_task_generation(self):
        today = date(2026, 11, 4)
        # 1. Overdue instalment > 45 days (40 pts)
        Instalment.objects.create(student=self.student, sequence=1, amount=3000000, due_date=date(2026, 9, 1))

        # 2. Dropping attendance (<50% in recent period) (30 pts)
        for i in range(14):
            # recent: absent 10 days, present 4 days
            Attendance.objects.create(student=self.student, date=today - timedelta(days=i), present=(i % 3 == 0))
        for i in range(14, 28):
            # prior: present all days
            Attendance.objects.create(student=self.student, date=today - timedelta(days=i), present=True)

        # 3. Falling test scores: latest 35%, prior 80% (30 pts)
        TestScore.objects.create(student=self.student, test_name='Test A', date=date(2026, 9, 15), score=80, max_score=100)
        TestScore.objects.create(student=self.student, test_name='Test B', date=date(2026, 10, 20), score=35, max_score=100)

        score, reasons = evaluate_student_risk(self.student, as_of_date=today)
        # Should be maximum risk score: 40 + 30 + 30 = 100
        self.assertGreaterEqual(score, 80)
        self.assertIn('instalments', reasons)
        self.assertIn('attendance', reasons)
        self.assertIn('academics', reasons)

        # Trigger scan and verify CounsellorTask created
        flag, task = scan_student_and_create_task(self.student, threshold=60, as_of_date=today)
        self.assertIsNotNone(flag)
        self.assertIsNotNone(task)
        self.assertEqual(task.status, 'open')
        self.assertEqual(flag.score, score)

    def test_false_positive_suppression(self):
        today = date(2026, 11, 4)
        # Create an overdue instalment to push score over threshold
        Instalment.objects.create(student=self.student, sequence=1, amount=3000000, due_date=date(2026, 9, 1))
        for i in range(14):
            Attendance.objects.create(student=self.student, date=today - timedelta(days=i), present=False)
        for i in range(14, 28):
            Attendance.objects.create(student=self.student, date=today - timedelta(days=i), present=True)

        flag, task = scan_student_and_create_task(self.student, threshold=50, as_of_date=today)
        self.assertIsNotNone(flag)

        # Counsellor marks it as a false positive
        flag.status = 'false_flag'
        flag.save()

        # Rescanning must now be suppressed by 30-day rule
        new_flag, new_task = scan_student_and_create_task(self.student, threshold=50, as_of_date=today)
        self.assertIsNone(new_flag)
        self.assertIsNone(new_task)
