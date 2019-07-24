import six


def escape(value):
    if isinstance(value, NoEscapeStr):
        return str(value)
    if isinstance(value, six.string_types):
        return "'%s'" % value
    return str(value)


class NoEscapeStr(str):

    _escape = False


class ArithmeticOpsToStr(NoEscapeStr):

    def __eq__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} = {value}'.format(col=self, value=other))

    def __ne__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} != {value}'.format(col=self, value=other))

    def __lt__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} < {value}'.format(col=self, value=other))

    def __gt__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} > {value}'.format(col=self, value=other))

    def __le__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} <= {value}'.format(col=self, value=other))

    def __ge__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} >= {value}'.format(col=self, value=other))

    def __add__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} + {value}'.format(col=self, value=other))

    def __sub__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} + {value}'.format(col=self, value=other))

    def __mul__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} * {value}'.format(col=self, value=other))

    def __floordiv__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} // {value}'.format(col=self, value=other))

    def __truediv__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} / {value}'.format(col=self, value=other))

    __div__ = __truediv__

    def __mod__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} % {value}'.format(col=self, value=other))

    def __lshift__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} << {value}'.format(col=self, value=other))

    def __rshift__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} >> {value}'.format(col=self, value=other))

    def __and__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} AND {value}'.format(col=self, value=other))

    def __or__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} OR {value}'.format(col=self, value=other))

    def __xor__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col} & {value}'.format(col=self, value=other))


class Element(object):

    def __str__(self):
        raise NotImplementedError('`Element` subclass must implement `__getattribute__` method')


class Generator(object):

    def __getattribute__(self, item):
        raise NotImplementedError('`Generator` subclass must implement `__getattribute__` method')


class Column(Element, ArithmeticOpsToStr):

    _name = None

    def __str__(self):
        return NoEscapeStr(self._name)

    def label(self, label):
        self._name = self._name + '` AS `' + label
        return self

    __repr__ = __str__


class ColumnGenerator(Generator):

    def __getattribute__(self, column):
        return type(column, (Column,), {'_name': column})()


col = ColumnGenerator()


class Function(Element, ArithmeticOpsToStr):

    _name = None

    def __call__(self, *args, **kwargs):
        self._args = ', '.join([escape(x) for x in args])
        self._args = self._args.replace('__', '')
        return self

    def __str__(self):
        return NoEscapeStr('{func}({args})'.format(func=self._name, args=self._args))

    __repr__ = __str__


class FunctionGenerator(Generator):

    def __getattribute__(self, f):
        return type(f, (Function,), {'_name': f})()


func = FunctionGenerator()
