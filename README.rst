Tornado Pypi Proxy
==================

A Tornado PyPI proxy. Use asynchronous to stream downloaded package from
PyPI to eliminate timeout caused by package being downloaded first by proxy.

It loose fork of Flask-Pypi-Proxy


Usage
-----
Installation ::

  python setup.py install
  typi-proxy setup
  typi-proxy

Update or create `~/.pip/pip.conf` ::

  [global]
  index-url = http://localhost:5000/simple/

Update or create `cat ~/.pypirc` ::

  [distutils]
  index-servers =
      pypi

  [pypi]
  repository: http://localhost:5000/pypi/
  username: admin
  password: admin

Update or create `.pydistutils.cfg` ::

  [easy_install]
  index_url = http://localhost:5000/simple/
