import re
import difflib
import json
import logging
logger = logging.getLogger('universitas')
bylines_logger = logging.getLogger('bylines')
from slugify import Slugify
slugify = Slugify(max_length=50, to_lower=True)

# Django core
from django.utils.translation import ugettext_lazy as _
from django.db import models

# Installed apps
from diff_match_patch import diff_match_patch

# Project apps
from myapps.contributors.models import Contributor


class Byline(models.Model):

    """ Credits the people who created content for a story. """

    CREDIT_CHOICES = [
        ('text', _('Text')),
        ('photo', _('Photo')),
        ('video', _('Video')),
        ('illus', _('Illustration')),
        ('graph', _('Graphics')),
        ('trans', _('Translation')),
        ('???', _('Unknown')),
    ]
    DEFAULT_CREDIT = CREDIT_CHOICES[0][0]
    story = models.ForeignKey('Story')
    contributor = models.ForeignKey(Contributor)
    credit = models.CharField(
        choices=CREDIT_CHOICES,
        default=DEFAULT_CREDIT,
        max_length=20,
    )
    title = models.CharField(
        blank=True,
        null=True,
        max_length=200,
    )

    class Meta:
        verbose_name = _('Byline')
        verbose_name_plural = _('Bylines')

    def __str__(self):
        return '{credit}: {full_name} ({story_title})'.format(
            credit=self.get_credit_display(),
            full_name=self.contributor,
            story_title=self.story,
        )

    @classmethod
    def create(cls, full_byline, story, initials=''):
        """
        Creates new user or tries to find existing name in db
        args:
            full_byline: string of byline and creditline
            article: Article object (must be saved)
            initials: string
        returns:
            Byline object
        """
        byline_pattern = re.compile(
            # single word credit with colon. Person's name, Person's job title
            # or similiar description.
            # Example:
            # text: Jane Doe, Just a regular person
            r'^(?P<credit>[^:, ]+): (?P<full_name>[^,]+)\s*(, (?P<title>.+))?$',
            flags=re.UNICODE,
        )

        match = byline_pattern.match(full_byline)
        full_name = None
        try:
            d = match.groupdict()
            full_name = d['full_name'].title()
            title = d['title'] or ''
            credit = d['credit'].lower()
            initials = ''.join(
                letters[0] for letters in full_name.replace(
                    '-',
                    ' ').split())
            assert initials == initials.upper(
            ), 'All names should be capitalised'
            assert len(
                initials) <= 5, 'Five names probably means something is wrong.'
            if len(initials) == 1:
                initials = full_name.upper()

        except (AssertionError, AttributeError, ) as e:
            # Malformed byline
            p_org = w_org = ' -- '
            if story.legacy_prodsys_source:
                dump = story.legacy_prodsys_source
                tekst = json.loads(dump)[0]['fields']['tekst']
                p_org = needle_in_haystack(full_byline, tekst)
            if story.legacy_html_source:
                dump = story.legacy_html_source
                w_org = json.loads(dump)[0]['fields']['byline']

            warning = ((
                'Malformed byline: "{byline}" error: {error} id: {id}'
                ' p_id: {p_id}\n{p_org} | {w_org} ').format(
                id=story.id,
                p_id=story.prodsak_id,
                story=story,
                byline=full_byline,
                error=e,
                p_org=p_org,
                w_org=w_org,
            ))
            logger.warn(warning)
            story.comment += warning
            story.publication_status = story.STATUS_ERROR

            full_name = 'Nomen Nescio'
            title = full_byline
            initials = 'XX'
            credit = '???'

        for choice in cls.CREDIT_CHOICES:
            # Find correct credit.
            ratio = difflib.SequenceMatcher(
                None,
                choice[0],
                credit[:5],
            ).ratio()
            if .4 > ratio > .8:
                logger.debug(choice[0], credit, ratio)
            if ratio > .8:
                credit = choice[0]
                break
        else:
            credit = cls.DEFAULT_CREDIT

        contributor = Contributor.get_or_create(full_name, initials)

        new_byline = cls(
            story=story,
            credit=credit,
            title=title[:200],
            contributor=contributor,
        )
        new_byline.save()

        return new_byline


def needle_in_haystack(needle, haystack):
    """ strips away all spaces and puctuations before comparing. """
    needle = re.sub(r'\W', '', needle).lower()
    diff = diff_match_patch()
    diff.Match_Distance = 5000  # default is 1000
    diff.Match_Threshold = .5  # default is .5
    lines = haystack.splitlines()
    for line in lines:
        line2 = re.sub(r'\W', '', line).lower()
        value = diff.match_main(line2, needle, 0)
        if value is not -1:
            return line
    return 'no match in %d lines' % (len(lines),)


def clean_up_bylines(raw_bylines):
    """
    Normalise misformatting and idiosyncraticies of bylines in legacy data.
    string -> string
    """
    replacements = (
        # Symbols used to separate individual bylines.
        (r'\r|;|•|\*|·|/', r'\n', re.I),

        # No full stops
        (r'\.', r' ', re.I),

        # A word that ends with colon must be at the beginning of a line.
        (r' +(\S*?:)', r'\n\1', 0),


        # comma, and or "og" before two capitalised words probably means it's
        # a new person. Insert newline.
        (r'\s*(&|#|,\s|\s[oO]g\s|\s[aA]nd\s)\s*([A-ZÆØÅ]\S+ [A-ZÆØÅ])',
         r'\n\2',
         0),
        # TODO: Bytt ut byline regular expression med ny regex-modul som funker
        # med unicode

        # parantheses shall have no spaces inside them, but after and before.
        (r' *\( *(.*?) *\) *', r' (\1) ', 0),

        # close parantheses.
        (r'\([^)]+$', r'\0)', re.M),

        # email addresses will die!
        (r'\S+@\S+', '', 0),

        # words in parantheses at end of line is probably some creditation.
        # Put in front with colon instead.
        (r'^(.*?) *\(([^)]*)\) *$', r'\2: \1', re.M),

        # "Anmeldt av" is text credit.
        (r'anmeldt av:?', 'text: ', re.I),

        # Oversatt = translatrion
        (r'oversatt av:?', 'translation: ', re.I),

        # Any word containging "photo" is some kind of photo credit.
        (r'\S*(ph|f)oto\S*?[\s:]*', '\nphoto: ', re.I),

        # Any word containing "text" is text credit.
        (r'\S*te(ks|x)t\S*?[\s:]*', '\ntext: ', re.I),

        # These words are stripped from end of line.
        (r' *(,| og| and) *$', '', re.M | re.I),

        # These words are stripped from start of line
        (r'^ *(,|og |and |av ) *', '', re.M | re.I),

        # These words are stripped from after colon
        (r': *(,|og |and |av ) *', ':', re.M | re.I),

        # Creditline with empty space after it is deleted.
        (r'^\S:\s*$', '', re.M),

        # Multiple spaces.
        (r' {2,}', ' ', 0),

        # Remove lines containing only whitespace.
        (r'\s*\n\s*', r'\n', 0),

        # Bylines with no credit are assumed to be text credit.
        (r'^([^:]+?)$', r'text:\1', re.M),

        # Exactly one space after and no space before colon or comma.
        (r'\s*([:,])+\s*', r'\1 ', 0),

        # No multi colons
        (r': *:', r':', 0),

        # No random colons at the start or end of a line
        (r'^\s*:', r'', re.M),
        (r':\s*$', r'', re.M),
    )

    byline_words = []
    for word in raw_bylines.split():
        if word == word.upper():
            word = word.title()
        byline_words.append(word)

    bylines = ' '.join(byline_words)
    for pattern, replacement, flags in replacements:
        bylines = re.sub(pattern, replacement, bylines, flags=flags)
    bylines = bylines.strip()
    bylines_logger.debug(
        '(\n"{input}",\n"{out}"\n),'.format(
            input=raw_bylines.replace('\n', r'\n'),
            out=bylines.replace('\n', r'\n'),
        ))
    return bylines
