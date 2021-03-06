# -*- coding: utf-8 -*-
"""Urls to redirect"""
from django.conf.urls import url
from django.views.generic.base import RedirectView

urlpatterns = [
    # PHP utils from old website and other cruft that older browsers might request.
    url(r'^(?P<base>.+)/(hl|tel):.+$', RedirectView.as_view(url=r'/%(base)s/')),
    url(r'^rss\.php$', RedirectView.as_view(url=r'/rss/')),
    # Retired pages from old website
    url(r'^inc/func/image\.inc\.php', RedirectView.as_view(url=None)),
    url(r'^arkivet/', RedirectView.as_view(url=None)),
    # Rebranded pages
    url(r'^nyhet/$', RedirectView.as_view(url=r'/nyheter/')),
    url(r'^vispor/$', RedirectView.as_view(url=r'/baksiden/vi-spor/')),
    url(r'^nyheter/omverden/$',
        RedirectView.as_view(url=r'/nyheter/utenriks/')),
    url(r'^omverden/$', RedirectView.as_view(url=r'/nyheter/utenriks/')),
    # Annoying bot doesn't understand href="tel:..."
]
