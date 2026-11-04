from datetime import date
from django.core.management.base import BaseCommand
from reminders.services import process_daily_reminders


class Command(BaseCommand):
    help = 'Dispatches scheduled fee instalment reminders at -3, 0, +1, +7, +15 days past due date'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Run reminders as of a specific date (YYYY-MM-DD). Defaults to today.',
        )

    def handle(self, *args, **options):
        target_date = date.today()
        if options.get('date'):
            from datetime import datetime
            target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()

        self.stdout.write(f"Executing daily reminder dispatch for {target_date}...")
        stats = process_daily_reminders(target_date)

        self.stdout.write(self.style.SUCCESS(
            f"Reminders completed for {target_date}:\n"
            f"- Checked: {stats['checked']}\n"
            f"- Sent: {stats['sent']}\n"
            f"- Skipped (already paid / stop-on-pay): {stats['skipped_paid']}\n"
            f"- Skipped (duplicate offset already dispatched): {stats['skipped_duplicate']}"
        ))
