#!/usr/bin/python3

import sys
import shelve

from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ArgumentParser

# some debugging
_debug = 0
_log = ModuleLogger(globals())

# parse the command line arguments
parser = ArgumentParser(description=__doc__)

# database file name
parser.add_argument("dbname", help="database file name")
parser.add_argument("devid", help="device identifier", nargs="?", default="-")
parser.add_argument("objid", help="database file name", nargs="?", default="-")
parser.add_argument("propid", help="database file name", nargs="?", default="-")

args = parser.parse_args()

if _debug:
    _log.debug("initialization")
if _debug:
    _log.debug("    - args: %r", args)

db = shelve.open(sys.argv[1], flag="r")

_log.debug("running")

for key, value in db.items():
    devid, objid, propid = eval(key)
    if (args.devid != "-") and (int(args.devid) != devid):
        continue
    if (args.objid != "-") and (args.objid != objid):
        continue
    if (args.propid != "-") and (args.propid != propid):
        continue
    if hasattr(value, "debug_contents"):
        print("{} {} {}".format(devid, objid, propid))
        value.debug_contents(file=sys.stdout)
    elif isinstance(value, list):
        print("{} {} {}".format(devid, objid, propid))
        for i, x in enumerate(value):
            print("    [{}]: {}".format(i, x))
            if hasattr(x, "debug_contents"):
                x.debug_contents(file=sys.stdout, indent=4)
    else:
        print("{} {} {} {}".format(devid, objid, propid, value))

_log.debug("fini")

db.close()
