# -*- encoding: utf-8 -*-
# Copyright P. Christeas <xrg@hellug.gr> 2013
# Only some little rights reserved

import settings
from django.db import models
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.utils import translation
from optparse import make_option
from dhelp.models import HelpTopic
from django.utils.translation import ugettext_lazy as _
import logging
from datetime import datetime
from operator import itemgetter
from django.core.urlresolvers import RegexURLResolver, RegexURLPattern


def list_view_urls(urllist, depth=0, app=None):
    sub_app = None
    for entry in urllist:
        if isinstance(entry, RegexURLResolver):
            name = entry.app_name or entry.urlconf_name
            if isinstance(name, list):
                continue
            elif isinstance(name, basestring):
                sub_app = name
            else:
                sub_app = name.__name__
                if sub_app.endswith('.urls'):
                    sub_app = sub_app[:-5]
        elif isinstance(entry, RegexURLPattern) and entry.name:
            yield app, entry.name

        if hasattr(entry, 'url_patterns'):
            for a, n in list_view_urls(entry.url_patterns, depth + 1, app=sub_app):
                yield a, n


class Command(BaseCommand):
    args = ''
    help = 'Scans all Django models, apps, views and generates help topics'
    option_list = BaseCommand.option_list + (
        make_option('-l', '--lang',
            help='Language to use'),
        )

    def handle(self, *args, **options):
        logger = logging.getLogger('apps.dhelp.commands')
        if options.get('lang', False):
            if options['lang'] not in map(itemgetter(0), settings.LANGUAGES):
                raise CommandError("Invalid language: %s" % options['lang'])
            translation.activate(options['lang'])

        user = User.objects.get(pk=1)
        apps_done = set()
        for model in models.get_models():
            mmeta = model._meta
            if mmeta.app_label not in apps_done:
                logger.debug("Application: %s", mmeta.app_label)
                HelpTopic.objects.get_or_create(mode='app', tkey=mmeta.app_label,
                        defaults={'title': _("Application: %s") % mmeta.app_label,
                                'create_user': user, 'create_date': datetime.now(),
                                'active': False })

            logger.debug("Model: %s.%s", mmeta.app_label, mmeta.object_name)

            HelpTopic.objects.get_or_create(mode='model',
                        tkey='%s.%s' %(mmeta.app_label, mmeta.object_name),
                        defaults={'title': _("Model: %s") % mmeta.verbose_name,
                                'create_user': user, 'create_date': datetime.now(),
                                'active': False })

            for field in mmeta.fields:
                if field.name == 'id':
                    continue
                logger.debug("Field: %s", field.name)

                HelpTopic.objects.get_or_create(mode='field',
                        tkey='%s.%s.%s' %(mmeta.app_label, mmeta.object_name, field.name),
                        defaults={'title': _("Field: %s") % (field.verbose_name or field.name),
                                'create_user': user, 'create_date': datetime.now(),
                                'active': False,
                                'content': field.help_text or False})

        import urls
        for app, name in list_view_urls(urls.urlpatterns):
            if mmeta.app_label not in apps_done:
                logger.debug("Application: %s", app)
                HelpTopic.objects.get_or_create(mode='app', tkey=app,
                        defaults={'title': _("Application: %s") % app,
                                'create_user': user, 'create_date': datetime.now(),
                                'active': False })

            logger.debug("View: %s.%s", app, name)

            HelpTopic.objects.get_or_create(mode='view',
                        tkey='%s.%s' %(app, name),
                        defaults={'title': _("View: %s") % name,
                                'create_user': user, 'create_date': datetime.now(),
                                'active': False })

        if options.get('lang', False):
            translation.deactivate()

#eof
