#!/usr/bin/python3

import sys

from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ArgumentParser

from db import Snapshot

# some debugging
_debug = 0
_log = ModuleLogger(globals())

# parse the command line arguments
parser = ArgumentParser(description=__doc__)

# database file name
parser.add_argument("dbname", help="database file name")
parser.add_argument("devid", help="device identifier", nargs="?", default="-")
parser.add_argument("objid", help="object identifier", nargs="?", default="-")
parser.add_argument("propid", help="property identifier", nargs="?", default="-")

args = parser.parse_args()

if _debug:
    _log.debug("initialization")
if _debug:
    _log.debug("    - args: %r", args)

snapshot = Snapshot(args.dbname)

_log.debug("running")

for (devid, objid, propid, value) in snapshot.items(
    devid=args.devid if args.devid != "-" else None,
    objid=args.objid if args.objid != "-" else None,
    propid=args.propid if args.propid != "-" else None,
):
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

snapshot.close()
