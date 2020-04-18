#!/usr/bin/python3

"""
This sample application presents itself as a router and a device sitting on an
IP network connected to a VLAN with one or more devices on it.

A "console" is attached to the IP device which supports the whois, iam, read
and write commands (and rtn when it's needed).
"""

import sys
import shelve
import argparse

from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ArgumentParser
from bacpypes.consolecmd import ConsoleCmd

from bacpypes.core import run, deferred, enable_sleeping
from bacpypes.comm import bind

from bacpypes.iocb import IOCB

from bacpypes.pdu import Address, LocalBroadcast, GlobalBroadcast
from bacpypes.netservice import NetworkServiceAccessPoint, NetworkServiceElement
from bacpypes.bvllservice import (
    BIPSimple,
    BIPForeign,
    BIPBBMD,
    AnnexJCodec,
    UDPMultiplexer,
)

from bacpypes.app import ApplicationIOController
from bacpypes.appservice import StateMachineAccessPoint, ApplicationServiceAccessPoint
from bacpypes.local.device import LocalDeviceObject
from bacpypes.service.device import WhoIsIAmServices
from bacpypes.service.object import (
    ReadWritePropertyServices,
    ReadWritePropertyMultipleServices,
)

from bacpypes.vlan import Network, Node

from bacpypes.apdu import (
    SimpleAckPDU,
    ReadPropertyRequest,
    ReadPropertyACK,
    WritePropertyRequest,
    WhoIsRequest,
    IAmRequest,
)
from bacpypes.primitivedata import (
    Null,
    Atomic,
    Boolean,
    Unsigned,
    Integer,
    Real,
    Double,
    OctetString,
    CharacterString,
    BitString,
    Date,
    Time,
    ObjectIdentifier,
)
from bacpypes.constructeddata import Array, Any, AnyAtomic
from bacpypes.object import get_object_class, get_datatype

# some debugging
_debug = 0
_log = ModuleLogger(globals())

# globals
args = None
this_device = None
this_application = None

# errors
class ConfigurationError(RuntimeError):
    pass


@bacpypes_debugging
class Snapshot:
    def __init__(self, filename, flag="r"):
        try:
            self.shelf = shelve.open(filename, flag=flag)
        except:
            raise ConfigurationError(f"unable to open database: {filename!r}")

    def __getitem__(self, item):
        return self.shelf[str(item)]

    def __setitem__(self, item, value):
        self.shelf[str(item)] = value

    def close(self):
        self.shelf.close()

    def items(self, devid=None, objid=None, propid=None):
        if _debug:
            Snapshot._debug("items %r %r %r", devid, objid, propid)

        objtype, objinst = None, None
        if objid is not None:
            objtype, objinst = (objid + ":").split(":")[:2]

        for k, v in self.shelf.items():
            d, o, p = eval(k)

            # match the device instance number
            if (devid is not None) and (d != devid):
                continue

            # match the object identifer, 'x' or 'x:y'
            if objid is not None:
                # match the whole object identifier
                if objinst and o != objid:
                    continue

                # match the type
                ot, oi = o.split(":")
                if o != ot:
                    continue

            # match the property identifier
            if (propid is not None) and (p != propid):
                continue
            yield (d, o, p, v)


@bacpypes_debugging
class VLANConsoleCmd(ConsoleCmd):
    def do_read(self, args):
        """read <addr> <objid> <prop> [ <indx> ]"""
        args = args.split()
        if _debug:
            VLANConsoleCmd._debug("do_read %r", args)

        try:
            addr, obj_id, prop_id = args[:3]
            obj_id = ObjectIdentifier(obj_id).value

            datatype = get_datatype(obj_id[0], prop_id)
            if not datatype:
                raise ValueError("invalid property for object type")

            # build a request
            request = ReadPropertyRequest(
                objectIdentifier=obj_id, propertyIdentifier=prop_id,
            )
            request.pduDestination = Address(addr)

            if len(args) == 4:
                request.propertyArrayIndex = int(args[3])
            if _debug:
                VLANConsoleCmd._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug:
                VLANConsoleCmd._debug("    - iocb: %r", iocb)

            # give it to the application
            deferred(this_application.request_io, iocb)

            # wait for it to complete
            iocb.wait()

            # do something for success
            if iocb.ioResponse:
                apdu = iocb.ioResponse

                # should be an ack
                if not isinstance(apdu, ReadPropertyACK):
                    if _debug:
                        VLANConsoleCmd._debug("    - not an ack")
                    return

                # find the datatype
                datatype = get_datatype(
                    apdu.objectIdentifier[0], apdu.propertyIdentifier
                )
                if _debug:
                    VLANConsoleCmd._debug("    - datatype: %r", datatype)
                if not datatype:
                    raise TypeError("unknown datatype")

                # special case for array parts, others are managed by cast_out
                if issubclass(datatype, Array) and (
                    apdu.propertyArrayIndex is not None
                ):
                    if apdu.propertyArrayIndex == 0:
                        value = apdu.propertyValue.cast_out(Unsigned)
                    else:
                        value = apdu.propertyValue.cast_out(datatype.subtype)
                else:
                    value = apdu.propertyValue.cast_out(datatype)
                if _debug:
                    VLANConsoleCmd._debug("    - value: %r", value)

                sys.stdout.write(str(value) + "\n")
                if hasattr(value, "debug_contents"):
                    value.debug_contents(file=sys.stdout)
                sys.stdout.flush()

            # do something for error/reject/abort
            if iocb.ioError:
                sys.stdout.write(str(iocb.ioError) + "\n")

        except Exception as error:
            VLANConsoleCmd._exception("exception: %r", error)

    def do_write(self, args):
        """write <addr> <objid> <prop> <value> [ <indx> ] [ <priority> ]"""
        args = args.split()
        VLANConsoleCmd._debug("do_write %r", args)

        try:
            addr, obj_id, prop_id = args[:3]
            obj_id = ObjectIdentifier(obj_id).value
            value = args[3]

            indx = None
            if len(args) >= 5:
                if args[4] != "-":
                    indx = int(args[4])
            if _debug:
                VLANConsoleCmd._debug("    - indx: %r", indx)

            priority = None
            if len(args) >= 6:
                priority = int(args[5])
            if _debug:
                VLANConsoleCmd._debug("    - priority: %r", priority)

            # get the datatype
            datatype = get_datatype(obj_id[0], prop_id)
            if _debug:
                VLANConsoleCmd._debug("    - datatype: %r", datatype)

            # change atomic values into something encodeable, null is a special case
            if value == "null":
                value = Null()
            elif issubclass(datatype, AnyAtomic):
                dtype, dvalue = value.split(":", 1)
                if _debug:
                    VLANConsoleCmd._debug("    - dtype, dvalue: %r, %r", dtype, dvalue)

                datatype = {
                    "b": Boolean,
                    "u": lambda x: Unsigned(int(x)),
                    "i": lambda x: Integer(int(x)),
                    "r": lambda x: Real(float(x)),
                    "d": lambda x: Double(float(x)),
                    "o": OctetString,
                    "c": CharacterString,
                    "bs": BitString,
                    "date": Date,
                    "time": Time,
                    "id": ObjectIdentifier,
                }[dtype]
                if _debug:
                    VLANConsoleCmd._debug("    - datatype: %r", datatype)

                value = datatype(dvalue)
                if _debug:
                    VLANConsoleCmd._debug("    - value: %r", value)

            elif issubclass(datatype, Atomic):
                if datatype is Integer:
                    value = int(value)
                elif datatype is Real:
                    value = float(value)
                elif datatype is Unsigned:
                    value = int(value)
                value = datatype(value)
            elif issubclass(datatype, Array) and (indx is not None):
                if indx == 0:
                    value = Integer(value)
                elif issubclass(datatype.subtype, Atomic):
                    value = datatype.subtype(value)
                elif not isinstance(value, datatype.subtype):
                    raise TypeError(
                        "invalid result datatype, expecting %s"
                        % (datatype.subtype.__name__,)
                    )
            elif not isinstance(value, datatype):
                raise TypeError(
                    "invalid result datatype, expecting %s" % (datatype.__name__,)
                )
            if _debug:
                VLANConsoleCmd._debug(
                    "    - encodeable value: %r %s", value, type(value)
                )

            # build a request
            request = WritePropertyRequest(
                objectIdentifier=obj_id, propertyIdentifier=prop_id
            )
            request.pduDestination = Address(addr)

            # save the value
            request.propertyValue = Any()
            try:
                request.propertyValue.cast_in(value)
            except Exception as error:
                VLANConsoleCmd._exception("WriteProperty cast error: %r", error)

            # optional array index
            if indx is not None:
                request.propertyArrayIndex = indx

            # optional priority
            if priority is not None:
                request.priority = priority

            if _debug:
                VLANConsoleCmd._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug:
                VLANConsoleCmd._debug("    - iocb: %r", iocb)

            # give it to the application
            deferred(this_application.request_io, iocb)

            # wait for it to complete
            iocb.wait()

            # do something for success
            if iocb.ioResponse:
                # should be an ack
                if not isinstance(iocb.ioResponse, SimpleAckPDU):
                    if _debug:
                        VLANConsoleCmd._debug("    - not an ack")
                    return

                sys.stdout.write("ack\n")

            # do something for error/reject/abort
            if iocb.ioError:
                sys.stdout.write(str(iocb.ioError) + "\n")

        except Exception as error:
            VLANConsoleCmd._exception("exception: %r", error)

    def do_whois(self, args):
        """whois [ <addr>] [ <lolimit> <hilimit> ]"""
        args = args.split()
        if _debug:
            VLANConsoleCmd._debug("do_whois %r", args)

        try:
            # build a request
            request = WhoIsRequest()
            if (len(args) == 1) or (len(args) == 3):
                request.pduDestination = Address(args[0])
                del args[0]
            else:
                request.pduDestination = GlobalBroadcast()

            if len(args) == 2:
                request.deviceInstanceRangeLowLimit = int(args[0])
                request.deviceInstanceRangeHighLimit = int(args[1])
            if _debug:
                VLANConsoleCmd._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug:
                VLANConsoleCmd._debug("    - iocb: %r", iocb)

            # give it to the application
            this_application.request_io(iocb)

        except Exception as err:
            VLANConsoleCmd._exception("exception: %r", err)

    def do_iam(self, args):
        """iam"""
        args = args.split()
        if _debug:
            VLANConsoleCmd._debug("do_iam %r", args)
        global this_device

        try:
            # build a request
            request = IAmRequest()
            request.pduDestination = GlobalBroadcast()

            # set the parameters from the device object
            request.iAmDeviceIdentifier = this_device.objectIdentifier
            request.maxAPDULengthAccepted = this_device.maxApduLengthAccepted
            request.segmentationSupported = this_device.segmentationSupported
            request.vendorID = this_device.vendorIdentifier
            if _debug:
                VLANConsoleCmd._debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug:
                VLANConsoleCmd._debug("    - iocb: %r", iocb)

            # give it to the application
            this_application.request_io(iocb)

        except Exception as err:
            VLANConsoleCmd._exception("exception: %r", err)

    def do_rtn(self, args):
        """rtn <addr> <net> ... """
        args = args.split()
        if _debug:
            VLANConsoleCmd._debug("do_rtn %r", args)

        # provide the address and a list of network numbers
        router_address = Address(args[0])
        network_list = [int(arg) for arg in args[1:]]

        # pass along to the service access point
        this_application.nsap.update_router_references(
            None, router_address, network_list
        )


#
#   ReplayApplication
#


@bacpypes_debugging
class ReplayApplication(
    ApplicationIOController,
    WhoIsIAmServices,
    ReadWritePropertyServices,
    ReadWritePropertyMultipleServices,
):
    def __init__(self, device_id, aseID=None):
        if _debug:
            ReplayApplication._debug("__init__ %r aseID=%r", device_id, aseID)
        global args, snapshot

        # save our device identifier for searching later
        self.device_id = device_id
        device_object_id = "device:{}".format(device_id)

        # extract some pieces
        try:
            device_object_name = snapshot[device_id, device_object_id, "objectName"]
        except KeyError:
            raise ConfigurationError(f"device {device_id}: object name not found")
        try:
            vendor_identifier = snapshot[
                device_id, device_object_id, "vendorIdentifier"
            ]
        except KeyError:
            raise ConfigurationError(f"device {device_id}: vendor identifier not found")

        # build a device object from the
        vlan_device = LocalDeviceObject(
            objectName=device_object_name,
            objectIdentifier=("device", device_id),
            vendorIdentifier=vendor_identifier,
        )
        for d, o, p, v in snapshot.items(device_id, device_object_id):
            if _debug:
                ReplayApplication._debug("    - item: %r", (d, o, p, v))

            # skip properties that are built-in
            if p in (
                "localDate",
                "localTime",
                "protocolServicesSupported",
                "propertyList",
                "objectList",
            ):
                continue
            setattr(vlan_device, p, v)

        if _debug:
            ReplayApplication._debug("    - vlan_device: %r", vlan_device)

        # normal initialization
        ApplicationIOController.__init__(self, vlan_device, aseID=aseID)

        # include a application decoder
        self.asap = ApplicationServiceAccessPoint()

        # pass the device object to the state machine access point so it
        # can know if it should support segmentation
        self.smap = StateMachineAccessPoint(vlan_device)

        # the segmentation state machines need access to the same device
        # information cache as the application
        self.smap.deviceInfoCache = self.deviceInfoCache

        # a network service access point will be needed
        self.nsap = NetworkServiceAccessPoint()

        # give the NSAP a generic network layer service element
        self.nse = NetworkServiceElement()
        bind(self.nse, self.nsap)

        # bind the top layers
        bind(self, self.asap, self.smap, self.nsap)

        # look for objects and properties
        obj_prop_map = {}
        for d, o, p, v in snapshot.items(device_id):
            if (o == "-") or (o == device_object_id):
                continue
            if _debug:
                ReplayApplication._debug("    - item: %r", (d, o, p, v))

            # pool the definitions
            if o in obj_prop_map:
                prop_map = obj_prop_map[o]
            else:
                prop_map = obj_prop_map[o] = {}
            prop_map[p] = v

        # build objects and add them to the application
        for object_identifer, prop_map in obj_prop_map.items():
            object_type, object_instance = object_identifer.split(":")
            object_instance = int(object_instance)

            # build an instance of the object from its class
            object_class = get_object_class(object_type)
            obj = object_class(**prop_map)
            if _debug:
                ReplayApplication._debug("    - obj: %r", obj)

            # if it has a present value, make it mutable for fun
            try:
                present_value_property = obj._attr_to_property("presentValue")
                present_value_property.mutable = True
                if _debug:
                    ReplayApplication._debug("    - mutable")
            except:
                pass

            # add it to the application
            self.add_object(obj)

    def request(self, apdu):
        if _debug:
            ReplayApplication._debug("[%s]request %r", self.device_id, apdu)
        super(ReplayApplication, self).request(apdu)

    def indication(self, apdu):
        if _debug:
            ReplayApplication._debug("[%s]indication %r", self.device_id, apdu)
        super(ReplayApplication, self).indication(apdu)

    def response(self, apdu):
        if _debug:
            ReplayApplication._debug("[%s]response %r", self.device_id, apdu)
        super(ReplayApplication, self).response(apdu)

    def confirmation(self, apdu):
        if _debug:
            ReplayApplication._debug("[%s]confirmation %r", self.device_id, apdu)
        super(ReplayApplication, self).confirmation(apdu)


#
#   VLANRouter
#


@bacpypes_debugging
class VLANRouter:
    def __init__(self, local_address, local_network, device_id):
        if _debug:
            VLANRouter._debug("__init__ %r %r", local_address, local_network)
        global args

        # create a replay application
        self.rapp = ReplayApplication(device_id)

        # BACnet/IP layer is simple or a BBMD
        if args.bbmd:
            self.bip = BIPBBMD(local_address)

            # loop through the BDT entries
            for bdt_entry in args.bbmd:
                if _debug:
                    _log.debug("    - bdtentry: %r", bdt_entry)

                bdt_address = Address(bdt_entry)
                self.bip.add_peer(bdt_address)
        elif args.foreign:
            self.bip = BIPForeign()
            self.bip.register(args.foreign, args.ttl)
        else:
            self.bip = BIPSimple()
        if _debug:
            VLANRouter._debug("    - bip: %r", self.bip)

        self.annexj = AnnexJCodec()
        self.mux = UDPMultiplexer(local_address)

        # bind the bottom layers
        bind(self.bip, self.annexj, self.mux.annexJ)

        # bind the BIP stack to the local network
        self.rapp.nsap.bind(self.bip, local_network, local_address)


@bacpypes_debugging
class VLANNode:
    def __init__(self, vlan_address, device_id):
        if _debug:
            VLANNode._debug("__init__ %r %r", vlan_address, device_id)

        # create a replay application
        self.rapp = ReplayApplication(device_id)

        # create a vlan node at the assigned address
        self.vlan_node = Node(vlan_address)

        # bind the stack to the node, no network number, no addresss
        self.rapp.nsap.bind(self.vlan_node)


#
#   __main__
#


def main():
    global args, snapshot, this_device, this_application

    # parse the command line arguments
    parser = ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # snapshot database name
    parser.add_argument(
        "dbname", type=str, help="snapshot database name",
    )

    # local network address
    parser.add_argument(
        "addr1", type=str, help="local network address",
    )

    # local BACnet network number
    parser.add_argument(
        "net1", type=int, help="network number of first network",
    )

    # VLAN BACnet network number
    parser.add_argument(
        "net2", type=int, help="network number of second network",
    )

    # list of device identifiers, first one is local
    parser.add_argument(
        "devid", type=int, nargs="+", help="device identifiers",
    )

    # add an option to enable BBMD with BDT entries
    parser.add_argument(
        "--bbmd", type=str, nargs="+", help="enable BBMD with a list of peer addresses",
    )

    # add an option for foreign registration
    parser.add_argument(
        "--foreign", type=str, help="enable foreign device registration",
    )

    # add an option for foreign registration
    parser.add_argument(
        "--ttl", type=int, help="foreign device registration time to live", default=30,
    )

    # now parse the arguments
    args = parser.parse_args()

    if _debug:
        _log.debug("initialization")
    if _debug:
        _log.debug("    - args: %r", args)

    try:
        # open the snapshot database
        snapshot = Snapshot(args.dbname)

        # extract the address and networks
        local_address = Address(args.addr1)
        local_network = args.net1
        vlan_network = args.net2

        # extract the first device identifier
        local_device_id = args.devid[0]

        # create the VLAN router, bind it to the local network
        router = VLANRouter(local_address, local_network, local_device_id)

        # create a VLAN
        vlan = Network(broadcast_address=LocalBroadcast())

        # create a node for the router, address 1 on the VLAN
        router_addr = Address(1)
        router_node = Node(router_addr)
        vlan.add_node(router_node)

        # console messages get directed to its application
        this_application = router.rapp

        # bind the router stack to the vlan network through this node
        router.rapp.nsap.bind(router_node, vlan_network)

        # send network topology
        deferred(router.rapp.nse.i_am_router_to_network)

        # make some devices
        for i, device_id in enumerate(args.devid[1:]):
            vlan_address = Address(i + 2)
            _log.debug("    - vlan_address, device_id: %r, %r", vlan_address, device_id)

            # make the replay application
            vlan_app = VLANNode(vlan_address, device_id)
            _log.debug("    - vlan_app: %r", vlan_app)

            # add the node to the VLAN
            vlan.add_node(vlan_app.vlan_node)
    except ConfigurationError as err:
        sys.stderr.write(f"configuration err: {err}\n")
        sys.exit(1)

    # make a console
    this_console = VLANConsoleCmd()
    if _debug:
        _log.debug("    - this_console: %r", this_console)

    # enable sleeping will help with threads
    enable_sleeping()

    _log.debug("running")

    run()

    _log.debug("fini")


if __name__ == "__main__":
    main()
