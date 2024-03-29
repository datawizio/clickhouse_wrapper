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
        return ArithmeticOpsToStr('{col} - {value}'.format(col=self, value=other))

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

    def __getitem__(self, other):
        other = escape(other)
        return ArithmeticOpsToStr('{col}[{value}]'.format(col=self, value=other))


class Element(object):

    def __str__(self):
        raise NotImplementedError('`Element` subclass must implement `__getattribute__` method')

    def __hash__(self):
        return hash(str(self))


class Generator(object):

    def __getattribute__(self, item):
        raise NotImplementedError('`Generator` subclass must implement `__getattribute__` method')


class Column(Element, ArithmeticOpsToStr):

    _name = None

    def __str__(self):
        return NoEscapeStr(self._name)

    def label(self, label):
        self._name = self._name + ' AS ' + label
        return self

    def __getattr__(self, column):
        return type(column, (Column,), {'_name': self._name + '.' + column})()

    __repr__ = __str__


class ColumnGenerator(Generator):

    def __getattribute__(self, column):
        return type(column, (Column,), {'_name': column})()


col = ColumnGenerator()


class Function(Element, ArithmeticOpsToStr):

    _name = None
    _args = None

    def __call__(self, *args, **kwargs):
        # support currying function(args)(args)
        if self._args is not None:
            self._name = str(self)
        self._args = ', '.join([escape(x) for x in args])
        self._args = self._args.replace('__', '')
        return self

    def __str__(self):
        return NoEscapeStr('{func}({args})'.format(func=self._name, args=self._args))

    def label(self, label):
        return NoEscapeStr('{func}({args}) AS {label}'.format(func=self._name, args=self._args, label=label))

    __repr__ = __str__


class FunctionGenerator(Generator):

    def __getattribute__(self, f):
        return type(f, (Function,), {'_name': f.replace('__', '')})()


func = FunctionGenerator()
