from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction

from accounts.models import Guardian, StaffProfile
from ledger.models import Centre, Batch, FeePlan, Student, Instalment, Payment, PaymentAllocation, Receipt, Discount
from ledger.services import generate_receipt_number, compute_gst_breakdown
from risk.models import Attendance, TestScore
from risk.services import scan_student_and_create_task


class Command(BaseCommand):
    help = 'Seeds initial sample data for CoachFee (Company A, Jaipur)'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Clearing previous seed data...")
        from risk.models import Attendance, TestScore, RiskFlag, CounsellorTask
        from reminders.models import Reminder, MessageLog
        from refunds.models import RefundRequest
        from payments.models import PaymentLink, GatewayEvent, UnmatchedPayment

        CounsellorTask.objects.all().delete()
        RiskFlag.objects.all().delete()
        Attendance.objects.all().delete()
        TestScore.objects.all().delete()
        Reminder.objects.all().delete()
        MessageLog.objects.all().delete()
        RefundRequest.objects.all().delete()
        PaymentLink.objects.all().delete()
        GatewayEvent.objects.all().delete()
        UnmatchedPayment.objects.all().delete()
        Receipt.objects.all().delete()
        PaymentAllocation.objects.all().delete()
        Payment.objects.all().delete()
        Discount.objects.all().delete()
        Instalment.objects.all().delete()
        Student.objects.all().delete()
        Batch.objects.all().delete()
        StaffProfile.objects.all().delete()
        Guardian.objects.all().delete()
        Centre.objects.all().delete()
        FeePlan.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()

        # 1. Staff users
        admin_user, _ = User.objects.get_or_create(username='admin', defaults={'first_name': 'Director', 'email': 'director@companya.in'})
        admin_user.set_password('admin123')
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.save()

        staff_user, _ = User.objects.get_or_create(username='staff', defaults={'first_name': 'Sunil Accounts', 'email': 'sunil@companya.in'})
        staff_user.set_password('staff123')
        staff_user.is_staff = True
        staff_user.save()

        # 2. 4 Centres in Jaipur
        centres_data = [
            ('Gopalpura Bypass Head Office', 'GPL', 'Plot 12, Gopalpura Bypass Road, Jaipur'),
            ('Vaishali Nagar Branch', 'VSH', 'Amrapali Circle, Vaishali Nagar, Jaipur'),
            ('Malviya Nagar Branch', 'MLV', 'Sector 3, Malviya Nagar, Jaipur'),
            ('Raja Park Branch', 'RJP', 'Near LBS College, Raja Park, Jaipur'),
        ]
        centres = {}
        for name, code, addr in centres_data:
            c = Centre.objects.create(name=name, code=code, address=addr)
            centres[code] = c

        StaffProfile.objects.create(user=staff_user, role='accounts_exec', centre=centres['GPL'])
        StaffProfile.objects.create(user=admin_user, role='admin', centre=centres['GPL'])

        # 3. Fee Plans (Average fee ₹1.2 lakh in 4 instalments of ₹30,000)
        # All stored in paise: ₹1,20,000 = 12000000 paise
        plan_jee = FeePlan.objects.create(
            name='JEE 2-Year Classroom Program',
            total_amount=12000000,
            registration_fee=500000,  # ₹5,000 non-refundable
            gst_rate=18,
            number_of_instalments=4,
        )

        plan_neet = FeePlan.objects.create(
            name='NEET 2-Year Classroom Program',
            total_amount=12000000,
            registration_fee=500000,
            gst_rate=18,
            number_of_instalments=3,
        )

        # 4. Batches
        batch_jee_morn = Batch.objects.create(
            centre=centres['GPL'],
            name='JEE 2027 Morning',
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        batch_jee_eve = Batch.objects.create(
            centre=centres['VSH'],
            name='JEE 2027 Evening',
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        batch_neet_morn = Batch.objects.create(
            centre=centres['MLV'],
            name='NEET 2027 Morning',
            start_date=date(2026, 5, 1),
            end_date=date(2027, 4, 30),
        )
        batch_neet_rjp = Batch.objects.create(
            centre=centres['RJP'],
            name='NEET 2027 Evening',
            start_date=date(2026, 5, 1),
            end_date=date(2027, 4, 30),
        )

        # Helper to create guardian
        def make_guardian(username, first_name, phone, lang='en'):
            u, _ = User.objects.get_or_create(username=username, defaults={'first_name': first_name})
            u.set_password('parent123')
            u.save()
            g, _ = Guardian.objects.get_or_create(
                user=u,
                phone=phone,
                defaults={'language': lang, 'consent_given': True, 'consent_version': 'DPDP-2023-V1'}
            )
            return g

        # ---------------------------------------------------------------
        # MANDATORY SAMPLE STUDENT 1:
        # STU-0412 Aarav Meena | JEE 2027 Morning | Due 2026-10-10 | ₹30,000 | Paid ₹30,000 | Paid
        # ---------------------------------------------------------------
        g1 = make_guardian('parent_aarav', 'Rajesh Meena', '9829012345', lang='hi')
        s1 = Student.objects.create(
            student_id='STU-0412',
            name='Aarav Meena',
            batch=batch_jee_morn,
            guardian=g1,
            fee_plan=plan_jee,
            enrollment_date=date(2026, 4, 1),
        )
        # 4 instalments of ₹30,000 (3,000,000 paise)
        inst1_1 = Instalment.objects.create(student=s1, sequence=1, amount=3000000, due_date=date(2026, 4, 10))
        inst1_2 = Instalment.objects.create(student=s1, sequence=2, amount=3000000, due_date=date(2026, 7, 10))
        inst1_3 = Instalment.objects.create(student=s1, sequence=3, amount=3000000, due_date=date(2026, 10, 10))
        inst1_4 = Instalment.objects.create(student=s1, sequence=4, amount=3000000, due_date=date(2027, 1, 10))

        # Pay inst 1, 2, and 3 (₹30,000 on 2026-10-10)
        p1_1 = Payment.objects.create(student=s1, amount=3000000, mode='gateway', gateway_ref='GW-AARAV-01')
        PaymentAllocation.objects.create(payment=p1_1, instalment=inst1_1, amount=3000000)
        base, gst, total = compute_gst_breakdown(3000000, 18)
        Receipt.objects.create(payment=p1_1, receipt_number=generate_receipt_number(p1_1.id), base_amount=base, gst_amount=gst, total_amount=total)

        p1_2 = Payment.objects.create(student=s1, amount=3000000, mode='gateway', gateway_ref='GW-AARAV-02')
        PaymentAllocation.objects.create(payment=p1_2, instalment=inst1_2, amount=3000000)
        base, gst, total = compute_gst_breakdown(3000000, 18)
        Receipt.objects.create(payment=p1_2, receipt_number=generate_receipt_number(p1_2.id), base_amount=base, gst_amount=gst, total_amount=total)

        p1_3 = Payment.objects.create(student=s1, amount=3000000, mode='gateway', gateway_ref='GW-AARAV-03')
        PaymentAllocation.objects.create(payment=p1_3, instalment=inst1_3, amount=3000000)
        base, gst, total = compute_gst_breakdown(3000000, 18)
        Receipt.objects.create(payment=p1_3, receipt_number=generate_receipt_number(p1_3.id), base_amount=base, gst_amount=gst, total_amount=total)

        # ---------------------------------------------------------------
        # MANDATORY SAMPLE STUDENT 2:
        # STU-0587 Ishita Sharma | JEE 2027 Evening | Due 2026-10-10 | ₹30,000 | Paid ₹15,000 | Part paid, 23 days overdue
        # (Assuming current date ~ 2026-11-02 to 2026-11-04)
        # ---------------------------------------------------------------
        g2 = make_guardian('parent_ishita', 'Dr. Ramesh Sharma', '9829023456', lang='en')
        s2 = Student.objects.create(
            student_id='STU-0587',
            name='Ishita Sharma',
            batch=batch_jee_eve,
            guardian=g2,
            fee_plan=plan_jee,
            enrollment_date=date(2026, 4, 1),
        )
        inst2_1 = Instalment.objects.create(student=s2, sequence=1, amount=3000000, due_date=date(2026, 4, 10))
        inst2_2 = Instalment.objects.create(student=s2, sequence=2, amount=3000000, due_date=date(2026, 7, 10))
        inst2_3 = Instalment.objects.create(student=s2, sequence=3, amount=3000000, due_date=date(2026, 10, 10))
        inst2_4 = Instalment.objects.create(student=s2, sequence=4, amount=3000000, due_date=date(2027, 1, 10))

        # First two instalments paid in full
        p2_1 = Payment.objects.create(student=s2, amount=3000000, mode='bank', gateway_ref='NEFT-ISHITA-01')
        PaymentAllocation.objects.create(payment=p2_1, instalment=inst2_1, amount=3000000)
        base, gst, total = compute_gst_breakdown(3000000, 18)
        Receipt.objects.create(payment=p2_1, receipt_number=generate_receipt_number(p2_1.id), base_amount=base, gst_amount=gst, total_amount=total)

        p2_2 = Payment.objects.create(student=s2, amount=3000000, mode='gateway', gateway_ref='GW-ISHITA-02')
        PaymentAllocation.objects.create(payment=p2_2, instalment=inst2_2, amount=3000000)
        base, gst, total = compute_gst_breakdown(3000000, 18)
        Receipt.objects.create(payment=p2_2, receipt_number=generate_receipt_number(p2_2.id), base_amount=base, gst_amount=gst, total_amount=total)

        # Instalment 3: Only ₹15,000 paid out of ₹30,000 (1,500,000 paise), leaving ₹15,000 overdue
        p2_3 = Payment.objects.create(student=s2, amount=1500000, mode='gateway', gateway_ref='GW-ISHITA-03')
        PaymentAllocation.objects.create(payment=p2_3, instalment=inst2_3, amount=1500000)
        base, gst, total = compute_gst_breakdown(1500000, 18)
        Receipt.objects.create(payment=p2_3, receipt_number=generate_receipt_number(p2_3.id), base_amount=base, gst_amount=gst, total_amount=total)

        # ---------------------------------------------------------------
        # MANDATORY SAMPLE STUDENT 3:
        # STU-0219 Mohit Gurjar | NEET 2027 Morning | Due 2026-11-15 | ₹40,000 | Paid ₹0 | Due in 11 days (as of 2026-11-04)
        # ---------------------------------------------------------------
        g3 = make_guardian('parent_mohit', 'Surendra Gurjar', '9829034567', lang='hi')
        s3 = Student.objects.create(
            student_id='STU-0219',
            name='Mohit Gurjar',
            batch=batch_neet_morn,
            guardian=g3,
            fee_plan=plan_neet,
            enrollment_date=date(2026, 5, 1),
        )
        inst3_1 = Instalment.objects.create(student=s3, sequence=1, amount=4000000, due_date=date(2026, 5, 10))
        inst3_2 = Instalment.objects.create(student=s3, sequence=2, amount=4000000, due_date=date(2026, 11, 15))
        inst3_3 = Instalment.objects.create(student=s3, sequence=3, amount=4000000, due_date=date(2027, 3, 15))

        # First instalment paid
        p3_1 = Payment.objects.create(student=s3, amount=4000000, mode='cash', gateway_ref='CASH-MOHIT-01')
        PaymentAllocation.objects.create(payment=p3_1, instalment=inst3_1, amount=4000000)
        base, gst, total = compute_gst_breakdown(4000000, 18)
        Receipt.objects.create(payment=p3_1, receipt_number=generate_receipt_number(p3_1.id), base_amount=base, gst_amount=gst, total_amount=total)

        # Additional Realistic Students across centres
        # Student 4: High Dropout Risk Demo Student (falling attendance, declining scores, overdue)
        g4 = make_guardian('parent_rohit', 'Vikram Choudhary', '9829045678', lang='en')
        s4 = Student.objects.create(
            student_id='STU-0891',
            name='Rohit Choudhary',
            batch=batch_neet_rjp,
            guardian=g4,
            fee_plan=plan_neet,
            enrollment_date=date(2026, 5, 1),
        )
        inst4_1 = Instalment.objects.create(student=s4, sequence=1, amount=4000000, due_date=date(2026, 5, 10))
        inst4_2 = Instalment.objects.create(student=s4, sequence=2, amount=4000000, due_date=date(2026, 9, 10))  # 55 days overdue
        inst4_3 = Instalment.objects.create(student=s4, sequence=3, amount=4000000, due_date=date(2027, 1, 10))
        p4_1 = Payment.objects.create(student=s4, amount=4000000, mode='gateway', gateway_ref='GW-ROHIT-01')
        PaymentAllocation.objects.create(payment=p4_1, instalment=inst4_1, amount=4000000)

        # Seed attendance for Rohit (declining from 90% down to 30%)
        today = date(2026, 11, 4)
        for i in range(28):
            d = today - timedelta(days=i)
            # Recent 14 days mostly absent
            present = (i % 4 == 0) if i < 14 else (i % 5 != 0)
            Attendance.objects.create(student=s4, date=d, present=present)

        # Seed test scores for Rohit (falling from 82% to 35%)
        TestScore.objects.create(student=s4, test_name='Minor Test 1', date=date(2026, 8, 15), score=164, max_score=200)
        TestScore.objects.create(student=s4, test_name='Minor Test 2', date=date(2026, 9, 20), score=140, max_score=200)
        TestScore.objects.create(student=s4, test_name='Major Test 1', date=date(2026, 10, 25), score=70, max_score=200)

        # Seed attendance & test scores for Ishita (STU-0587)
        for i in range(25):
            d = today - timedelta(days=i)
            Attendance.objects.create(student=s2, date=d, present=(i % 7 != 0))
        TestScore.objects.create(student=s2, test_name='Physics Weekly #1', date=date(2026, 10, 5), score=88, max_score=100)
        TestScore.objects.create(student=s2, test_name='Chemistry Weekly #1', date=date(2026, 10, 18), score=79, max_score=100)
        TestScore.objects.create(student=s2, test_name='Maths Cumulative', date=date(2026, 10, 29), score=84, max_score=100)

        # Seed attendance for Aarav (STU-0412)
        for i in range(25):
            d = today - timedelta(days=i)
            Attendance.objects.create(student=s1, date=d, present=True)
        TestScore.objects.create(student=s1, test_name='JEE Mock #1', date=date(2026, 9, 10), score=245, max_score=300)
        TestScore.objects.create(student=s1, test_name='JEE Mock #2', date=date(2026, 10, 15), score=260, max_score=300)

        # Trigger initial risk scan for high-risk Rohit
        scan_student_and_create_task(s4, as_of_date=today)

        self.stdout.write(self.style.SUCCESS("Successfully seeded CoachFee with realistic data:"))
        self.stdout.write(f"- STU-0412 Aarav Meena (JEE 2027 Morning): Paid")
        self.stdout.write(f"- STU-0587 Ishita Sharma (JEE 2027 Evening): Part paid, 23 days overdue")
        self.stdout.write(f"- STU-0219 Mohit Gurjar (NEET 2027 Morning): Due in 11 days (2026-11-15)")
        self.stdout.write(f"- STU-0891 Rohit Choudhary (NEET 2027 Evening): High Risk flag + Counsellor Task generated")
        self.stdout.write(f"- Staff user: staff / staff123")
        self.stdout.write(f"- Parent phone: 9829012345 (Aarav), 9829023456 (Ishita)")
