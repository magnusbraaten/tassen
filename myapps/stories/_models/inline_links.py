# -*- coding: utf-8 -*-
""" Links inside text """

# Python standard library
import re
import logging
logger = logging.getLogger('universitas')
bylines_logger = logging.getLogger('bylines')
from slugify import Slugify
slugify = Slugify(max_length=50, to_lower=True)

# Django core
from django.utils.translation import ugettext_lazy as _
from django.conf import settings
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from django.core.validators import URLValidator, ValidationError
from django.utils.safestring import mark_safe

# Installed apps
from bs4 import BeautifulSoup
from requests import request
from requests.exceptions import Timeout, MissingSchema, ConnectionError
from model_utils.models import TimeStampedModel

# Project apps

from .status_codes import HTTP_STATUS_CODES
from .models import Story


class InlineLinkManager(models.Manager):

    def markup_to_html(self, text):
        """ replace markup version of tag with html version """
        for link in self.all():
            text = link.markup_to_html(text)
        return text

    def insert_urls(self, text):
        """ insert url as reference in link """
        for link in self.all():
            text = link.insert_url(text)
        return text


class InlineLink(TimeStampedModel):

    # Link looks like this: [this is a link](www.universitas.no)
    # Or this:              [this is a link](1)

    # TOKEN_START, TOKEN_SEP, TOKEN_END = '¨', '|', '¨'
    find_pattern = '\[(?P<text>.+?)\]\((?P<ref>\S+?)\)'
    change_pattern = '[{text}]({ref})'
    html_pattern = '<a href="{href}" alt="{alt}">{text}</a>'
    objects = InlineLinkManager()

    class Meta:
        verbose_name = _('inline link')
        verbose_name_plural = _('inline links')

    parent_story = models.ForeignKey(
        Story,
        related_name='inline_links'
    )
    number = models.PositiveSmallIntegerField(
        default=1,
        help_text=_('link label'),
    )
    href = models.CharField(
        blank=True,
        max_length=500,
        help_text=_('link target'),
        verbose_name=_('link target'),
    )
    linked_story = models.ForeignKey(
        Story,
        blank=True, null=True,
        help_text=_('link to story on this website.'),
        verbose_name=_('linked story'),
        related_name='incoming_links',
    )
    alt_text = models.CharField(
        max_length=500,
        blank=True,
        help_text=_('alternate link text'),
        verbose_name=_('alt text'),
    )
    text = models.TextField(
        blank=True,
        editable=False,
        help_text=_('link text'),
        verbose_name=_('link text'),
    )
    status_code = models.CharField(
        max_length=3,
        editable=False,
        default='',
        choices=HTTP_STATUS_CODES,
        help_text=_('Status code returned from automatic check.'),
        verbose_name=_('http status code'),
    )

    def get_tag(self, ref=None):
        """ Get markup placeholder for the link """
        pattern = self.change_pattern
        return pattern.format(text=self.text, ref=ref or self.number)

    def markup_to_html(self, text):
        """ replace markup version of tag with html version """
        text = re.sub(re.escape(self.get_tag()), self.get_html(), text)
        return text

    def insert_url(self, text):
        """ insert url as reference in link """
        text = re.sub(
            re.escape(
                self.get_tag()), self.get_tag(
                ref=self.link), text)
        return text

    def get_html(self):
        """ get <a> html tag for the link """
        pattern = self.html_pattern
        html = pattern.format(text=self.text, href=self.link, alt=self.alt_text)
        return mark_safe(html)

    get_html.allow_tags = True

    @property
    def link(self):
        if self.linked_story:
            return self.linked_story.get_absolute_url()
        elif self.href:
            return self.href
        return ''

    def find_linked_story(self):
        """
        Change literal url to foreign key if the target is
        another article in the database.
        """
        if not self.href or self.linked_story:
            return False

        if not self.linked_story:
            try:
                match = re.search(r'universitas.no/.+?/(?P<id>\d+)/', self.href)
                story_id = int(match.group('id'))
                self.linked_story = Story.objects.get(pk=story_id)
            except (AttributeError, ObjectDoesNotExist):
                # Not an internal link
                return False
        self.href = ''
        self.alt_text = self.linked_story.title
        return self.linked_story

    def save(self, *args, **kwargs):
        self.find_linked_story()
        super().save(*args, **kwargs)

    def check_link(self, save_if_changed=False, method='head', timeout=1):
        """ Does a http request to check the status of the url. """
        if self.linked_story:
            status_code = 'INT'
            url = validate_url(self.link)
        elif not self.link:
            status_code = ''
            url = ''
        else:
            url = validate_url(self.link)
            try:
                status_code = request(method, url, timeout=timeout).status_code
                if status_code == 410:
                    status_code = request(
                        'get',
                        url,
                        timeout=timeout).status_code
                if status_code > 500:
                    status_code = 500
                status_code = str(status_code)
            except Timeout:
                status_code = '408'  # HTTP Timout
            except MissingSchema:
                status_code = 'URL'  # not a HTTP url
            except ConnectionError:
                status_code = 'DNS'  # DNS error

        if save_if_changed and status_code != self.status_code:
            self.status_code = status_code
            self.save()

        logger.debug('{code}: {url}'.format(url=url, code=status_code))
        return status_code


def clean_and_create_links(body, parent_story):
    """
    Find markup links in text.
    Create new InlineLink objects if needed.
    Return text with updated markup for the changed links.
    """
    body = convert_html_links(body)
    found_links = re.finditer(InlineLink.find_pattern, body)
    queryset = parent_story.links()

    number = queryset.count() + 1
    for match in found_links:
        ref = match.group('ref')
        text = match.group('text')
        original_markup = re.escape(match.group(0))
        new_markup = []

        if re.match(r'^\d+$', ref):
            # ref is an integer
            ref = int(ref)
            links = queryset.filter(number=ref)
            if not links:
                link = InlineLink.objects.create(
                    number=ref,
                    parent_story=parent_story,
                )
            else:
                link = links[0]
                if link.text != text:
                    link.text = text
                    link.save()
                # other_links = links.exclude(pk=link.pk)
                for otherlink in links[1:]:
                    otherlink.number = number
                    otherlink.save()
                    number += 1
                    logger.warn(
                        'multiple links with same ref: ({}) {} {}'.format(
                            ref,
                            link,
                            otherlink))
                    new_markup.append(otherlink.get_tag())

        else:
            # ref is a url
            link = InlineLink(
                parent_story=parent_story,
                href=ref,
                number=number,
                alt_text=text,
                text=text,
            )
            number += 1
            link.save()

        new_markup = [link.get_tag()] + new_markup
        new_markup = ' '.join(new_markup)

        body = re.sub(original_markup, new_markup, body)
    return body


def convert_html_links(bodytext, return_html=False):
    """ convert <a href=""> to other tag """
    # if '&' in bodytext:
        # find = re.findall(r'.{,20}&.{,20}', bodytext)
        # logger.debug(find)
    soup = BeautifulSoup(bodytext)
    for link in soup.find_all('a'):
        href = link.get('href') or ''
        text = link.text
        href = validate_url(href)
        if href:
            replacement = InlineLink.change_pattern.format(
                ref=href.strip(),
                text=text.strip(),
            )
        else:
            # <a> element with no href
            replacement = '{text}'.format(text=text,)

        # change the link from html to markup
        link.replace_with(replacement)

    if return_html:
        bodytext = soup.decode()
    else:
        bodytext = soup.text
    return bodytext


def validate_url(href):
    """ Checks if input string is a valid http href. """
    site = settings.SITE_URL  # todo - get from settings.
    href = href.strip('«»“”"\'')
    if href.startswith('//'):
        href = 'http:{href}'.format(href=href)
    if href.startswith('/'):
        href = 'http://{site}{href}'.format(site=site, href=href)
    if not href.startswith('http://'):
        href = 'http://{href}'.format(href=href)
    try:
        validate = URLValidator()
        validate(href)
        return href
    except ValidationError:
        return None
