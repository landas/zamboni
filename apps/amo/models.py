from django.db import models

import caching.base
from translations.fields import TranslatedFieldMixin
from translations.query import TranslationManager


# Our apps should subclass BaseManager instead of models.Manager or
# caching.base.CachingManager directly.
ManagerBase = TranslationManager


class ModelBase(caching.base.CachingMixin, TranslatedFieldMixin, models.Model):
    """
    Base class for AMO models to abstract some common features.

    * Adds automatic created and modified fields to the model.
    * Fetches all translations in one subsequent query during initialization.
    """

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    objects = ManagerBase()

    class Meta:
        abstract = True
        get_latest_by = 'created'

    def get_absolute_url(self, *args, **kwargs):
        return self.get_url_path(*args, **kwargs)
