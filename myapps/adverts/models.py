# -*- coding: utf-8 -*-
import logging
import re
import random
from django.db import models

# from model_utils.models import TimeStampedModel
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.safestring import mark_safe

from sorl.thumbnail import ImageField, get_thumbnail

from .dummy_image_advert import dummy_image_advert


logger = logging.getLogger('universitas')


class AdFormat(models.Model):

    """ Size and shape of ad. """

    PRINT, WEB = 1, 2
    CATEGORY_CHOICES = [(PRINT, _('print')), (WEB, _('web')), ]

    name = models.CharField(unique=True, max_length=50)
    width = models.PositiveSmallIntegerField()
    height = models.PositiveSmallIntegerField()
    price = models.PositiveIntegerField(
        help_text=_('display price'),
    )
    published = models.BooleanField(default=True)
    category = models.PositiveSmallIntegerField(
        default=WEB,
        choices=CATEGORY_CHOICES,
    )

    class Meta:
        verbose_name = _('AdFormat')
        verbose_name_plural = _('AdFormats')
        unique_together = ('width', 'height')
        ordering = ('category', '-width', '-price')

    def __str__(self):
        unit = 'px' if self.category == self.WEB else 'mm'
        return '{s.name} ({s.width}{u} × {s.height}{u})'.format(s=self, u=unit)


class AdChannel(models.Model):

    """ Location for ads to be placed. """

    name = models.CharField(
        unique=True,
        max_length=50,
    )
    description = models.TextField(
        blank=True,
        null=True,

    )
    ad_formats = models.ManyToManyField(
        AdFormat,
        null=True,
        help_text=_('size and shape of ad'),
    )
    extra_classes = models.CharField(
        help_text=_('comma separated list of extra css classes to apply.'),
        blank=True,
        max_length=50,
    )
    max_at_once = models.PositiveSmallIntegerField(
        help_text=_('Maximum ads to show at once.'),
        default=1,
    )

    class Meta:
        verbose_name = _("Location")
        verbose_name_plural = _("Locations")

    def formats(self):
        return ', '.join(str(f) for f in self.ad_formats.all()) or '–'

    def __str__(self):
        return self.name

    def css_classes(self):
        return '{name} {extra}'.format(
            name = self.name.lower().replace(' ', '-'),
            extra = self.extra_classes,
            )

    def current_ads(self, at_time=None, publication_status=None):
        """ All ads in current position at current time """
        if publication_status is None:
            publication_status = [Advert.PUBLISHED, Advert.DEFAULT]
        ads = self.advert_set.filter(
            status__in=publication_status)
        return ads

    @property
    def active_ads(self):
        return ', '.join(str(ad) for ad in self.current_ads())

    def serve_ads(self):
        served_ads = self.current_ads().order_by(
            '-ordering',
            '?',
        )[:self.max_at_once]
        return served_ads

        # old_ads = old_ads or []
        # served_ads = []
        # unseen_ads = self.current_ads.exclude(id__in=seen_ads).order_by('-priority').all()
        # seen_ads = self.current_ads.filter(id__in=seen_ads).order_by('-priority').all()
        # spots = self.max_at_once
        # while spots:
        #     spots -= 1
        #     if unseen_ads:
        #         unseen_ads.pop()
        #         served_ads.append()
        #     elif seen_ads:


class Customer(models.Model):

    """ Buyer of the ad """

    name = models.CharField(max_length=500)
    contact_info = models.TextField(blank=True)

    class Meta:
        verbose_name = _("Customer")
        verbose_name_plural = _("Customers")

    def __str__(self):
        return self.name


class AdvertManager(models.Manager):

    def published_at(self, at_time=None):
        if at_time is None:
            at_time = timezone.now()
        return super().get_queryset().filter(
            start_time__lte=at_time,
            end_time__gte=at_time,
        )

    def create_dummy(self, adformat):
        """ Create a dummy ad """
        dummy_customer, new = Customer.objects.get_or_create(name='dummy')

        new_image = dummy_image_advert(
            adformat.width, adformat.height,
            watermarktext='reklame',
            labeltext=adformat.name,
        )

        new_ad = Advert(
            customer=dummy_customer,
            description='dummy jpg {}'.format(adformat),
            alt_text='dummy',
            link='http://example.com',
            imagefile=new_image,
            ad_type=Advert.IMAGE_AD,
            status=Advert.PRIVATE,
        )
        new_ad.save()
        return new_ad


def upload_folder(instance, filename):
    customer_name = re.sub(r'\s+', '', instance.customer.name)[:15].lower()
    path = '/'.join(['adverts', customer_name, filename])
    logger.debug(path)
    return path


def default_start_time():
    return timezone.now().replace(hour=6, minute=0, second=0)


def default_end_time():
    return default_start_time() + timezone.timedelta(weeks=4)


class Advert(models.Model):

    """ Individual ads """

    IMAGE_AD = 1
    CODE_AD = 2
    DUMMY_AD = 3
    ADTYPE_CHOICES = [
        (IMAGE_AD, _('Image advert')),
        (CODE_AD, _('HTML advert')),
        (DUMMY_AD, _('Dummy or unfinished advert')),
    ]

    DRAFT = 1
    PRIVATE = 2
    PUBLISHED = 3
    DEFAULT = 4
    STATUS_CHOICES = [
        (DRAFT, _(
            "Not ready to publish.")),
        (PRIVATE, _(
            "Private.")),
        (PUBLISHED, _(
            "Served to visiting audience.")),
        (DEFAULT, _(
            "Fallback ad served if no published ad exists in this channel.")),
    ]
    description = models.CharField(
        help_text=_('Short description of this ad.'),
        blank=True,
        null=True,
        max_length=100)

    customer = models.ForeignKey(
        Customer,
        help_text=_('Who bought this ad?'),
    )
    ad_channels = models.ManyToManyField(
        AdChannel,
        null=True,
        blank=True,
        help_text=_('Where to show the ad'),
    )
    ordering = models.PositiveIntegerField(
        help_text=_('Ordering of the ad within the channel'),
        default=1,
    )
    status = models.PositiveIntegerField(
        help_text=_('Publication status'),
        choices=STATUS_CHOICES,
        default=DRAFT,
    )
    ad_type = models.PositiveIntegerField(
        help_text=_('Advert type.'),
        choices=ADTYPE_CHOICES,
        default=DUMMY_AD,
        editable=False,
    )
    start_time = models.DateTimeField(
        help_text=_('When to start serving this ad'),
        default=default_start_time,

    )
    end_time = models.DateTimeField(
        help_text=_('When to stop serving this ad'),
        default=default_end_time,
    )
    imagefile = ImageField(
        help_text=_('Image Ad: image file in jpg or png format'),
        blank=True,
        null=True,
        upload_to=upload_folder,
    )
    link = models.URLField(
        help_text=_('Image Ad: url that ad links to'),
        blank=True, null=True,
    )
    alt_text = models.CharField(
        help_text=_('Image ad: alternative text for image'),
        blank=True,
        default='',
        max_length=50,
    )
    html_source = models.TextField(
        help_text=_('HTML to use for ad instead of serving an image ad.'),
        blank=True, null=True,
    )
    objects = AdvertManager()

    class Meta:
        verbose_name = _("Advert")
        verbose_name_plural = _("Adverts")

    def __str__(self):
        try:
            return self.description or '{self.customer}: {self.start_time}'.format(
                self=self)
        except:
            return 'New Advert'

    def save(self, *args, **kwargs):
        # set ad_type based on which fields have been filled out
        super().save(*args, **kwargs)

    def clean(self):
        """ make sure ad has valid values"""

        self.ad_type = self.determine_ad_type()
        if not self.id:
            self.status = self.DRAFT

        # if self.ad_type != self.DUMMY_AD:
        if self.status in [self.PUBLISHED, self.DEFAULT]:
            if self.ad_channels.count() == 0:
                raise ValidationError(
                    {'ad_channels': _('Choose one or more ad channels before publishing.')})
            if self.ad_type == self.DUMMY_AD:
                raise ValidationError(
                    _('Published ad must contain an image or html code.'))

            if self.ad_type == self.IMAGE_AD:
                if not self.link:
                    raise ValidationError({
                        'link': _('Image ads must have a link.')
                    })
                if not self.alt_text:
                    raise ValidationError({
                        'alt_text': _('Image ads must have alternative text.')
                    })

            if self.end_time <= self.start_time:
                raise ValidationError({
                    'end_time': _('End time must be after start time.')
                })

    def dimension(self, axis):
        """ return default height or width of this ad in pixels """
        if axis in ('w', 'width', 'x'):
            axis = 'width'
        else:
            axis = 'height'

        try:
            return getattr(self.imagefile, axis)
        except AttributeError:
            pass
        try:
            return getattr(self.ad_channels.first().ad_formats.first(), axis)
        except AttributeError:
            pass

        return 300

    @property
    def width(self):
        return self.dimension('width')

    @property
    def height(self):
        return self.dimension('height')

    def determine_ad_type(self, as_string=False):
        """ Determine which kind of ad it is based on which fields are filled in. """
        if self.html_source:
            return self.CODE_AD
        elif self.imagefile:
            return self.IMAGE_AD
        else:
            return self.DUMMY_AD

    def get_html(self):
        img_template = (
            '<a href="{self.link}" '
            'alt="{self.alt_text}" >'
            '<img src="{src}">'
            '</a>'
        )
        div_template = (
            '<div class="annonse {html_class}">{content}</div>'
        )
        if self.ad_type == self.CODE_AD:
            content = self.html_source
            html_class = 'annonse'
        elif self.ad_type == self.IMAGE_AD:
            thumb = get_thumbnail(
                self.imagefile, '%sx%s' %
                (self.width, self.height))
            content = img_template.format(self=self, src=thumb.url)
            html_class = 'annonse'
        elif self.ad_type == self.DUMMY_AD:
            content = str(self)
            html_class = 'annonse dummy ' + \
                random.choice(['blue_ad', 'red_ad', 'yellow_ad'])
        html_source = div_template.format(
            html_class=html_class,
            self=self,
            content=content)
        return mark_safe(html_source)
