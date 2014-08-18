"""
Created on Aug 15, 2014

@author: Azhar
"""
import pickle
from time import time
from urllib.parse import urljoin, urlsplit, parse_qs, urlunsplit, urlencode

from collections import namedtuple, OrderedDict
import hashlib
from os.path import getmtime, basename
from bs4 import BeautifulSoup
from pathlib import Path
from tornado.httpclient import AsyncHTTPClient
from tornado.log import app_log
import tornado.web
import tornado.gen
from tornado_pypi_proxy.streaming_upload import StreamingFormDataHandler
from tornado_pypi_proxy.util import Versioning


PackageData = namedtuple('PackageData', ['name', 'md5', 'link', 'cache'])


class PypiHandler(StreamingFormDataHandler):
    def prepare(self):
        StreamingFormDataHandler.prepare(self)

        self._pkg_md5 = None
        self._pkg_name = None
        self._pkg_file = None
        self._pkg_diggest = None
        self._pkg_fd = None

        self._need_md5 = False
        self._need_rename = False

    def write_md5(self):
        app_log.debug('recv: %r -- send: %r', self._pkg_diggest.hexdigest(), self._pkg_md5)
        if self._pkg_diggest.hexdigest() != self._pkg_md5:
            raise tornado.web.HTTPError(417)

        app_log.debug('write md5')
        with open(str(self._pkg_file) + '.md5', 'w') as f:
            f.write(self._pkg_md5)

        self._need_md5 = False

    def on_content_begin(self, data):
        # filename = str(self._disp_params['filename'])
        filename = self._disp_params['filename']
        if self._pkg_name is None:
            self._pkg_file = self.application.get_upload_path() / filename
            self._need_rename = True
        else:
            self._pkg_file = self.application.get_upload_path() / self._pkg_name / filename
            if not self._pkg_file.parent.exists():
                self._pkg_file.parent.mkdir()

        app_log.debug('begin handle content file %s', filename)
        self._pkg_diggest = hashlib.md5()
        self._pkg_fd = self._pkg_file.open('wb')
        self.on_content_data(data)

    def on_content_data(self, data):
        app_log.debug('write content %d byte(s) to %s', len(data), str(self._pkg_file))
        self._pkg_fd.write(data)
        self._pkg_diggest.update(data)

    def on_name_end(self):
        self._pkg_name = self._disp_buffer.decode()
        if self._need_rename:
            app_log.debug('renaming file')
            pkg_file = self.application.get_upload_path() / self._pkg_name / self._pkg_file.name
            if not pkg_file.parent.exists():
                pkg_file.parent.mkdir()

            self._pkg_file.rename(pkg_file)

            md5old = self._pkg_file.withsuffix(self._pkg_file.suffix + '.md5')
            if md5old.exist():
                md5new = pkg_file.withsuffix(pkg_file.suffix + '.md5')
                md5old.rename(md5new)

    def on_md5_digest_end(self):
        self._pkg_md5 = self._disp_buffer.decode()
        if self._need_md5:
            app_log.debug('writing md5')
            self.write_md5()

    def on_content_end(self):
        app_log.debug('finalize content')
        self._pkg_fd.close()
        self._pkg_fd = None

        if self._pkg_md5 is None:
            self._need_md5 = True
        else:
            self.write_md5()

    def on_finish(self):
        if self._pkg_fd is not None:
            self._pkg_fd.close()

        # md5_digest content not found
        app_log.warn('md5_digest disposition not found')
        self._pkg_md5 = self._pkg_diggest.hexdigest()
        self.write_md5()


class CacheHandler(tornado.web.StaticFileHandler):
    def initialize(self):
        tornado.web.StaticFileHandler.initialize(self, str(self.application.get_upload_path()))

    def set_extra_headers(self, path):
        package_file = Path(path)
        self.add_header('Content-Disposition', 'attachment; filename="{}"'.format(package_file.name))

    def validate_absolute_path(self, root, absolute_path):
        package_file = Path(absolute_path)
        if not package_file.exists():
            package_file = self.application.get_cache_path() / package_file.relative_to(
                self.application.get_upload_path())
            self.root = str(package_file.parent)
        return tornado.web.StaticFileHandler.validate_absolute_path(self, self.root, str(package_file))


class RemoteHandler(tornado.web.RequestHandler):
    def write_md5(self, file, md5=None):
        with file.with_suffix(file.suffix + '.md5').open('w') as f:
            if md5 is None:
                md5 = hashlib.md5(file.open('rb').read())
            f.write(md5.hexdigest())

    @tornado.web.asynchronous
    def get(self, path):
        cache_file = self.application.get_cache_path() / path

        upload_file = self.application.get_upload_path() / path
        if upload_file.exists():
            self.write_md5(upload_file)
            self.redirect(self.reverse_url('cache', path), permanent=True)
            return

        if cache_file.exists():
            self.write_md5(cache_file)
            self.redirect(self.reverse_url('cache', path), permanent=True)
            return

        link = self.get_argument('link', None)
        if link is None:
            raise tornado.web.HTTPError(404)

        if not cache_file.parent.exists():
            cache_file.parent.mkdir()

        self._file = cache_file
        self._md5 = hashlib.md5()
        self._fd = cache_file.open('wb')

        app_log.debug('fetch %s', link)

        client = AsyncHTTPClient()
        client.fetch(link,
                     request_timeout=self.application.settings['transload']['timeout'],
                     header_callback=self.process_header,
                     streaming_callback=self.process_body,
                     callback=self.process_finish)

    def process_header(self, line):
        header = line.strip()
        # app_log.debug('header: %r', header)
        if header:
            if ':' not in header:
                return

            key, val = [x.strip() for x in header.split(':', 1)]
            if key.lower() in ['content-length', 'content-type']:
                self.set_header(key, val)
            return

        self.add_header('Content-Disposition', 'attachment; filename="{}"'.format(self._file.name))
        self.flush()
        # app_log.debug('header finish')

    def process_body(self, chunk):
        # app_log.debug('got %d byte(s) for %s', len(chunk), self._file)
        self._md5.update(chunk)
        self._fd.write(chunk)
        self.write(chunk)
        self.flush()

    def process_finish(self, response):
        app_log.debug('%s done', self._file)
        self.write_md5(self._file, self._md5)
        self.finish()


class SimpleHandler(tornado.web.RequestHandler):
    @tornado.web.addslash
    @tornado.web.asynchronous
    def get(self):
        packages = []
        for file in self.application.get_upload_path().iterdir():
            packages.append(file.name)

        for file in self.application.get_cache_path().iterdir():
            if file.name not in packages:
                packages.append(file.name)

        packages.sort(key=str.lower)

        self.write('''\
<html>
<head>
    <title>Cached and uploaded packages</title>
</head>
<body>''')

        for package in packages:
            self.write('''\
<a href="{url}">{name}</a><br>'''.format(
                url=self.reverse_url('package', package)[:-1],
                name=package
            ))

        self.finish('''\
</body>
</html>
        ''')


class PackageHandler(tornado.web.RequestHandler):
    source_extensions = ('.tar.gz', '.tar.bz2', '.tar', '.zip', '.tgz', '.tbz', '.tbz2',)
    binary_extensions = ('.egg', '.exe', '.msi', '.whl',)
    others_extensions = ('.pybundle',)

    extensions = source_extensions + binary_extensions + others_extensions

    def prepare(self):
        self.reload_only = False
        self.cfg = self.application.settings['index']

    def is_archive(self, url):
        if url is None:
            return False

        url = url.lower()
        return url.endswith(self.extensions)

    def add_version(self, name, md5, url, cache, href):
        data = PackageData(name, md5, url, cache)
        if data.name not in self.package_versions and data.name not in self.local_versions:
            app_log.debug('add %s', href)
            self.package_versions[data.name] = data
            self.write_upstream(data)
            return data
        # else:
        # app_log.debug('added %s', href)
        return None

    def add_link(self, url, split, base, href):
        if self._finished or self.depth >= self.cfg['depth']:
            return

        strip_url = urlunsplit((split.scheme, split.netloc, split.path, None, None))
        if strip_url in self.visited_links:
            return
        self.visited_links.add(strip_url)

        if split.netloc != base.netloc or not split.path.startswith(base.path):
            return
        app_log.debug('found %s', href)
        self.links.append((url, self.depth + 1))

    def parse_remote(self, response):
        if self._finished:
            app_log.info('connection canceled')
            return

        try:
            if response.code != 200:
                app_log.warning('Error while getting proxy info for: %s '
                                'Errors details: (%s: %s) %s', response.effective_url,
                                response.code, response.reason, response.body)
                return

            base_url = response.effective_url
            base = urlsplit(base_url)

            content_type = response.headers.get('content-type', '')
            if content_type in ('application/x-gzip',):
                # in this case the URL was a redirection to download
                # a package. For example, sourceforge.
                self.add_version(basename(base.path), '', base_url, 0, base_url)
                return

            if not response.body:
                return

            app_log.debug('parse %s', base_url)

            soup = BeautifulSoup(response.body)
            for anchor in soup.find_all('a'):
                href = anchor.get('href')
                if not href:
                    continue

                current_url = urljoin(base_url, href)
                current = urlsplit(current_url)

                if self.is_archive(current.path):
                    self.add_version(basename(current.path), '', current_url, 0, href)
                else:
                    self.add_link(current_url, current, base, href)
        finally:
            self.fetch_next()

    def parse_index(self, response):
        if response.code != 200:
            app_log.warning('Error while getting proxy info for: %s '
                            'Errors details: (%s: %s) %s', response.effective_url,
                            response.code, response.reason, response.body)
            self.finalize_upstream()
            return

        if self._finished:
            app_log.info('connection canceled')
            return

        base_url = response.effective_url
        app_log.debug('parse %s', base_url)

        self.package_versions = OrderedDict()
        self.visited_links = set()

        soup = BeautifulSoup(response.body)

        for panchor in soup.find_all('a'):
            if panchor.get('rel') and panchor.get('rel')[0] == 'homepage':
                # skip getting information on the project homepage
                continue

            href = panchor.get('href')
            href = urljoin(base_url, href)
            url = urlsplit(href)

            if self.is_archive(url.path):
                pkg_name = basename(url.path)

                md5 = None
                if url.fragment:
                    fragment = parse_qs(url.fragment)
                    if 'md5' in fragment:
                        md5 = fragment['md5'][0]

                self.add_version(pkg_name, md5, href, 0, href)

            elif href not in self.visited_links and self.cfg['depth'] > 0:
                app_log.debug('found %s', href)
                self.links.append((href, 1))
                self.visited_links.add(href)

        self.fetch_next()

    def fetch_index(self, package_name, local_versions):
        index_url = self.cfg['base']
        if not index_url:
            self.finalize_upstream()
            return

        self.links = []
        self.depth = 0
        self.package_name = package_name
        self.local_versions = local_versions
        self.client = AsyncHTTPClient()

        url = urljoin(index_url, package_name + '/')
        if not url.endswith('/'):
            url += '/'

        app_log.debug('fetch %s', url)
        self.client_fetch = self.client.fetch(url, callback=self.parse_index)

    def fetch_next(self):
        if self._finished:
            return

        while self.links:
            if not self.reload_only:
                self.flush()

            url, depth = self.links.pop(0)
            app_log.debug('fetch %s', url)

            self.depth = depth
            self.client_fetch = self.client.fetch(url, callback=self.parse_remote)
            break
        else:
            self.finalize_upstream()

            app = self.application
            package_path = app.get_cache_path(self.package_name)
            self.save_cache(package_path, list(self.package_versions.values()))

    def load_local(self, package_name):
        files = {}

        for cache, package_folder in [(1, self.application.get_cache_path(package_name)),
                                      (2, self.application.get_upload_path(package_name))]:
            if not package_folder.exists():
                continue

            app_log.debug('loading package %s in %s',
                          package_name, package_folder)

            for filename in package_folder.glob('*.md5'):
                with filename.open() as f:
                    md5 = f.read()

                name = filename.stem
                data = PackageData(name, md5, None, cache)
                files[name] = data

        return list(files.values())

    def load_cache(self, package_path):
        lifetime = self.application.settings['index']['lifetime'] * 60 * 60

        cache_file = package_path / '.cache'
        if cache_file.exists() and (time() - getmtime(str(cache_file))) <= lifetime:
            try:
                with cache_file.open('rb') as f:
                    return pickle.load(f)
            except:
                pass
        return None

    def save_cache(self, package_path, versions):
        cache_file = package_path / '.cache'
        if not package_path.exists():
            package_path.mkdir()

        with cache_file.open('wb') as f:
            pickle.dump(versions, f)

        return versions

    @tornado.web.addslash
    @tornado.web.asynchronous
    def get(self, package_name):
        app = self.application
        package_name = app.normalize_name(package_name)
        package_path = app.get_cache_path(package_name)

        self.write('''\
<html>
<head>
    <title>Links for {package_name}</title>
</head>
<body>'''.format(package_name=package_name))

        local_versions = self.load_local(package_name)
        local_versions.sort(key=lambda v: Versioning(v.name), reverse=True)

        for cache, title in [(2, 'Uploaded'),
                             (1, 'Cached')]:
            self.write('''
<h2>{title}</h2>
<ul>'''.format(title=title))
            for data in local_versions:
                if data.cache != cache:
                    continue

                self.write('''
    <li>
        <a href="{url}#md5={md5}">{name}</a>
    </li>'''.format(url=self.reverse_url('cache', '/'.join([package_name, data.name])),
                    md5=data.md5,
                    name=data.name))

            self.write('''
</ul>''')

        self.write('''
<h2>
    Upstream
    <form method="post" style="display: inline">
        <input type="hidden" name="reload" value="1"><input type="submit" value="reload">
    </form>
</h2>
<ul>''')
        self.flush()

        local_versions = {x.name for x in local_versions}

        versions = self.load_cache(package_path)
        if versions is None:
            self.fetch_index(package_name, local_versions)
            return
        # else:
        # app_log.debug(versions)

        self.package_name = package_name
        for data in versions:
            if data.name not in local_versions:
                self.write_upstream(data)

        self.finalize_upstream()

    def write_upstream(self, data):
        if self.reload_only:
            return

        self.write('''
    <li>
        <a href="{url}?{link}">{name}</a>
    </li>'''.format(url=self.reverse_url('remote', '/'.join([self.package_name, data.name])),
                    link=urlencode({'link': data.link}),
                    name=data.name))

    def finalize_upstream(self):
        if self._finished:
            return

        if self.reload_only:
            self.redirect(self.reverse_url('package', self.package_name)[:-1])
        else:
            self.finish('''
</ul>
</body>
</html>''')

    @tornado.web.asynchronous
    def post(self, package_name):
        app = self.application
        package_name = app.normalize_name(package_name)

        self.reload_only = True
        self.fetch_index(package_name, {x.name for x in self.load_local(package_name)})

    def on_connection_close(self):
        app_log.debug('client connection close')
        self.finish()
