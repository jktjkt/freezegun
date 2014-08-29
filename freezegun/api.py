import time
import datetime
import functools
import sys
import inspect
import unittest

from dateutil import parser

real_time = time.time
real_date = datetime.date
real_datetime = datetime.datetime


# Stolen from six
def with_metaclass(meta, *bases):
    """Create a base class with a metaclass."""
    return meta("NewBase", bases, {})


class FakeTime(object):

    def __init__(self, time_to_freeze):
        self.time_to_freeze = time_to_freeze

    def __call__(self):
        shifted_time = self.time_to_freeze - datetime.timedelta(seconds=time.timezone)
        return time.mktime(shifted_time.timetuple()) + shifted_time.microsecond / 1000000.0


class FakeDateMeta(type):
    @classmethod
    def __instancecheck__(self, obj):
        return isinstance(obj, real_date)


def datetime_to_fakedatetime(datetime):
    return FakeDatetime(datetime.year,
                        datetime.month,
                        datetime.day,
                        datetime.hour,
                        datetime.minute,
                        datetime.second,
                        datetime.microsecond,
                        datetime.tzinfo)


def date_to_fakedate(date):
    return FakeDate(date.year,
                    date.month,
                    date.day)


class FakeDate(with_metaclass(FakeDateMeta, real_date)):
    date_to_freeze = None

    def __new__(cls, *args, **kwargs):
        return real_date.__new__(cls, *args, **kwargs)

    def __add__(self, other):
        result = real_date.__add__(self, other)
        if result is NotImplemented:
            return result
        return date_to_fakedate(result)

    def __sub__(self, other):
        result = real_date.__sub__(self, other)
        if result is NotImplemented:
            return result
        if isinstance(result, real_date):
            return date_to_fakedate(result)
        else:
            return result

    @classmethod
    def today(cls):
        result = cls.date_to_freeze
        return date_to_fakedate(result)

FakeDate.min = date_to_fakedate(real_date.min)
FakeDate.max = date_to_fakedate(real_date.max)


class FakeDatetimeMeta(FakeDateMeta):
    @classmethod
    def __instancecheck__(self, obj):
        return isinstance(obj, real_datetime)


class FakeDatetime(with_metaclass(FakeDatetimeMeta, real_datetime, FakeDate)):
    time_to_freeze = None
    tz_offset = None

    def __new__(cls, *args, **kwargs):
        return real_datetime.__new__(cls, *args, **kwargs)

    def __add__(self, other):
        result = real_datetime.__add__(self, other)
        if result is NotImplemented:
            return result
        return datetime_to_fakedatetime(result)

    def __sub__(self, other):
        result = real_datetime.__sub__(self, other)
        if result is NotImplemented:
            return result
        if isinstance(result, real_datetime):
            return datetime_to_fakedatetime(result)
        else:
            return result

    @classmethod
    def now(cls, tz=None):
        if tz:
            result = tz.fromutc(cls.time_to_freeze.replace(tzinfo=tz)) + datetime.timedelta(hours=cls.tz_offset)
        else:
            result = cls.time_to_freeze + datetime.timedelta(hours=cls.tz_offset)
        return datetime_to_fakedatetime(result)

    @classmethod
    def today(cls):
        return cls.now(tz=None)

    @classmethod
    def utcnow(cls):
        result = cls.time_to_freeze
        return datetime_to_fakedatetime(result)

FakeDatetime.min = datetime_to_fakedatetime(real_datetime.min)
FakeDatetime.max = datetime_to_fakedatetime(real_datetime.max)

def convert_to_timezone_naive(time_to_freeze):
    """
    Converts a potentially timezone-aware datetime to be a naive UTC datetime
    """
    if time_to_freeze.utcoffset():
        time_to_freeze += time_to_freeze.utcoffset()
        time_to_freeze =  time_to_freeze.replace(tzinfo=None)
    return time_to_freeze


class _freeze_time(object):

    def __init__(self, time_to_freeze_str, tz_offset, ignore):
        time_to_freeze = parser.parse(time_to_freeze_str)
        time_to_freeze = convert_to_timezone_naive(time_to_freeze)

        self.time_to_freeze = time_to_freeze
        self.tz_offset = tz_offset
        self.ignore = ignore

    def __call__(self, func):
        if inspect.isclass(func):
            return self.decorate_class(func)
        return self.decorate_callable(func)

    def decorate_class(self, klass):
        for attr in dir(klass):
            if not attr.startswith("test"):
                continue

            attr_value = getattr(klass, attr)
            if not hasattr(attr_value, "__call__"):
                continue

            setattr(klass, attr, self(attr_value))
        return klass

    def __enter__(self):
        self.start()

    def __exit__(self, *args):
        self.stop()

    def start(self):
        datetime.datetime = FakeDatetime
        datetime.date = FakeDate
        fake_time = FakeTime(self.time_to_freeze)
        time.time = fake_time

        for mod_name, module in list(sys.modules.items()):
            if module is None:
                continue
            if mod_name.startswith(tuple(self.ignore)):
                continue
            if hasattr(module, "__name__") and module.__name__ != 'datetime':
                if hasattr(module, 'datetime') and module.datetime == real_datetime:
                    module.datetime = FakeDatetime
                if hasattr(module, 'date') and module.date == real_date:
                    module.date = FakeDate
            if hasattr(module, "__name__") and module.__name__ != 'time':
                if hasattr(module, 'time') and module.time == real_time:
                    module.time = fake_time

        datetime.datetime.time_to_freeze = self.time_to_freeze
        datetime.datetime.tz_offset = self.tz_offset

        # Since datetime.datetime has already been mocked, just use that for
        # calculating the date
        datetime.date.date_to_freeze = datetime.datetime.now().date()

    def stop(self):
        datetime.datetime = real_datetime
        datetime.date = real_date
        time.time = real_time

        for mod_name, module in list(sys.modules.items()):
            if mod_name.startswith(tuple(self.ignore)):
                continue
            if mod_name != 'datetime':
                if hasattr(module, 'datetime') and module.datetime == FakeDatetime:
                    module.datetime = real_datetime
                if hasattr(module, 'date') and module.date == FakeDate:
                    module.date = real_date
            if mod_name != 'time':
                if hasattr(module, 'time') and isinstance(module.time, FakeTime):
                    module.time = real_time

    def decorate_callable(self, func):
        def wrapper(*args, **kwargs):
            with self:
                result = func(*args, **kwargs)
            return result
        functools.update_wrapper(wrapper, func)
        return wrapper


def freeze_time(time_to_freeze, tz_offset=0, ignore=None):
    if isinstance(time_to_freeze, datetime.datetime):
        time_to_freeze = time_to_freeze.isoformat()
    elif isinstance(time_to_freeze, datetime.date):
        time_to_freeze = time_to_freeze.isoformat()

    # Python3 doesn't have basestring, but it does have str.
    try:
        string_type = basestring
    except NameError:
        string_type = str

    if not isinstance(time_to_freeze, string_type):
        raise TypeError(('freeze_time() expected a string, date instance, or '
                         'datetime instance, but got type {0}.').format(type(time_to_freeze)))
    if ignore is None:
        ignore = []
    ignore.append('six.moves.')
    ignore.append('django.utils.six.moves.')
    return _freeze_time(time_to_freeze, tz_offset, ignore)


# Setup adapters for sqlite
try:
    import sqlite3
except ImportError:
    # Some systems have trouble with this
    pass
else:
    # These are copied from Python sqlite3.dbapi2
    def adapt_date(val):
        return val.isoformat()

    def adapt_datetime(val):
        return val.isoformat(" ")

    sqlite3.register_adapter(FakeDate, adapt_date)
    sqlite3.register_adapter(FakeDatetime, adapt_datetime)
