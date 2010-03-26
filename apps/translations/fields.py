from django import forms
from django.conf import settings
from django.db import models
from django.db.models.fields import related
from django.utils import translation as translation_utils
from django.utils.translation.trans_real import to_language

from .models import Translation, PurifiedTranslation, LinkifiedTranslation
from .widgets import TranslationWidget


class TranslatedField(models.ForeignKey):
    """A foreign key to the translations table."""
    model = Translation

    def __init__(self, **kwargs):
        # to_field: The field on the related object that the relation is to.
        # Django wants to default to translations.autoid, but we need id.
        options = dict(null=True, to_field='id', unique=True, blank=True)
        kwargs.update(options)
        super(TranslatedField, self).__init__(self.model, **kwargs)

    @property
    def db_column(self):
        # Django wants to call the db_column ('%s_id' % self.name), but our
        # translations foreign keys aren't set up that way.
        return self._db_column if hasattr(self, '_db_column') else self.name

    @db_column.setter
    def db_column(self, value):
        # Django sets db_column=None to initialize it.  I don't think anyone
        # would set the db_column otherwise.
        if value is not None:
            self._db_column = value

    def contribute_to_class(self, cls, name):
        """Add this Translation to ``cls._meta.translated_fields``."""
        super(TranslatedField, self).contribute_to_class(cls, name)
        self.alias = 'translated_%s' % self.column
        self.alias_locale = '%s_locale' % self.alias
        self.alias_autoid = '%s_autoid' % self.alias
        self.alias_created = '%s_created' % self.alias

        # Add self to the list of translated fields.
        if hasattr(cls._meta, 'translated_fields'):
            cls._meta.translated_fields[self] = self.alias
        else:
            cls._meta.translated_fields = {self: self.alias}

        setattr(cls, self.alias, FancyShit('localized_string', self))
        setattr(cls, self.alias_locale, FancyShit('locale', self))
        setattr(cls, self.alias_autoid, FancyShit('autoid', self))
        setattr(cls, self.alias_created, FancyShit('created', self))

        # Set up a unique related name.
        self.rel.related_name = '%s_%s_set' % (cls.__name__, name)

        # Replace the normal descriptor with our custom descriptor.
        setattr(cls, self.name, TranslationDescriptor(self))

    def formfield(self, **kw):
        defaults = {'form_class': TranslationFormField}
        defaults.update(kw)
        return super(TranslatedField, self).formfield(**defaults)

    def validate(self, value, model_instance):
        # Skip ForeignKey.validate since that expects only one Translation when
        # doing .get(id=id)
        return models.Field.validate(self, value, model_instance)


class PurifiedField(TranslatedField):
    model = PurifiedTranslation


class LinkifiedField(TranslatedField):
    model = LinkifiedTranslation


def switch(obj, new_model):
    """Switch between Translation and Purified/Linkified Translations."""
    fields = [(f.name, getattr(obj, f.name)) for f in new_model._meta.fields]
    return new_model(**dict(fields))


class FancyShit(object):

    def __init__(self, attr, field):
        self.attr = attr
        self.field = field

    def __set__(self, instance, value):
        t = getattr(instance, self.field.name)
        trans_id = getattr(instance, self.field.attname)
        trans = Translation(id=trans_id) if t is None else t
        setattr(trans, self.attr, value)
        setattr(instance, self.field.name, trans)


class TranslationDescriptor(related.ReverseSingleRelatedObjectDescriptor):
    """
    Descriptor that handles creating and updating Translations given strings.
    """

    def __init__(self, field):
        super(TranslationDescriptor, self).__init__(field)
        self.model = field.model

    def __get__(self, instance, instance_type=None):
        if instance is None:
            return self

        # If Django doesn't find find the value in the cache (which would only
        # happen if the field was set or accessed already), it does a db query
        # to follow the foreign key.  We expect translations to be set by
        # TranslatedFieldMixin, so doing a query is the wrong thing here.
        try:
            return getattr(instance, self.field.get_cache_name())
        except AttributeError:
            return None

    def __set__(self, instance, value):
        lang = translation_utils.get_language()
        if isinstance(value, basestring):
            value = self.translation_from_string(instance, lang, value)
        elif hasattr(value, 'items'):
            value = self.translation_from_dict(instance, lang, value)


        # Don't let this be set to None, because Django will then blank out the
        # foreign key for this object.  That's incorrect for translations.
        if value is not None:
            # We always get these back from the database as Translations, but
            # we may want them to be a more specific Purified/Linkified child
            # class.
            if not isinstance(value, self.model):
                value = switch(value, self.model)
            super(TranslationDescriptor, self).__set__(instance, value)

    def translation_from_string(self, instance, lang, string):
        """Create, save, and return a Translation from a string."""
        try:
            trans = getattr(instance, self.field.name)
            trans_id = getattr(instance, self.field.attname)
            if trans is None and trans_id is not None:
                # This locale doesn't have a translation set, but there are
                # translations in another locale, so we have an id already.
                return self.model.new(string, lang, id=trans_id)
            elif to_language(trans.locale) == lang.lower():
                # Replace the translation in the current language.
                trans.localized_string = string
                trans.save()
                return trans
            else:
                # We already have a translation in a different language.
                return self.model.new(string, lang, id=trans.id)
        except AttributeError:
            # Create a brand new translation.
            return self.model.new(string, lang)

    def translation_from_dict(self, instance, lang, dict_):
        """
        Create Translations from a {'locale': 'string'} mapping.

        If one of the locales matches lang, that Translation will be returned.
        """
        rv = None
        for locale, string in dict_.items():
            # The Translation is created and saved in here.
            trans = self.translation_from_string(instance, locale, string)

            # Set the Translation on the object because translation_from_string
            # doesn't expect Translations to be created but not attached.
            self.__set__(instance, trans)

            # If we're setting the current locale, set it to the object so
            # callers see the expected effect.
            if to_language(locale) == lang:
                rv = trans
        return rv


class TranslatedFieldMixin(object):
    """Mixin that fetches all ``TranslatedFields`` after instantiation."""

    def _set_translated_fields(self):
        """Fetch and attach all of this object's translations."""
        if hasattr(self._meta, 'translated_fields'):
            fields = self._meta.translated_fields
        else:
            fields = dict((f, f.alias) for f in self._meta.fields
                          if isinstance(f, TranslatedField))
            self._meta.translated_fields = fields

        # Map the attribute name to the object name: 'name_id' => 'name'
        names = dict((f.attname, f.name) for f in fields)
        # Map the foreign key to the attribute name: self.name_id => 'name_id'
        ids = dict((getattr(self, name), name) for name in names)

        lang = translation_utils.get_language()
        q = self.fetch_translations(filter(None, ids), lang)

        for translation in q:
            attr = names.pop(ids[translation.id])
            setattr(self, attr, translation)

    def fetch_translations(self, ids, lang):
        """
        Performs the query for finding Translation objects.

        - ``ids`` is a list of the foreign keys to the object's translations
        - ``lang`` is the language of the current request

        Override this to search for translations in an unusual way.
        """
        return translations_with_fallback(ids, lang, settings.LANGUAGE_CODE)


def translations_with_fallback(ids, lang, default):
    """Default implementation for TranslatedFieldMixin.fetch_translations."""
    if not ids:
        return []

    fetched = Translation.objects.filter(id__in=ids, locale=lang,
                                         localized_string__isnull=False)

    # Try to find any missing translations in the default locale.
    missing = set(ids).difference(t.id for t in fetched)
    if missing and default != lang:
        fallback = Translation.objects.filter(id__in=missing, locale=default)
        return list(fetched) + list(fallback)
    else:
        return fetched


class TranslationFormField(forms.Field):
    widget = TranslationWidget

    def __init__(self, *args, **kwargs):
        del kwargs['queryset']
        del kwargs['to_field_name']
        super(TranslationFormField, self).__init__(*args, **kwargs)

    def clean(self, value):
        return dict(value)
