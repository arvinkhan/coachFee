from datetime import date, timedelta
import random
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction

from accounts.models import Guardian, StaffProfile, StudentProfile
from ledger.models import Centre, Batch, FeePlan, Student, Instalment, Payment, PaymentAllocation, Receipt, Discount
from ledger.services import generate_receipt_number, compute_gst_breakdown
from risk.models import Attendance, TestScore
from risk.services import scan_student_and_create_task


class Command(BaseCommand):
    help = 'Seeds initial sample data with 50 students across 4 centres for CoachFee (Company A, Jaipur)'

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
        StudentProfile.objects.all().delete()
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

        # Head office admin staff can view all centres
        StaffProfile.objects.create(user=staff_user, role='admin', centre=centres['GPL'])
        StaffProfile.objects.create(user=admin_user, role='admin', centre=centres['GPL'])

        # Dedicated single-centre accounts executive to test centre scoping
        exec_gpl, _ = User.objects.get_or_create(username='exec_gpl', defaults={'first_name': 'Ramesh Accounts', 'email': 'ramesh@companya.in'})
        exec_gpl.set_password('staff123')
        exec_gpl.is_staff = True
        exec_gpl.save()
        StaffProfile.objects.create(user=exec_gpl, role='accounts_exec', centre=centres['GPL'])

        # 3. Fee Plans (Average fee ₹1.2 lakh)
        # All stored in paise: ₹1,20,000 = 12,000,000 paise
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

        # 4. Batches across 4 centres
        batches = {
            'GPL': Batch.objects.create(
                centre=centres['GPL'],
                name='JEE 2027 Morning',
                start_date=date(2026, 4, 1),
                end_date=date(2027, 3, 31),
            ),
            'VSH': Batch.objects.create(
                centre=centres['VSH'],
                name='JEE 2027 Evening',
                start_date=date(2026, 4, 1),
                end_date=date(2027, 3, 31),
            ),
            'MLV': Batch.objects.create(
                centre=centres['MLV'],
                name='NEET 2027 Morning',
                start_date=date(2026, 5, 1),
                end_date=date(2027, 4, 30),
            ),
            'RJP': Batch.objects.create(
                centre=centres['RJP'],
                name='NEET 2027 Evening',
                start_date=date(2026, 5, 1),
                end_date=date(2027, 4, 30),
            ),
        }

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

        # Helper to create student login
        def make_student_user(student, password='student123'):
            username = f"stu_{student.student_id.lower().replace('-', '_')}"
            u, _ = User.objects.get_or_create(username=username, defaults={'first_name': student.name})
            u.set_password(password)
            u.save()
            sp, _ = StudentProfile.objects.get_or_create(user=u, student=student)
            return sp

        # Helper to record a payment
        def record_payment(student, instalment, amount_paise, mode='gateway', ref=None):
            if not ref:
                ref = f"PAY-{student.student_id}-{instalment.sequence}"
            p = Payment.objects.create(student=student, amount=amount_paise, mode=mode, gateway_ref=ref)
            PaymentAllocation.objects.create(payment=p, instalment=instalment, amount=amount_paise)
            base, gst, total = compute_gst_breakdown(amount_paise, 18)
            Receipt.objects.create(
                payment=p,
                receipt_number=generate_receipt_number(p.id),
                base_amount=base,
                gst_amount=gst,
                total_amount=total
            )
            return p

        # Helper to seed attendance and test scores
        def seed_academics(student, attendance_pct=0.90, test_trend='stable'):
            today = date(2026, 11, 4)
            # Seed 20 attendance records
            for i in range(20):
                d = today - timedelta(days=i + 1)
                present = (random.random() < attendance_pct)
                Attendance.objects.create(student=student, date=d, present=present)

            # Seed 3 test scores
            if test_trend == 'improving':
                scores = [70, 82, 91]
            elif test_trend == 'declining':
                scores = [85, 62, 41]
            else:
                scores = [75, 78, 80]

            for idx, sc in enumerate(scores):
                TestScore.objects.create(
                    student=student,
                    test_name=f"Periodic Test {idx + 1}",
                    date=today - timedelta(days=50 - (idx * 18)),
                    score=sc,
                    max_score=100
                )

        # -------------------------------------------------------------------
        # 50 STUDENTS DEFINITION (Distributed across 4 centres/batches)
        # -------------------------------------------------------------------
        # Mandatory 4 students specified in brief:
        # 1. STU-0412 Aarav Meena: Paid (JEE 2027 Morning, GPL)
        # 2. STU-0587 Ishita Sharma: Part-paid, 23d overdue (JEE 2027 Evening, VSH)
        # 3. STU-0219 Mohit Gurjar: Due in 11 days (NEET 2027 Morning, MLV)
        # 4. STU-0891 Rohit Choudhary: High Risk, 55d overdue (NEET 2027 Evening, RJP)

        students_spec = [
            # ----------------- Centre 1: Gopalpura Bypass (GPL - JEE Morning) : 12 students -----------------
            {
                'id': 'STU-0412', 'name': 'Aarav Meena', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Rajesh Meena', 'phone': '9829012345', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_3', 'att_pct': 0.95, 'trend': 'improving',
            },
            {
                'id': 'STU-0413', 'name': 'Tanvi Agarwal', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Alok Agarwal', 'phone': '9829056789', 'enrolled': date(2026, 4, 1),
                'status': 'part_paid_inst2', 'att_pct': 0.88, 'trend': 'stable',
            },
            {
                'id': 'STU-0414', 'name': 'Harsh Vardhan', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Dharmendra Singh', 'phone': '9829067890', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.92, 'trend': 'improving',
            },
            {
                'id': 'STU-0415', 'name': 'Aditya Sharma', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Mukesh Sharma', 'phone': '9829010015', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_3', 'att_pct': 0.96, 'trend': 'stable',
            },
            {
                'id': 'STU-0416', 'name': 'Kavya Jain', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Naveen Jain', 'phone': '9829010016', 'enrolled': date(2026, 4, 1),
                'status': 'overdue_inst3', 'att_pct': 0.85, 'trend': 'stable',
            },
            {
                'id': 'STU-0417', 'name': 'Dev Saini', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Kailash Saini', 'phone': '9829010017', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.90, 'trend': 'improving',
            },
            {
                'id': 'STU-0418', 'name': 'Ananya Mathur', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Sudhir Mathur', 'phone': '9829010018', 'enrolled': date(2026, 4, 1),
                'status': 'part_paid_inst3', 'att_pct': 0.89, 'trend': 'stable',
            },
            {
                'id': 'STU-0419', 'name': 'Varun Shekhawat', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Bhawani Singh Shekhawat', 'phone': '9829010019', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_3', 'att_pct': 0.94, 'trend': 'improving',
            },
            {
                'id': 'STU-0420', 'name': 'Pooja Khandelwal', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Radhe Shyam Khandelwal', 'phone': '9829010020', 'enrolled': date(2026, 4, 1),
                'status': 'overdue_inst3', 'att_pct': 0.86, 'trend': 'stable',
            },
            {
                'id': 'STU-0421', 'name': 'Ayush Gupta', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Sanjay Gupta', 'phone': '9829010021', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_3', 'att_pct': 0.93, 'trend': 'improving',
            },
            {
                'id': 'STU-0422', 'name': 'Sneha Verma', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Govind Verma', 'phone': '9829010022', 'enrolled': date(2026, 4, 1),
                'status': 'part_paid_inst3', 'att_pct': 0.87, 'trend': 'stable',
            },
            {
                'id': 'STU-0423', 'name': 'Rohan Yadav', 'centre': 'GPL', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Om Prakash Yadav', 'phone': '9829010023', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.91, 'trend': 'stable',
            },

            # ----------------- Centre 2: Vaishali Nagar (VSH - JEE Evening) : 12 students -----------------
            {
                'id': 'STU-0587', 'name': 'Ishita Sharma', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Dr. Ramesh Sharma', 'phone': '9829023456', 'enrolled': date(2026, 4, 1),
                'status': 'part_paid_23d_overdue', 'att_pct': 0.90, 'trend': 'stable',
            },
            {
                'id': 'STU-0588', 'name': 'Priyansh Jain', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Manish Jain', 'phone': '9829078901', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_1', 'att_pct': 0.85, 'trend': 'declining',
            },
            {
                'id': 'STU-0589', 'name': 'Divya Rathore', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Pratap Singh Rathore', 'phone': '9829020025', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_3', 'att_pct': 0.95, 'trend': 'improving',
            },
            {
                'id': 'STU-0590', 'name': 'Kunal Joshi', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Anil Joshi', 'phone': '9829020026', 'enrolled': date(2026, 4, 1),
                'status': 'overdue_inst3', 'att_pct': 0.88, 'trend': 'stable',
            },
            {
                'id': 'STU-0591', 'name': 'Meera Agarwal', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Pawan Agarwal', 'phone': '9829020027', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_3', 'att_pct': 0.97, 'trend': 'improving',
            },
            {
                'id': 'STU-0592', 'name': 'Abhishek Meena', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Gopi Chand Meena', 'phone': '9829020028', 'enrolled': date(2026, 4, 1),
                'status': 'part_paid_inst3', 'att_pct': 0.84, 'trend': 'stable',
            },
            {
                'id': 'STU-0593', 'name': 'Simran Kaur', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Harjeet Singh', 'phone': '9829020029', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.93, 'trend': 'improving',
            },
            {
                'id': 'STU-0594', 'name': 'Chirag Saini', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Rakesh Saini', 'phone': '9829020030', 'enrolled': date(2026, 4, 1),
                'status': 'overdue_inst3', 'att_pct': 0.83, 'trend': 'stable',
            },
            {
                'id': 'STU-0595', 'name': 'Neha Mathur', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Vinod Mathur', 'phone': '9829020031', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_3', 'att_pct': 0.95, 'trend': 'stable',
            },
            {
                'id': 'STU-0596', 'name': 'Sahil Gurjar', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Ramphool Gurjar', 'phone': '9829020032', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.91, 'trend': 'improving',
            },
            {
                'id': 'STU-0597', 'name': 'Khushi Verma', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'hi',
                'parent_name': 'Mahesh Verma', 'phone': '9829020033', 'enrolled': date(2026, 4, 1),
                'status': 'part_paid_inst3', 'att_pct': 0.87, 'trend': 'stable',
            },
            {
                'id': 'STU-0598', 'name': 'Yash Shekhawat', 'centre': 'VSH', 'plan': plan_jee, 'lang': 'en',
                'parent_name': 'Surinder Shekhawat', 'phone': '9829020034', 'enrolled': date(2026, 4, 1),
                'status': 'fully_paid_up_to_3', 'att_pct': 0.96, 'trend': 'improving',
            },

            # ----------------- Centre 3: Malviya Nagar (MLV - NEET Morning) : 13 students -----------------
            {
                'id': 'STU-0219', 'name': 'Mohit Gurjar', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Surendra Gurjar', 'phone': '9829034567', 'enrolled': date(2026, 5, 1),
                'status': 'due_in_11_days', 'att_pct': 0.92, 'trend': 'improving',
            },
            {
                'id': 'STU-0220', 'name': 'Riya Rathore', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Colonel Rajendra Rathore', 'phone': '9829089012', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_1', 'att_pct': 0.94, 'trend': 'improving',
            },
            {
                'id': 'STU-0221', 'name': 'Bhavna Sharma', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Gopal Sharma', 'phone': '9829030037', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.96, 'trend': 'improving',
            },
            {
                'id': 'STU-0222', 'name': 'Aman Gupta', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'en',
                'parent_name': 'Vivek Gupta', 'phone': '9829030038', 'enrolled': date(2026, 5, 1),
                'status': 'part_paid_inst2', 'att_pct': 0.88, 'trend': 'stable',
            },
            {
                'id': 'STU-0223', 'name': 'Garima Jain', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Ajit Jain', 'phone': '9829030039', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.95, 'trend': 'improving',
            },
            {
                'id': 'STU-0224', 'name': 'Lakshay Yadav', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'en',
                'parent_name': 'Dinesh Yadav', 'phone': '9829030040', 'enrolled': date(2026, 5, 1),
                'status': 'overdue_inst2', 'att_pct': 0.81, 'trend': 'declining',
            },
            {
                'id': 'STU-0225', 'name': 'Swati Meena', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Babulal Meena', 'phone': '9829030041', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_1', 'att_pct': 0.91, 'trend': 'stable',
            },
            {
                'id': 'STU-0226', 'name': 'Parth Khandelwal', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'en',
                'parent_name': 'Ashok Khandelwal', 'phone': '9829030042', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.97, 'trend': 'improving',
            },
            {
                'id': 'STU-0227', 'name': 'Komal Choudhary', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Ramniwas Choudhary', 'phone': '9829030043', 'enrolled': date(2026, 5, 1),
                'status': 'part_paid_inst2', 'att_pct': 0.86, 'trend': 'stable',
            },
            {
                'id': 'STU-0228', 'name': 'Shivam Saini', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Jagdish Saini', 'phone': '9829030044', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.93, 'trend': 'improving',
            },
            {
                'id': 'STU-0229', 'name': 'Shreya Mathur', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'en',
                'parent_name': 'Hemant Mathur', 'phone': '9829030045', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_1', 'att_pct': 0.89, 'trend': 'stable',
            },
            {
                'id': 'STU-0230', 'name': 'Mayank Joshi', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'en',
                'parent_name': 'Chandra Mohan Joshi', 'phone': '9829030046', 'enrolled': date(2026, 5, 1),
                'status': 'overdue_inst2', 'att_pct': 0.82, 'trend': 'declining',
            },
            {
                'id': 'STU-0231', 'name': 'Surbhi Agarwal', 'centre': 'MLV', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Satish Agarwal', 'phone': '9829030047', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.95, 'trend': 'improving',
            },

            # ----------------- Centre 4: Raja Park (RJP - NEET Evening) : 13 students -----------------
            {
                'id': 'STU-0891', 'name': 'Rohit Choudhary', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'en',
                'parent_name': 'Vikram Choudhary', 'phone': '9829045678', 'enrolled': date(2026, 5, 1),
                'status': 'high_risk_overdue', 'att_pct': 0.35, 'trend': 'declining',
            },
            {
                'id': 'STU-0892', 'name': 'Tanishq Sharma', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Vishnu Sharma', 'phone': '9829040049', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.94, 'trend': 'improving',
            },
            {
                'id': 'STU-0893', 'name': 'Muskan Verma', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Brijesh Verma', 'phone': '9829040050', 'enrolled': date(2026, 5, 1),
                'status': 'part_paid_inst2', 'att_pct': 0.87, 'trend': 'stable',
            },
            {
                'id': 'STU-0894', 'name': 'Deepak Gurjar', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Mangej Gurjar', 'phone': '9829040051', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_1', 'att_pct': 0.90, 'trend': 'stable',
            },
            {
                'id': 'STU-0895', 'name': 'Pragati Jain', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'en',
                'parent_name': 'Ratan Jain', 'phone': '9829040052', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.96, 'trend': 'improving',
            },
            {
                'id': 'STU-0896', 'name': 'Payal Rathore', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Fateh Singh Rathore', 'phone': '9829040053', 'enrolled': date(2026, 5, 1),
                'status': 'overdue_inst2', 'att_pct': 0.83, 'trend': 'stable',
            },
            {
                'id': 'STU-0897', 'name': 'Manan Meena', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Hansraj Meena', 'phone': '9829040054', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.93, 'trend': 'improving',
            },
            {
                'id': 'STU-0898', 'name': 'Sakshi Shekhawat', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'en',
                'parent_name': 'Shakti Singh Shekhawat', 'phone': '9829040055', 'enrolled': date(2026, 5, 1),
                'status': 'part_paid_inst2', 'att_pct': 0.85, 'trend': 'declining',
            },
            {
                'id': 'STU-0899', 'name': 'Gaurav Yadav', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Brij Mohan Yadav', 'phone': '9829040056', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.95, 'trend': 'improving',
            },
            {
                'id': 'STU-0900', 'name': 'Ritik Mathur', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'en',
                'parent_name': 'Pramod Mathur', 'phone': '9829040057', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_1', 'att_pct': 0.88, 'trend': 'stable',
            },
            {
                'id': 'STU-0901', 'name': 'Diya Khandelwal', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Manoj Khandelwal', 'phone': '9829040058', 'enrolled': date(2026, 5, 1),
                'status': 'overdue_inst2', 'att_pct': 0.80, 'trend': 'declining',
            },
            {
                'id': 'STU-0902', 'name': 'Aryan Saini', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'hi',
                'parent_name': 'Girdhari Saini', 'phone': '9829040059', 'enrolled': date(2026, 5, 1),
                'status': 'fully_paid_up_to_2', 'att_pct': 0.92, 'trend': 'improving',
            },
            {
                'id': 'STU-0903', 'name': 'Ritu Gupta', 'centre': 'RJP', 'plan': plan_neet, 'lang': 'en',
                'parent_name': 'Sunil Gupta', 'phone': '9829040060', 'enrolled': date(2026, 5, 1),
                'status': 'part_paid_inst2', 'att_pct': 0.89, 'trend': 'stable',
            },
        ]

        today = date(2026, 11, 4)

        for s_data in students_spec:
            # 1. Create Guardian
            username = f"parent_{s_data['id'].lower().replace('-', '_')}"
            guardian = make_guardian(
                username=username,
                first_name=s_data['parent_name'],
                phone=s_data['phone'],
                lang=s_data['lang']
            )

            # 2. Create Student
            batch = batches[s_data['centre']]
            student = Student.objects.create(
                student_id=s_data['id'],
                name=s_data['name'],
                batch=batch,
                guardian=guardian,
                fee_plan=s_data['plan'],
                enrollment_date=s_data['enrolled'],
            )

            # 3. Create Student Login
            make_student_user(student)

            # 4. Create Instalments based on Fee Plan
            if s_data['plan'] == plan_jee:
                # 4 instalments of ₹30,000 (3,000,000 paise)
                inst1 = Instalment.objects.create(student=student, sequence=1, amount=3000000, due_date=date(2026, 4, 10))
                inst2 = Instalment.objects.create(student=student, sequence=2, amount=3000000, due_date=date(2026, 7, 10))
                inst3 = Instalment.objects.create(student=student, sequence=3, amount=3000000, due_date=date(2026, 10, 10))
                inst4 = Instalment.objects.create(student=student, sequence=4, amount=3000000, due_date=date(2027, 1, 10))

                # Handle payment status patterns for JEE
                status = s_data['status']
                if status == 'fully_paid_up_to_3':
                    record_payment(student, inst1, 3000000, mode='gateway')
                    record_payment(student, inst2, 3000000, mode='gateway')
                    record_payment(student, inst3, 3000000, mode='gateway')
                elif status == 'fully_paid_up_to_2':
                    record_payment(student, inst1, 3000000, mode='gateway')
                    record_payment(student, inst2, 3000000, mode='bank')
                elif status == 'part_paid_23d_overdue':
                    # Ishita Sharma mandatory case
                    record_payment(student, inst1, 3000000, mode='bank', ref='NEFT-ISHITA-01')
                    record_payment(student, inst2, 3000000, mode='gateway', ref='GW-ISHITA-02')
                    record_payment(student, inst3, 1500000, mode='gateway', ref='GW-ISHITA-03')
                elif status == 'part_paid_inst2':
                    record_payment(student, inst1, 3000000, mode='gateway')
                    record_payment(student, inst2, 1500000, mode='gateway')
                elif status == 'part_paid_inst3':
                    record_payment(student, inst1, 3000000, mode='gateway')
                    record_payment(student, inst2, 3000000, mode='gateway')
                    record_payment(student, inst3, 1500000, mode='gateway')
                elif status == 'overdue_inst3':
                    record_payment(student, inst1, 3000000, mode='gateway')
                    record_payment(student, inst2, 3000000, mode='gateway')
                    # Inst 3 remains unpaid (overdue since 2026-10-10)
                elif status == 'fully_paid_up_to_1':
                    record_payment(student, inst1, 3000000, mode='gateway')

            else:
                # NEET: 3 instalments of ₹40,000 (4,000,000 paise)
                inst1 = Instalment.objects.create(student=student, sequence=1, amount=4000000, due_date=date(2026, 5, 10))
                # For Rohit, inst2 was due on 2026-09-10 (55d overdue); for Mohit, inst2 is due 2026-11-15 (due in 11 days)
                due2 = date(2026, 9, 10) if s_data['status'] in ('high_risk_overdue', 'overdue_inst2') else date(2026, 11, 15)
                inst2 = Instalment.objects.create(student=student, sequence=2, amount=4000000, due_date=due2)
                inst3 = Instalment.objects.create(student=student, sequence=3, amount=4000000, due_date=date(2027, 3, 15))

                # Handle payment status patterns for NEET
                status = s_data['status']
                if status == 'due_in_11_days':
                    # Mohit Gurjar mandatory case
                    record_payment(student, inst1, 4000000, mode='cash', ref='CASH-MOHIT-01')
                elif status == 'high_risk_overdue':
                    # Rohit Choudhary mandatory case
                    record_payment(student, inst1, 4000000, mode='gateway', ref='GW-ROHIT-01')
                elif status == 'fully_paid_up_to_2':
                    record_payment(student, inst1, 4000000, mode='gateway')
                    record_payment(student, inst2, 4000000, mode='gateway')
                elif status == 'part_paid_inst2':
                    record_payment(student, inst1, 4000000, mode='gateway')
                    record_payment(student, inst2, 2000000, mode='gateway')
                elif status == 'overdue_inst2':
                    record_payment(student, inst1, 4000000, mode='gateway')
                    # Inst 2 unpaid and overdue
                elif status == 'fully_paid_up_to_1':
                    record_payment(student, inst1, 4000000, mode='gateway')

            # 5. Seed Attendance & Test Scores
            if s_data['status'] == 'high_risk_overdue':
                # Special high-risk curve for Rohit Choudhary
                for i in range(28):
                    d = today - timedelta(days=i)
                    present = (i % 4 == 0) if i < 14 else (i % 5 != 0)
                    Attendance.objects.create(student=student, date=d, present=present)
                TestScore.objects.create(student=student, test_name='Minor Test 1', date=date(2026, 8, 15), score=164, max_score=200)
                TestScore.objects.create(student=student, test_name='Minor Test 2', date=date(2026, 9, 20), score=140, max_score=200)
                TestScore.objects.create(student=student, test_name='Major Test 1', date=date(2026, 10, 25), score=70, max_score=200)
                # Trigger risk engine for Rohit
                scan_student_and_create_task(student, as_of_date=today)
            else:
                seed_academics(student, attendance_pct=s_data['att_pct'], test_trend=s_data['trend'])

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded CoachFee with {len(students_spec)} students across all 4 Jaipur centres:"))
        self.stdout.write(f"- Gopalpura Bypass (GPL): 12 students (including STU-0412 Aarav Meena - Paid)")
        self.stdout.write(f"- Vaishali Nagar (VSH): 12 students (including STU-0587 Ishita Sharma - Part paid, 23d overdue)")
        self.stdout.write(f"- Malviya Nagar (MLV): 13 students (including STU-0219 Mohit Gurjar - Due in 11 days)")
        self.stdout.write(f"- Raja Park (RJP): 13 students (including STU-0891 Rohit Choudhary - High Dropout Risk flag)")
        self.stdout.write(f"- Staff logins: 'staff' (Admin: all centres), 'exec_gpl' (Scoped to Gopalpura) / pass: staff123")
        self.stdout.write(f"- Parent logins: Phone number OTP (Alert dialog popup)")
        self.stdout.write(f"- Student logins: stu_<student_id> (e.g. stu_stu_0412) / pass: student123")
