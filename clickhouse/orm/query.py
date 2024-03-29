from __future__ import unicode_literals

import six
import pytz
from copy import copy
from math import ceil

from .engines import CollapsingMergeTree
from .utils import comma_join, escape, is_in_parenthesis


# TODO
# - check that field names are valid
# - operators for arrays: length, has, empty

class Operator(object):
    """
    Base class for filtering operators.
    """

    def to_sql(self, model_cls, field_name, value):
        """
        Subclasses should implement this method. It returns an SQL string
        that applies this operator on the given field and value.
        """
        raise NotImplementedError   # pragma: no cover


class SimpleOperator(Operator):
    """
    A simple binary operator such as a=b, a<b, a>b etc.
    """

    def __init__(self, sql_operator, sql_for_null=None):
        self._sql_operator = sql_operator
        self._sql_for_null = sql_for_null

    def to_sql(self, model_cls, field_name, value):
        field = getattr(model_cls, field_name)
        value = field.to_db_string(field.to_python(value, pytz.utc))
        if value == '\\N' and self._sql_for_null is not None:
            return '%s %s' % (field_name, self._sql_for_null)
        return '%s %s %s' % (field_name, self._sql_operator, value)


class InOperator(Operator):
    """
    An operator that implements IN.
    Accepts 3 different types of values:
    - a list or tuple of simple values
    - a string (used verbatim as the contents of the parenthesis)
    - a queryset (subquery)
    """

    def to_sql(self, model_cls, field_name, value):
        field = getattr(model_cls, field_name)
        if isinstance(value, QuerySet):
            value = value.as_sql()
        elif isinstance(value, six.string_types):
            pass
        else:
            value = comma_join([field.to_db_string(field.to_python(v, pytz.utc)) for v in value])
        return '%s IN (%s)' % (field_name, value)


class LikeOperator(Operator):
    """
    A LIKE operator that matches the field to a given pattern. Can be
    case sensitive or insensitive.
    """

    def __init__(self, pattern, case_sensitive=True):
        self._pattern = pattern
        self._case_sensitive = case_sensitive

    def to_sql(self, model_cls, field_name, value):
        field = getattr(model_cls, field_name)
        value = field.to_db_string(field.to_python(value, pytz.utc), quote=False)
        value = value.replace('\\', '\\\\').replace('%', '\\\\%').replace('_', '\\\\_')
        pattern = self._pattern.format(value)
        if self._case_sensitive:
            return '%s LIKE \'%s\'' % (field_name, pattern)
        else:
            return 'lowerUTF8(toString(%s)) LIKE lowerUTF8(\'%s\')' % (field_name, pattern)


class IExactOperator(Operator):
    """
    An operator for case insensitive string comparison.
    """

    def to_sql(self, model_cls, field_name, value):
        field = getattr(model_cls, field_name)
        value = field.to_db_string(field.to_python(value, pytz.utc))
        return 'lowerUTF8(%s) = lowerUTF8(%s)' % (field_name, value)


class NotOperator(Operator):
    """
    A wrapper around another operator, which negates it.
    """

    def __init__(self, base_operator):
        self._base_operator = base_operator

    def to_sql(self, model_cls, field_name, value):
        # Negate the base operator
        return 'NOT (%s)' % self._base_operator.to_sql(model_cls, field_name, value)


class BetweenOperator(Operator):
    """
    An operator that implements BETWEEN.
    Accepts list or tuple of two elements and generates sql condition:
    - 'BETWEEN value[0] AND value[1]' if value[0] and value[1] are not None and not empty
    Then imitations of BETWEEN, where one of two limits is missing
    - '>= value[0]' if value[1] is None or empty
    - '<= value[1]' if value[0] is None or empty
    """

    def to_sql(self, model_cls, field_name, value):
        field = getattr(model_cls, field_name)
        value0 = field.to_db_string(
                field.to_python(value[0], pytz.utc)) if value[0] is not None or len(str(value[0])) > 0 else None
        value1 = field.to_db_string(
                field.to_python(value[1], pytz.utc)) if value[1] is not None or len(str(value[1])) > 0 else None
        if value0 and value1:
            return '%s BETWEEN %s AND %s' % (field_name, value0, value1)
        if value0 and not value1:
            return ' '.join([field_name, '>=', value0])
        if value1 and not value0:
            return ' '.join([field_name, '<=', value1])

# Define the set of builtin operators

_operators = {}

def register_operator(name, sql):
    _operators[name] = sql

register_operator('eq',          SimpleOperator('=', 'IS NULL'))
register_operator('ne',          SimpleOperator('!=', 'IS NOT NULL'))
register_operator('gt',          SimpleOperator('>'))
register_operator('gte',         SimpleOperator('>='))
register_operator('lt',          SimpleOperator('<'))
register_operator('lte',         SimpleOperator('<='))
register_operator('between',     BetweenOperator())
register_operator('in',          InOperator())
register_operator('not_in',      NotOperator(InOperator()))
register_operator('contains',    LikeOperator('%{}%'))
register_operator('startswith',  LikeOperator('{}%'))
register_operator('endswith',    LikeOperator('%{}'))
register_operator('icontains',   LikeOperator('%{}%', False))
register_operator('istartswith', LikeOperator('{}%', False))
register_operator('iendswith',   LikeOperator('%{}', False))
register_operator('iexact',      IExactOperator())


class FOV(object):
    """
    An object for storing Field + Operator + Value.
    """

    def __init__(self, field_name, operator, value):
        self._field_name = field_name
        self._operator = _operators.get(operator)
        self._operator_lookup = operator
        if self._operator is None:
            # The field name contains __ like my__field
            self._field_name = field_name + '__' + operator
            self._operator = _operators['eq']
        self._value = value

    def to_sql(self, model_cls):
        return self._operator.to_sql(model_cls, self._field_name, self._value)


class Q(object):

    AND_MODE = 'AND'
    OR_MODE = 'OR'

    def __init__(self, **filter_fields):
        self._fovs = [self._build_fov(k, v) for k, v in six.iteritems(filter_fields)]
        self._l_child = None
        self._r_child = None
        self._negate = False
        self._mode = self.AND_MODE

    @classmethod
    def _construct_from(cls, l_child, r_child, mode):
        q = cls()
        q._l_child = l_child
        q._r_child = r_child
        q._mode = mode # AND/OR
        return q

    def _build_fov(self, key, value):
        if '__' in key:
            field_name, operator = key.rsplit('__', 1)
        else:
            field_name, operator = key, 'eq'
        return FOV(field_name, operator, value)

    def to_sql(self, model_cls):
        if self._fovs:
            sql = ' {} '.format(self._mode).join(fov.to_sql(model_cls) for fov in self._fovs)
        else:
            if self._l_child is not None and self._r_child is not None:
                l_child_sql = self._l_child.to_sql(model_cls)
                r_child_sql = self._r_child.to_sql(model_cls)
                if l_child_sql == '1':
                    sql = '{}'.format(r_child_sql)
                elif r_child_sql == '1':
                    sql = '{}'.format(l_child_sql)
                else:
                    sql = '({} {} {})'.format(
                       l_child_sql, self._mode, r_child_sql)
            else:
                return '1'
        if self._negate:
            sql = 'NOT (%s)' % sql
        return sql

    def __or__(self, other):
        return self.__class__._construct_from(self, other, self.OR_MODE)

    def __and__(self, other):
        return self.__class__._construct_from(self, other, self.AND_MODE)

    def __invert__(self):
        q = copy(self)
        q._negate = not q._negate
        return q

    def __bool__(self):
        return bool(self._fovs or self._r_child or self._l_child)


class NDEQ(Q):
    """No Depth Error Q
    Q that fixes the max recursion depth error in the to_sql() method.
    """

    def to_sql(self, model_cls, is_root: bool = True) -> str:
        if self._fovs:
            sql = ' {} '.format(self._mode).join(fov.to_sql(model_cls) for fov in self._fovs)
        else:
            if self._l_child is not None and self._r_child is not None:
                l_child_sql = self._l_child.to_sql(model_cls, is_root=False)
                r_child_sql = self._r_child.to_sql(model_cls, is_root=False)
                if l_child_sql == '1':
                    sql = '{}'.format(r_child_sql)
                elif r_child_sql == '1':
                    sql = '{}'.format(l_child_sql)
                else:
                    sql_template = (
                        '({} {} {})'
                        if is_root or not (is_in_parenthesis(l_child_sql) and is_in_parenthesis(r_child_sql))
                        else '{} {} {}'
                    )
                    sql = sql_template.format(l_child_sql, self._mode, r_child_sql)
            else:
                return '1'
        if self._negate:
            sql = 'NOT (%s)' % sql
        return sql


class FBFOV(FOV):
    """
    Function Based FOV
    """

    def to_sql(self, model_cls):
        setattr(self, self._field_name, self.pseudo_field)
        return self._operator.to_sql(self, self._field_name, self._value)

    class PseudoField(object):
        """
        Need to represent function based field
        """
        @staticmethod
        def to_db_string(v, quote=True):
            return escape(v, quote)

        @staticmethod
        def to_python(v, _):
            return v

    pseudo_field = PseudoField()


class FBQ(Q):

    """
    Function Based Q
    """

    def _build_fov(self, key, value):
        if '__' in key:
            field_name, operator = key.rsplit('__', 1)
        else:
            field_name, operator = key, 'eq'
        return FBFOV(field_name, operator, value)


@six.python_2_unicode_compatible
class QuerySet(object):
    """
    A queryset is an object that represents a database query using a specific `Model`.
    It is lazy, meaning that it does not hit the database until you iterate over its
    matching rows (model instances).
    """

    def __init__(self, model_cls, database):
        """
        Initializer. It is possible to create a queryset like this, but the standard
        way is to use `MyModel.objects_in(database)`.
        """
        self._model_cls = model_cls
        self._database = database
        self._order_by = []
        self._q = []
        self._fields = ['*']
        self._limits = None
        self._join_label = ''
        self._join_type = ''
        self._join_fields = []
        self._join_query = None
        self._subquery = ''
        self._distinct = False
        self._extra = ''
        self._array = ''
        self._final = False

    def __iter__(self):
        """
        Iterates over the model instances matching this queryset
        """
        return self._database.select(self.as_sql(), self._model_cls)

    def __bool__(self):
        """
        Returns true if this queryset matches any rows.
        """
        return bool(self.count())

    def __nonzero__(self):      # Python 2 compatibility
        return type(self).__bool__(self)

    def __str__(self):
        return self.as_sql()

    def __getitem__(self, s):
        if isinstance(s, six.integer_types):
            # Single index
            assert s >= 0, 'negative indexes are not supported'
            qs = copy(self)
            qs._limits = (s, 1)
            return six.next(iter(qs))
        else:
            # Slice
            assert s.step in (None, 1), 'step is not supported in slices'
            start = s.start or 0
            stop = s.stop or 2**63 - 1
            assert start >= 0 and stop >= 0, 'negative indexes are not supported'
            assert start <= stop, 'start of slice cannot be smaller than its end'
            qs = copy(self)
            qs._limits = (start, stop - start)
            return qs

    def as_sql(self):
        """
        Returns the whole query as a SQL string.
        """
        distinct = 'DISTINCT ' if self._distinct else ''
        fields = '*'
        if self._fields:
            fields = comma_join('%s' % field for field in self._fields)
        ordering = '\nORDER BY ' + self.order_by_as_sql() if self._order_by else ''
        limit = '\nLIMIT %d, %d' % self._limits if self._limits else ''
        join = '\n%s' % self.join_as_sql() if self._join_fields else ''
        array_join = '\n%s' % self._array if self._array else ''
        final = ' FINAL' if self._final else ''
        table = self._subquery if self._subquery else '%s' % self._model_cls.table_name()
        params = (distinct, fields, table, join, array_join,
                  final, self.conditions_as_sql(), ordering, limit)
        return u'SELECT %s%s\nFROM %s%s%s%s\nWHERE %s%s%s' % params

    def join(self, query, *join_fields, inner_=False, label_='', all_=True ):
        qs = copy(self)
        qs._join_fields = join_fields
        qs._join_query = query
        if label_:
            qs._join_label = ' AS %s' % label_
        if all_:
            qs._join_type += 'ALL '
        else:
            qs._join_type += 'ANY '
        if inner_:
            qs._join_type += 'INNER JOIN '
        else:
            qs._join_type += 'LEFT JOIN '
        return qs

    def array_join(self, *array, label=''):
        array = comma_join((str(item)) for item in array)
        qs = copy(self)
        qs._array = 'ARRAY JOIN [%s]' % array + ' AS %s' % label if label else ''
        return qs

    def join_as_sql(self):
        join_table = u'(%s)' % self._join_query.as_sql() if hasattr(self._join_query,
                                                                    'as_sql') else u'%s' % self._join_query.table_name()
        join_fields = comma_join('%s' % field for field in self._join_fields)
        return u'%s %s %s USING %s' % (self._join_type, join_table, self._join_label, join_fields)

    def subquery(self, label=''):
        qs = QuerySet(self._model_cls, self._database)
        if label:
            qs._subquery = u'(%s) AS %s' % (self.as_sql(),label)
        else:
            qs._subquery = u'(%s)' % self.as_sql()
        return qs

    def extra_filter(self, raw):
        qs = copy(self)
        qs._extra = raw
        return qs

    def order_by_as_sql(self):
        """
        Returns the contents of the query's `ORDER BY` clause as a string.
        """
        return comma_join([
            '%s DESC' % field[1:] if field[0] == '-' else field
            for field in self._order_by
        ])

    def conditions_as_sql(self):
        """
        Returns the contents of the query's `WHERE` clause as a string.
        """
        if self._q:
            res_ = ' AND '.join([q.to_sql(self._model_cls) for q in self._q if q.to_sql(self._model_cls) != '1']) or '1'
            if self._extra:
                res_ += ' AND ' + self._extra
            return res_
        elif self._extra:
            return self._extra
        return u'1'

    def count(self):
        """
        Returns the number of matching model instances.
        """
        if self._distinct or self._limits:
            # Use a subquery, since a simple count won't be accurate
            sql = u'SELECT count() FROM (%s)' % self.as_sql()
            raw = self._database.raw(sql)
            return int(raw) if raw else 0
        # Simple case
        return self._database.count(self._model_cls, self.conditions_as_sql())

    def order_by(self, *field_names):
        """
        Returns a copy of this queryset with the ordering changed.
        """
        qs = copy(self)
        qs._order_by = field_names
        return qs

    def only(self, *field_names):
        """
        Returns a copy of this queryset limited to the specified field names.
        Useful when there are large fields that are not needed,
        or for creating a subquery to use with an IN operator.
        """
        qs = copy(self)
        qs._fields = field_names
        return qs

    def filter(self, *q, **filter_fields):
        """
        Returns a copy of this queryset that includes only rows matching the conditions.
        Add q object to query if it specified.
        """
        qs = copy(self)
        if q:
            qs._q = list(self._q) + list(q)
        if filter_fields:
            qs._q = qs._q + [Q(**filter_fields)]
        return qs

    def exclude(self, *q_list, **filter_fields):
        """
        Returns a copy of this queryset that excludes all rows matching the conditions.
        """
        qs = copy(self)
        if q_list:
            qs._q = list(self._q) + list([~q for q in q_list])
        if filter_fields:
            qs._q = qs._q + [~Q(**filter_fields)]
        return qs

    def paginate(self, page_num=1, page_size=100):
        """
        Returns a single page of model instances that match the queryset.
        Note that `order_by` should be used first, to ensure a correct
        partitioning of records into pages.

        - `page_num`: the page number (1-based), or -1 to get the last page.
        - `page_size`: number of records to return per page.

        The result is a namedtuple containing `objects` (list), `number_of_objects`,
        `pages_total`, `number` (of the current page), and `page_size`.
        """
        from .database import Page
        count = self.count()
        pages_total = int(ceil(count / float(page_size)))
        if page_num == -1:
            page_num = pages_total
        elif page_num < 1:
            raise ValueError('Invalid page number: %d' % page_num)
        offset = (page_num - 1) * page_size
        return Page(
            objects=list(self[offset : offset + page_size]),
            number_of_objects=count,
            pages_total=pages_total,
            number=page_num,
            page_size=page_size
        )

    def distinct(self):
        """
        Adds a DISTINCT clause to the query, meaning that any duplicate rows
        in the results will be omitted.
        """
        qs = copy(self)
        qs._distinct = True
        return qs

    def final(self):
        """
        Adds a FINAL modifier to table, meaning data will be collapsed to final version.
        Can be used with `CollapsingMergeTree` engine only.
        """
        if not isinstance(self._model_cls.engine, CollapsingMergeTree):
            raise TypeError('final() method can be used only with CollapsingMergeTree engine')

        qs = copy(self)
        qs._final = True
        return qs

    def aggregate(self, *args, **kwargs):
        """
        Returns an `AggregateQuerySet` over this query, with `args` serving as
        grouping fields and `kwargs` serving as calculated fields. At least one
        calculated field is required. For example:
        ```
            Event.objects_in(database).filter(date__gt='2017-08-01').aggregate('event_type', count='count()')
        ```
        is equivalent to:
        ```
            SELECT event_type, count() AS count FROM event
            WHERE data > '2017-08-01'
            GROUP BY event_type
        ```
        """
        return AggregateQuerySet(self, args, kwargs)




class AggregateQuerySet(QuerySet):
    """
    A queryset used for aggregation.
    """

    def __init__(self, base_qs, grouping_fields, calculated_fields):
        """
        Initializer. Normally you should not call this but rather use `QuerySet.aggregate()`.

        The grouping fields should be a list/tuple of field names from the model. For example:
        ```
            ('event_type', 'event_subtype')
        ```
        The calculated fields should be a mapping from name to a ClickHouse aggregation function. For example:
        ```
            {'weekday': 'toDayOfWeek(event_date)', 'number_of_events': 'count()'}
        ```
        At least one calculated field is required.
        """
        super(AggregateQuerySet, self).__init__(base_qs._model_cls, base_qs._database)
        assert calculated_fields, 'No calculated fields specified for aggregation'
        self._fields = grouping_fields
        self._grouping_fields = grouping_fields
        self._calculated_fields = calculated_fields
        self._order_by = list(base_qs._order_by)
        self._q = list(base_qs._q)
        self._subquery = base_qs._subquery
        self._limits = base_qs._limits
        self._distinct = base_qs._distinct
        self._join_type = base_qs._join_type
        self._join_fields = base_qs._join_fields
        self._join_label =base_qs._join_label
        self._join_query = base_qs._join_query
        self._array = base_qs._array
        self._extra = base_qs._extra
        self._having = []
        self._with = None

    def group_by(self, *args):
        """
        This method lets you specify the grouping fields explicitly. The `args` must
        be names of grouping fields or calculated fields that this queryset was
        created with.
        """
        for name in args:
            assert name in self._fields or name in self._calculated_fields, \
                   'Cannot group by `%s` since it is not included in the query' % name
        qs = copy(self)
        qs._grouping_fields = args
        return qs

    def only(self, *field_names):
        """
        This method is not supported on `AggregateQuerySet`.
        """
        raise NotImplementedError('Cannot use "only" with AggregateQuerySet')

    def aggregate(self, *args, **kwargs):
        """
        This method is not supported on `AggregateQuerySet`.
        """
        raise NotImplementedError('Cannot re-aggregate an AggregateQuerySet')

    def having(self, *q_list, **filter_fields):
        qs = copy(self)
        if q_list:
            qs._having += q_list
        if filter_fields:
            qs._having += [FBQ(**filter_fields)]
        return qs

    def having_as_sql(self):
        """
        Returns the contents of the query's `HAVING` clause as a string.
        """
        return (
            u' AND '.join([q.to_sql(self._model_cls) for q in self._having if q.to_sql(self._model_cls) != '1']) or u'1'
        )

    def as_sql(self):
        """
        Returns the whole query as a SQL string.
        """
        distinct = 'DISTINCT ' if self._distinct else ''
        grouping = comma_join('%s' % field for field in self._grouping_fields)
        having = self.having_as_sql()
        fields = comma_join(
            ['%s' % f for f in self._fields] + ['%s AS %s' % (v, k) for k, v in self._calculated_fields.items()]
        )
        params = dict(
            distinct=distinct,
            fields=fields,
            table=self._subquery if self._subquery else '%s' % self._model_cls.table_name(),
            conds=self.conditions_as_sql(),
            join=self.join_as_sql() if self._join_fields else '',
            array_join='%s' % self._array if self._array else ''
        )
        sql = u'SELECT %(distinct)s%(fields)s\nFROM %(table)s\n%(join)s\n%(array_join)s\nWHERE %(conds)s' % params
        if self._grouping_fields:
            sql += '\nGROUP BY ' + grouping
        if self._having:
            sql += '\nHAVING ' + having
        if self._with:
            sql += '\nWITH ' + self._with
        if self._order_by:
            sql += '\nORDER BY ' + self.order_by_as_sql()
        if self._limits:
            sql += '\nLIMIT %d, %d' % self._limits
        return sql

    def __iter__(self):
        return self._database.select(self.as_sql())  # using an ad-hoc model

    def count(self):
        """
        Returns the number of rows after aggregation.
        """
        sql = u'SELECT count() FROM (%s)' % self.as_sql()
        raw = self._database.raw(sql)
        return int(raw) if raw else 0

    def with_rollup(self):
        qs = copy(self)
        qs._with = 'ROLLUP'
        return qs

    def with_totals(self):
        qs = copy(self)
        qs._with = 'TOTALS'
        return qs

    def with_cube(self):
        qs = copy(self)
        qs._with = 'CUBE'
        return qs
