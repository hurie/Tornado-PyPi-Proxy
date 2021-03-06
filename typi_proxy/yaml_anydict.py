# http://pyyaml.org/ticket/29#comment:11
# yaml_anydict.py
import yaml
from yaml.constructor import MappingNode, ConstructorError


def dump_anydict_as_map(anydict):
    yaml.add_representer(anydict, _represent_dictorder)


def _represent_dictorder(self, data):
    return self.represent_mapping('tag:yaml.org,2002:map', data.items())


class LoaderMapAsAnydict(object):
    """inherit + Loader"""
    anydict = None  # override

    @classmethod  # and call this
    def load_map_as_anydict(cls):
        yaml.add_constructor('tag:yaml.org,2002:map', cls.construct_yaml_map)

    'copied from constructor.BaseConstructor, replacing {} with self.anydict()'

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, MappingNode):
            raise ConstructorError(None, None,
                                   "expected a mapping node, but found %s" % node.id,
                                   node.start_mark)
        mapping = self.anydict()
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError as exc:
                raise ConstructorError("while constructing a mapping", node.start_mark,
                                       "found unacceptable key (%s)" % exc, key_node.start_mark)
            value = self.construct_object(value_node, deep=deep)
            mapping[key] = value
        return mapping

    def construct_yaml_map(self, node):
        data = self.anydict()
        yield data
        value = self.construct_mapping(node)
        data.update(value)


'''usage:
   ...dictOrder = whatever-dict-thing

   class Loader( yaml_anydict.Loader_map_as_anydict, yaml.Loader):
       anydict = dictOrder
   Loader.load_map_as_anydict()
   yaml_anydict.dump_anydict_as_map( dictOrder)
   ...
   p = yaml.load( a, Loader= Loader)
'''
