try:
    from setuptools import setup, Extension
except ImportError:
    from distutils.core import setup, Extension

VERSION = "0.10dev"

setup(
    name="clickhouse-wrapper",
    version=VERSION,
    description="Yandex ClickHouse wrapper for python",
    license="http://www.gnu.org/copyleft/gpl.html",
    platforms=["any"],
    # url="http://github.com/datawizio/pythonAPI/",
    packages=['clickhouse', 'clickhouse.orm', 'clickhouse.sql'],
    package_dir={'clickhouse': 'clickhouse'},
    install_requires=["requests", "six", "pytz", "iso8601"],
)