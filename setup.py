#!/bin/env python
import os
import sys

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

from tornado_pypi_proxy import VERSION

if sys.version_info < (3, 3):
    sys.exit("requires python 3.3 and up")

here = os.path.dirname(__file__)

setup(
    name='Tornado-Pypi-Proxy',
    version=VERSION,
    description='A tornado base Pypi proxy',
    long_description=open('README.md').read(),
    author='A. Azhar Mashuri',
    author_email='hurie83@gmail.com',
    url='https://github.com/hurie83/Tornado-PyPi-Proxy',
    install_requires=[
        'PyYAML==3.11',
        'beautifulsoup4==4.3.2',
        'pathlib==1.0',
        'tornado==4.0.1',
    ],
    include_package_data=True,
    packages=[
        'tornado_pypi_proxy',
    ],
    package_data={'tornado_pypi_proxy': [
        'template/config.yml',
    ]},
    entry_points={
        'console_scripts': [
            'tornado-pypi-proxy = tornado_pypi_proxy.main:main',
        ],
    },
    zip_safe=False,
    keywords='pypi tornado proxy',
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.3',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ]
)
