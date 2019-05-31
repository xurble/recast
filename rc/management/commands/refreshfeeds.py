
from django.core.management.base import BaseCommand, CommandError

from rc.utils import update_feeds

class Command(BaseCommand):
    help = 'Closes the specified poll for voting'


    def handle(self, *args, **options):

        update_feeds(self.stdout, 30)

        self.stdout.write(self.style.SUCCESS('Finished'))