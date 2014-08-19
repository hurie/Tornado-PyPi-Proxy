"""
Created on Aug 15, 2014

@author: Azhar
"""
from distutils.version import LooseVersion


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
