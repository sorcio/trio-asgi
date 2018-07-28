import sys
import argparse
from pathlib import Path
from importlib import import_module
from typing import List, Optional

import trio

from trio_web import serve_tcp as serve_http


class NoAppException(Exception):
    pass


def _load_application(path: str):
    try:
        module_name, app_name = path.split(':', 1)
    except ValueError:
        module_name, app_name = path, 'app'
    except AttributeError:
        raise NoAppException()

    module_path = Path(module_name).resolve()
    sys.path.insert(0, str(module_path.parent))
    if module_path.is_file():
        import_name = module_path.with_suffix('').name
    else:
        import_name = module_path.name
    try:
        module = import_module(import_name)
    except ModuleNotFoundError as error:
        if error.name == import_name:  # type: ignore
            raise NoAppException()
        else:
            raise

    try:
        return eval(app_name, vars(module))
    except NameError:
        raise NoAppException()


def main(sys_args: Optional[List[str]]=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'application',
        help='The application to dispatch to as path.to.module:instance.path',
    )
    parser.add_argument(
        '--host',
        dest='host',
        help='The host/address to bind to',
        default='localhost',
    )
    parser.add_argument(
        '--port',
        dest='port',
        help='The port to bind to',
        default='8080',
    )
    
    args = parser.parse_args(sys_args or sys.argv[1:])
    application = _load_application(args.application)
    
    print("Running on http://{}:{} (CTRL + C to quit)".format(args.host, args.port))


    trio.run(serve_http, application, args.host, int(args.port))

if __name__ == '__main__':
    main()
