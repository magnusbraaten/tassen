""" Management commands for importing images and stories from legacy website and production system. """

from optparse import make_option
import logging
logger = logging.getLogger('universitas')

from django.conf import settings
from django.core.management.base import BaseCommand  # ,CommandError

# from apps.stories.models import Story
from apps.legacy_db.export_content_and_images import (
    import_legacy_website_content,
    import_prodsys_content,
    drop_model_tables,
    reset_db_autoincrement,
)

from apps.stories.models import Story
from apps.contributors.models import Contributor
from apps.photo.models import ImageFile


class Command(BaseCommand):
    help = 'Imports content from legacy website.'
    leave_locale_alone = True,
    can_import_settings = True,
    option_list = BaseCommand.option_list + (
        make_option(
            '--replace_existing', '-x',
            action='store_true',
            dest='replace existing',
            default=False,
            help='Replace existing content from previous imports.'
        ),
        make_option(
            '--first', '-f',
            type='int',
            dest='first',
            default=0,
            help='Number of stories to skip at beginning of import.'
        ),
        make_option(
            '--number', '-n',
            type='int',
            dest='number',
            default=0,
            help='Number of stories to import'
        ),
        make_option(
            '--reverse', '-r',
            action='store_true',
            dest='reverse',
            default=False,
            help='Start with newest stories.'
        ),
        make_option(
            '--textonly', '-t',
            action='store_true',
            dest='text only',
            default=False,
            help='Only import text.'
        ),
        make_option(
            '--drop', '-d',
            action='store_true',
            dest='drop',
            default=False,
            help='Drop old content from the database.'
        ),
        make_option(
            '--prodsys', '-p',
            action='store_true',
            dest='prodsys only',
            default=False,
            help='Import articles from prodsys.'
        ),
        make_option(
            '--crop', '-c',
            action='store_true',
            dest='autocrop',
            default=False,
            help='Autocrop images'
        ),
    )

    def handle(self, *args, **options):

        first = options['first']
        last = first + options['number'] if options['number'] else None

        if options['prodsys only']:

            if options['drop'] and not options['replace existing']:
                drop_model_tables(Story, Contributor, ImageFile)

            status = import_prodsys_content(
                text_only=options['text only'],
                first=options['first'],
                last=last,
                reverse=options['reverse'],
                replace_existing=options['replace existing'],
                autocrop=options['autocrop'],
            )
            if status:
                self.stdout.write('Successfully imported content from prodsys.')
            else:
                self.stdout.write('No content to import.')

        else:
            # Import from website
            if settings.DEBUG:
                self.stderr.write('WARNING: Django running with in DEBUG mode.\nThis command might run out of memory.')

            if options['drop'] and not options['replace existing']:
                drop_model_tables(Story, Contributor, ImageFile)

            status = import_legacy_website_content(
                text_only=options['text only'],
                first=first,
                last=last,
                reverse=options['reverse'],
                replace_existing=options['replace existing'],
                autocrop=options['autocrop'],
            )

            reset_db_autoincrement()
            if status:
                self.stdout.write('Successfully imported content from website.')
            else:
                self.stdout.write('No content to import.')
