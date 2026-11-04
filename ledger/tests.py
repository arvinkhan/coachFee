from datetime import date, timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User

from accounts.models import Guardian, StaffProfile
from ledger.models import Centre, Batch, FeePlan, Student, Instalment, Payment, PaymentAllocation, Discount
from ledger.services import (
    compute_instalment_status,
    allocate_payment,
    compute_student_ledger,
    compute_ageing_buckets,
    compute_gst_breakdown
)


class LedgerFinancialCalculationsTest(TestCase):
    """Unit tests for financial calculations using integer paise."""

    def test_gst_breakdown_inclusive(self):
        # 18% GST on ₹30,000 (3,000,000 paise)
        base, gst, total = compute_gst_breakdown(3000000, 18)
        self.assertEqual(total, 3000000)
        self.assertEqual(base + gst, 3000000)
        # base ~ 2542372, gst ~ 457628
        self.assertAlmostEqual(base, 2542372, delta=2)

    def test_instalment_status_and_overdue(self):
        today = date(2026, 11, 4)
        due_past = date(2026, 10, 10)  # 25 days ago
        due_future = date(2026, 11, 15)  # 11 days ahead

        # Fully paid
        status, bal, days = compute_instalment_status(3000000, 3000000, due_past, today=today)
        self.assertEqual(status, 'paid')
        self.assertEqual(bal, 0)
        self.assertEqual(days, 0)

        # Partially paid and overdue
        status, bal, days = compute_instalment_status(3000000, 1500000, due_past, today=today)
        self.assertEqual(status, 'partial')
        self.assertEqual(bal, 1500000)
        self.assertEqual(days, 25)

        # Unpaid and overdue
        status, bal, days = compute_instalment_status(3000000, 0, due_past, today=today)
        self.assertEqual(status, 'overdue')
        self.assertEqual(bal, 3000000)
        self.assertEqual(days, 25)

        # Upcoming
        status, bal, days = compute_instalment_status(4000000, 0, due_future, today=today)
        self.assertEqual(status, 'upcoming')
        self.assertEqual(bal, 4000000)
        self.assertEqual(days, 0)

    def test_partial_payment_allocation_oldest_first(self):
        # Two instalments: Inst 1 balance 30,000, Inst 2 balance 30,000
        inst_balances = [(1, 3000000), (2, 3000000)]
        
        # Payment of ₹15,000 (1,500,000 paise)
        allocations, remaining = allocate_payment(1500000, inst_balances)
        self.assertEqual(allocations, [(1, 1500000)])
        self.assertEqual(remaining, 0)

    def test_multiple_instalment_allocation(self):
        # Payment of ₹45,000 should completely pay Inst 1 (30k) and partially pay Inst 2 (15k)
        inst_balances = [(1, 3000000), (2, 3000000)]
        allocations, remaining = allocate_payment(4500000, inst_balances)
        self.assertEqual(allocations, [(1, 3000000), (2, 1500000)])
        self.assertEqual(remaining, 0)

    def test_overpayment_handling(self):
        # Payment of ₹70,000 when only ₹60,000 total dues exist
        inst_balances = [(1, 3000000), (2, 3000000)]
        allocations, remaining = allocate_payment(7000000, inst_balances)
        self.assertEqual(allocations, [(1, 3000000), (2, 3000000)])
        self.assertEqual(remaining, 1000000)  # ₹10,000 leftover

    def test_discounts_and_balance_derivation(self):
        inst_data = [
            {'id': 1, 'sequence': 1, 'amount': 3000000, 'allocated': 3000000, 'due_date': date(2026, 4, 1)},
            {'id': 2, 'sequence': 2, 'amount': 3000000, 'allocated': 0, 'due_date': date(2026, 7, 1)},
        ]
        payments_data = [{'amount': 3000000}]
        discount_paise = 1000000  # ₹10,000 discount

        ledger = compute_student_ledger(inst_data, payments_data, discount_paise)
        # Total fee 60,000 - 30,000 paid - 10,000 discount = 20,000 balance
        self.assertEqual(ledger['total_balance'], 2000000)
        self.assertEqual(ledger['total_discount'], 1000000)

    def test_ageing_buckets(self):
        today = date(2026, 11, 4)
        overdue_items = [
            (date(2026, 10, 20), 1000000),  # 15 days overdue -> bucket 0-30
            (date(2026, 9, 20), 2000000),   # 45 days overdue -> bucket 31-60
            (date(2026, 8, 1), 3000000),    # 95 days overdue -> bucket over 60
        ]
        buckets = compute_ageing_buckets(overdue_items, today=today)
        self.assertEqual(buckets['bucket_0_30'], 1000000)
        self.assertEqual(buckets['bucket_31_60'], 2000000)
        self.assertEqual(buckets['bucket_over_60'], 3000000)


class AccessControlPermissionsTest(TestCase):
    """Test object-level permissions: parents only access own children, staff scoped to centre."""

    def setUp(self):
        self.c1 = Centre.objects.create(name='Gopalpura', code='GPL')
        self.c2 = Centre.objects.create(name='Vaishali', code='VSH')
        self.plan = FeePlan.objects.create(name='Test Plan', total_amount=12000000, registration_fee=500000, gst_rate=18)
        self.b1 = Batch.objects.create(centre=self.c1, name='B1', start_date=date(2026, 4, 1), end_date=date(2027, 3, 31))
        self.b2 = Batch.objects.create(centre=self.c2, name='B2', start_date=date(2026, 4, 1), end_date=date(2027, 3, 31))

        # Parent 1
        self.u_parent1 = User.objects.create_user(username='parent1', password='pass')
        self.g1 = Guardian.objects.create(user=self.u_parent1, phone='9999900001')
        self.s1 = Student.objects.create(student_id='STU-001', name='Child 1', batch=self.b1, guardian=self.g1, fee_plan=self.plan, enrollment_date=date(2026, 4, 1))

        # Parent 2
        self.u_parent2 = User.objects.create_user(username='parent2', password='pass')
        self.g2 = Guardian.objects.create(user=self.u_parent2, phone='9999900002')
        self.s2 = Student.objects.create(student_id='STU-002', name='Child 2', batch=self.b2, guardian=self.g2, fee_plan=self.plan, enrollment_date=date(2026, 4, 1))

        # Staff scoped to Centre 1
        self.u_staff = User.objects.create_user(username='exec_gpl', password='pass')
        self.staff_profile = StaffProfile.objects.create(user=self.u_staff, role='accounts_exec', centre=self.c1)

    def test_parent_cannot_access_other_parent_student_ledger(self):
        client = Client()
        client.login(username='parent1', password='pass')

        # Parent 1 accesses dashboard -> OK (200)
        res_dash = client.get('/parent/')
        self.assertEqual(res_dash.status_code, 200)
        
        # Parent 1 accesses own child -> OK (200)
        res_own = client.get(f'/students/{self.s1.student_id}/')
        self.assertEqual(res_own.status_code, 200)

        # Parent 1 tries to access Parent 2's child -> 404 Not Found (restricted by guardian=guardian)
        res_other = client.get(f'/students/{self.s2.student_id}/')
        self.assertEqual(res_other.status_code, 404)

    def test_centre_staff_cannot_view_other_centre_student(self):
        client = Client()
        client.login(username='exec_gpl', password='pass')

        # Staff at Centre 1 views student at Centre 1 -> OK (200)
        res_c1 = client.get(f'/students/{self.s1.student_id}/')
        self.assertEqual(res_c1.status_code, 200)

        # Staff at Centre 1 tries to view student at Centre 2 -> 403 Forbidden
        res_c2 = client.get(f'/students/{self.s2.student_id}/')
        self.assertEqual(res_c2.status_code, 403)
