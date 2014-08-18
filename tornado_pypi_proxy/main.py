"""
Created on Aug 15, 2014

@author: Azhar
"""
import argparse
from collections import OrderedDict
import logging
import logging.config
import os
from datetime import timedelta

import hashlib
import pathlib
from pathlib import Path
from tornado.log import app_log
import tornado.web
import tornado.ioloop
from tornado_pypi_proxy import yaml_anydict
import tornado_pypi_proxy.template
from tornado_pypi_proxy.handler import SimpleHandler, PackageHandler, CacheHandler, RemoteHandler, PypiHandler
import yaml


logging.basicConfig()
_log = logging.getLogger(__name__)

CONFIG_FILENAME = 'tornado-pypi-proxy.yml'


class Application(tornado.web.Application):
    def __init__(self, cfg, debug=False):
        handlers = [
            (r"/simple/?", SimpleHandler),
            (r"/simple/([^/]+)/?", PackageHandler, {}, 'package'),
            (r"/package/cache/(.+)", CacheHandler, {}, 'cache'),
            (r"/package/remote/(.+)", RemoteHandler, {}, 'remote'),
            (r"/pypi/?", PypiHandler),
        ]

        tornado.web.Application.__init__(self, handlers,
                                         debug=debug,
                                         **cfg)

    def get_cache_path(self, package_name=None):
        base = pathlib.Path(self.settings['package']['cache_dir'])
        if package_name:
            return base / package_name
        return base

    def get_upload_path(self, package_name=None):
        base = pathlib.Path(self.settings['package']['upload_dir'])
        if package_name:
            return base / package_name
        return base

    def normalize_name(self, package_name):
        return package_name.replace('-', '_').lower()


def merge_dict(source, other):
    for key in other:
        if key in source:
            if isinstance(source[key], dict) and isinstance(other[key], dict):
                merge_dict(source[key], other[key])
            elif source[key] != other[key]:
                source[key] = other[key]
        else:
            source[key] = other[key]


def load_config(path):
    file = Path(path).resolve()
    if not file.is_file():
        raise Exception('{} not found'.format(path))

    default_file = Path(tornado_pypi_proxy.template.__file__).resolve().parent / 'config.yml'
    default_cfg = yaml.load(default_file.open('r'))

    try:
        cfg = yaml.load(file.open('r')) or {}
    except:
        raise Exception('Unable to load configuration file {}'.format(file))

    merge_dict(default_cfg, cfg)

    cfg = default_cfg
    cfg['path'] = str(file.parent)
    return cfg


def setup_logging(cfg):
    logging_cfg = cfg['logging']

    path = Path(cfg['path'])
    for handler in logging_cfg['handlers'].values():
        fname = handler.get('filename')
        if fname is None:
            continue

        fpath = Path(fname)
        if fpath.is_absolute():
            continue

        handler['filename'] = str(path / fpath)

    logging.config.dictConfig(logging_cfg)


def setup(args):
    config = os.getcwd() / Path(args.config if 'config' in args else CONFIG_FILENAME)
    root = config.parent

    if not args.replace and config.exists():
        print('{} already exists'.format(config))
        return

    def ask(question, error=None, default=None, info=None, cast=None):
        if default is None:
            question = '-> {}? '.format(question)
        else:
            question = '-> {} [{}]? '.format(question, default)

        if error is None:
            error = 'Invalid value'

        while True:
            res = input(question)
            if res == '':
                if default is not None:
                    res = default
                else:
                    print(info)
                    continue

            if cast is not None:
                try:
                    res = cast(res)
                except:
                    print(error)
                    continue

            return res

    def ask_file(question, default=None):
        if default is None:
            default = '.'

        while True:
            file = ask(question, default=default, cast=Path)
            if file.is_dir():
                print('{} is an existing directory'.format(file))
                continue
            return file

    def ask_path(question, default=None):
        if default is None:
            default = '.'

        while True:
            path = ask(question, default=default, cast=Path)
            if path.exists() and not path.is_dir():
                print('{} is an existing file'.format(path))
                continue
            return path

    class LoaderMapAsOrderedDict(yaml_anydict.LoaderMapAsAnydict, yaml.Loader):
        anydict = OrderedDict

    LoaderMapAsOrderedDict.load_map_as_anydict()
    yaml_anydict.dump_anydict_as_map(OrderedDict)

    template_file = Path(tornado_pypi_proxy.template.__file__).resolve().parent / 'config.yml'
    template_cfg = yaml.load(template_file.open('r'), Loader=LoaderMapAsOrderedDict)

    try:
        port = ask('Port to listen', 'Port range is 0 - 65535', 5000, cast=int)

        cache_dir = ask_path('Package cache directory', default=template_cfg['package']['cache_dir'])
        upload_dir = ask_path('Uploaded package directory', default=template_cfg['package']['upload_dir'])
        pid_path = ask_file('Application pid file', default=template_cfg['daemon']['pid'])
        log_dir = ask_path('Application log path', default='.')
    except KeyboardInterrupt:
        print()
        print('Setup canceled!')
        return

    cache_dir = root / cache_dir
    if not cache_dir.exists():
        cache_dir.mkdir(parents=True)
    cache_dir = cache_dir.resolve()

    upload_dir = root / upload_dir
    if not upload_dir.exists():
        upload_dir.mkdir(parents=True)
    upload_dir = upload_dir.resolve()

    pid_path = root / pid_path
    if not pid_path.parent.exists():
        pid_path.parent.mkdir(parents=True)
    pid_path = pid_path.parent.resolve() / pid_path.name

    log_dir = root / log_dir
    if not log_dir.exists():
        log_dir.mkdir(parents=True)
    log_dir = log_dir.resolve()

    template_cfg['server']['port'] = port
    template_cfg['package']['cache_dir'] = str(cache_dir)
    template_cfg['package']['upload_dir'] = str(upload_dir)
    template_cfg['daemon']['pid'] = str(pid_path)

    for handler in template_cfg['logging']['handlers'].values():
        fname = handler.get('filename')
        if fname is None:
            continue

        fpath = Path(fname)
        if fpath.is_absolute():
            continue

        handler['filename'] = str(log_dir / fpath)

    print('write configuration to {}'.format(config))
    yaml.dump(template_cfg, config.open('w'), default_flow_style=False)


def execute(args, cfg, daemon=None):
    # use sub function since daemonocle does'nt support args nor kwargs on worker property
    def worker():
        # setup logging, on start it have to do here since all fd will close by daemonocle
        setup_logging(cfg)

        application = Application(cfg, args.debug)

        # setup logging level if specify
        if args.level is not None:
            logging.root.setLevel(args.level)

        # listen to port
        port = cfg['server']['port']
        try:
            application.listen(port)
            app_log.info('listening port %s', port)
        except OSError:
            app_log.error('unable to listen port %s', port)
            return

        # start main loop
        ioloop = tornado.ioloop.IOLoop.instance()
        try:
            ioloop.start()
        except KeyboardInterrupt:
            app_log.info('Keyboard interrupt')
        except SystemExit:
            pass
        except Exception:
            app_log.exception('Error')
            raise

        ioloop.stop()
        app_log.info('Closed')

    if args.cmd == 'start':
        if daemon is None:
            # prevent block for IO allowed ctrl-c to pass
            # http://stackoverflow.com/a/9578595
            def set_ping(timeout):
                ioloop = tornado.ioloop.IOLoop.instance()
                ioloop.add_timeout(timeout, lambda: set_ping(timeout))

            set_ping(timedelta(seconds=0.5))

            worker()
        else:
            daemon.worker = worker
            daemon.detach = not args.foreground and not args.debug
            daemon.start()
        return True

    setup_logging(cfg)
    if args.cmd in ['stop', 'restart', 'status']:
        if daemon is None:
            return False

        args.debug = False
        daemon.worker = worker

        method = getattr(daemon, args.cmd)
        method()
    return True


def hash_pkg(args, cfg):
    try:
        for base in [Path(cfg['package']['cache_dir']),
                     Path(cfg['package']['upload_dir'])]:

            digest_base = []
            for path in base.iterdir():
                if not path.is_dir():
                    continue
                _log.info('scanning %s', path)

                digests = []
                for file in path.iterdir():
                    if not file.is_file() or file.name in ['.cache', '.md5']:
                        continue

                    md5 = hashlib.md5(file.open('rb').read()).hexdigest()

                    digests.append('{} *{}'.format(md5, file.relative_to(path)))
                    digest_base.append('{} *{}'.format(md5, file.relative_to(base)))

                md5file = path / '.md5'
                with md5file.open('w') as f:
                    f.write('\n'.join(digests))

            md5file = base / 'checksums.md5'
            with md5file.open('w') as f:
                f.write('\n'.join(digest_base))

    except FileNotFoundError as e:
        _log.error(e)


def main():
    # daemon mode is optional if OS is not windows and daemonocle is found
    if os.name == 'nt':
        daemonocle = None
    else:
        try:
            import daemonocle
        except ImportError:
            daemonocle = None
    daemon = None

    # base parser
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=CONFIG_FILENAME)
    parser.add_argument('--logging', dest='level',
                        choices=[v for k, v in logging._levelNames.items() if isinstance(k, int) and k != 0])

    subparsers = parser.add_subparsers()

    # start and daemon related command
    cmd = subparsers.add_parser('start')
    cmd.add_argument('--debug', default=False, action='store_true')
    cmd.set_defaults(cmd='start')

    if daemonocle is not None:
        cmd.add_argument('--foreground', '-f', default=False, action='store_true')

        cmd = subparsers.add_parser('stop')
        cmd.set_defaults(cmd='stop')

        cmd = subparsers.add_parser('restart')
        cmd.set_defaults(cmd='restart')

        cmd = subparsers.add_parser('stop')
        cmd.set_defaults(cmd='stop')

        cmd = subparsers.add_parser('status')
        cmd.set_defaults(cmd='status')

    # configuration setup
    cmd = subparsers.add_parser('setup')
    cmd.add_argument('--replace', default=False, action='store_true')
    cmd.set_defaults(cmd='setup')

    cmd = subparsers.add_parser('calculate')
    cmd.set_defaults(cmd='calculate')

    # parse
    args = parser.parse_args()

    # default command is start if not specify
    if 'cmd' not in args:
        args.cmd = 'start'
        args.foreground = False
        args.debug = False

    # stop here if this ask for setup
    if args.cmd == 'setup':
        setup(args)
        return

    # load configuration
    try:
        cfg = load_config(args.config)
    except Exception as e:
        parser.error(e)
        raise

    # if daemonocle is found setup daemon mode
    if daemonocle is not None:
        try:
            pidfile = Path(cfg['daemon']['pid'])
            if not pidfile.is_absolute():
                pidfile = (cfg['path'] / pidfile)
        except Exception as e:
            parser.error(e)
            raise

        daemon = daemonocle.Daemon(
            pidfile=str(pidfile),
            close_open_files=True,
        )

    # execute command
    if args.cmd == 'calculate':
        setup_logging(cfg)
        hash_pkg(args, cfg)

    elif not execute(args, cfg, daemon):
        parser.error('unable to create daemon')


if __name__ == "__main__":
    main()
