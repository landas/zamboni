from django.db import models, connection

import caching


class Translation(caching.CachingMixin, models.Model):
    """
    Translation model.

    Use :class:`translations.fields.TranslatedField` instead of a plain foreign
    key to this model.
    """

    autoid = models.AutoField(primary_key=True)
    id = models.IntegerField()
    locale = models.CharField(max_length=10)
    localized_string = models.TextField()

    # These are normally from amo.ModelBase, but we don't want to have weird
    # circular dependencies between ModelBase and Translations.
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    objects = caching.CachingManager()

    class Meta:
        db_table = 'translations'
        unique_together = ('id', 'locale')

    def __unicode__(self):
        return self.localized_string

    def __nonzero__(self):
        # __nonzero__ is called to evaluate an object in a boolean context.  We
        # want Translations to be falsy if their string is empty.
        return bool(self.localized_string.strip())

    @property
    def cache_key(self):
        return self._cache_key(self.id)

    @classmethod
    def new(cls, string, locale, id=None):
        """
        Jumps through all the right hoops to create a new translation.

        If ``id`` is not given a new id will be created using
        ``translations_seq``.  Otherwise, the id will be used to add strings to
        an existing translation.
        """
        if id is None:
            # Get a sequence key for the new translation.
            cursor = connection.cursor()
            cursor.execute("""UPDATE translations_seq
                              SET id=LAST_INSERT_ID(id + 1)""")
            cursor.execute('SELECT LAST_INSERT_ID() FROM translations_seq')
            id = cursor.fetchone()[0]

        return Translation.objects.create(id=id, localized_string=string,
                                          locale=locale)


class TranslationSequence(models.Model):
    """
    The translations_seq table, so syncdb will create it during testing.
    """
    id = models.IntegerField(primary_key=True)

    class Meta:
        db_table = 'translations_seq'