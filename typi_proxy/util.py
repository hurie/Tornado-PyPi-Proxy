"""
Created on Aug 15, 2014

@author: Azhar
"""
import hashlib
from distutils.version import LooseVersion
from collections import OrderedDict

import yaml

from . import yaml_anydict


class Versioning(LooseVersion):
    def __init__(self, vstring=None):
        self.full_vstring = vstring

        sss = vstring
        if vstring:
            vs = vstring.split('.')
            for i, v in enumerate(reversed(vs)):
                if v[0].isnumeric():
                    vstring = '.'.join(vs[:-i])
                    break

            ssss = vstring
            vs = vstring.split('-')
            for v in vs:
                if v[0].isnumeric():
                    vstring = v
                    break
            # app.logger.debug([sss, ssss, vstring])
            self.parse(vstring)
        else:
            self.version = []

    def parse(self, vstring):
        # I've given up on thinking I can reconstruct the version string
        # from the parsed tuple -- so I just store the string here for
        # use by __str__
        self.vstring = vstring

        components = []
        for component in self.component_re.split(vstring):
            try:
                components.append(int(component))
            except ValueError:
                components.append(component)

        self.version = components

    def _cmp(self, other):
        if isinstance(other, str):
            other = Versioning(other)

        for v_self, v_other in zip(self.version, other.version):
            if v_self < v_other:
                return -1
            if v_self > v_other:
                return 1

        n_self = len(self.version)
        n_other = len(other.version)

        if n_self < n_other:
            return -1
        if n_self > n_other:
            return 1

        if self.full_vstring < other.full_vstring:
            return -1
        if self.full_vstring > other.full_vstring:
            return 1

        return 0


class Checksum():
    SEPARATOR = ' *'
    CHUNK_SIZE = 64 * 1024

    def __init__(self, path):
        self.path = path
        self.md5file = path / '.md5'

    def format(self, md5, name):
        return ''.join([md5, self.SEPARATOR, str(name)])

    def digest(self, file):
        md5hash = hashlib.md5()
        with file.open('rb') as f:
            chunk = f.read(self.CHUNK_SIZE)
            while chunk:
                md5hash.update(chunk)
                chunk = f.read(self.CHUNK_SIZE)
        return md5hash.hexdigest()

    def update(self, file, digest=None):
        md5data = OrderedDict()

        if self.md5file.exists():
            with self.md5file.open('r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(';') or not line:
                        continue

                    md5, _, name = line.partition(self.SEPARATOR)
                    md5data[name] = md5

        if digest is not None:
            md5data[file.name] = digest
        else:
            md5data[file.name] = self.digest(file)

        hashdata = [self.format(md5, name) for name, md5 in md5data.items()]

        with self.md5file.open('w') as f:
            f.write('\n'.join(hashdata))

    def iter(self):
        if not self.md5file.exists():
            return []

        with self.md5file.open('r') as f:
            for line in f:
                line = line.strip()
                if line.startswith(';') or not line:
                    continue

                md5, _, name = line.partition(' *')
                yield md5, name

    def iter_dir(self):
        for file in self.path.iterdir():
            if not file.is_file() or file.name in ['.cache', '.md5']:
                continue

            md5 = self.digest(file)
            name = file.relative_to(self.path)

            yield md5, file

    def write(self, digests=None, md5file=None):
        if digests is None:
            digests = []
            for md5, file in self.iter_dir():
                digests.append(self.format(md5, file.relative_to(self.path)))

        if md5file is None:
            md5file = self.md5file
        else:
            md5file = self.path / md5file

        with md5file.open('w') as f:
            f.write('\n'.join(digests))


class OrderedDictObj(OrderedDict):
    def __getattr__(self, item):
        try:
            return OrderedDict.__getattribute__(self, item)
        except AttributeError:
            try:
                return self.__getitem__(item)
            except KeyError:
                try:
                    return self.__getitem__(item.replace('-', '_'))
                except KeyError:
                    raise AttributeError("'%s' object has no attribute '%s'", (self.__class__.__name__, item))


class LoaderMapAsOrderedDict(yaml_anydict.LoaderMapAsAnydict, yaml.Loader):
    anydict = OrderedDictObj

    @classmethod  # and call this
    def load_map_as_anydict(cls):
        yaml.add_constructor('tag:yaml.org,2002:map', cls.construct_yaml_map)
