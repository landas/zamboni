from django.conf import settings
from django.db import connections, models
from django.utils import translation

import multidb

from translations.models import Translation

isnull = """IF(!ISNULL({t1}.localized_string), {t1}.{col}, {t2}.{col})
            AS {name}_{col}"""
join = """LEFT OUTER JOIN translations {t}
          ON ({t}.id={model}.{name} AND {t}.locale={locale})"""

trans_fields = [f.name for f in Translation._meta.fields]


def build_query(model, connection):
    qn = connection.ops.quote_name
    selects, joins, params = [], [], []

    # The model can define a fallback locale (which may be a Field).
    if hasattr(model, 'get_fallback'):
        fallback = model.get_fallback()
    else:
        fallback = settings.LANGUAGE_CODE

    # Add the selects and joins for each translated field on the model.
    for field in model._meta.translated_fields:
        # Add the primary and (possibly) fallback locale parameters.
        params.append(translation.get_language())
        if isinstance(fallback, models.Field):
            fallback_str = '%s.%s' % (qn(model._meta.db_table),
                                      qn(fallback.column))
        else:
            fallback_str = '%s'
            params.append(fallback)

        name = field.column
        d = {'t1': 't1_' + name, 't2': 't2_' + name,
             'model': qn(model._meta.db_table), 'name': name}

        selects.extend(isnull.format(col=f, **d) for f in trans_fields)
        for table, locale in (('t1', '%s'), ('t2', fallback_str)):
            joins.append(join.format(t=d[table], locale=locale, **d))

    # ids will be added later on.
    sql = """SELECT {model}.{pk}, {selects} FROM {model} {joins}
             WHERE {model}.{pk} IN {{ids}}"""
    s = sql.format(selects=','.join(selects), joins='\n'.join(joins),
                   model=qn(model._meta.db_table), pk=model._meta.pk.column)
    return s, params


def get_trans(items):
    if not items:
        return

    connection = connections[multidb.get_slave()]
    cursor = connection.cursor()

    model = items[0].__class__
    sql, params = build_query(model, connection)
    item_dict = dict((item.pk, item) for item in items)
    ids = ','.join(map(str, item_dict.keys()))

    cursor.execute(sql.format(ids='(%s)' % ids), tuple(params))
    step = len(trans_fields)
    for row in cursor.fetchall():
        # We put the item's pk as the first selected field.
        item = item_dict[row[0]]
        for index, field in enumerate(model._meta.translated_fields):
            start = 1 + step * index
            t = Translation(*row[start:start+step])
            if t.id is not None and t.localized_string is not None:
                setattr(item, field.name, t)
