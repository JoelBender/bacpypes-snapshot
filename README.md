# BACpypes Snapshot

This set of BACpypes applications will take a snapshot of BACnet devices,
objects, and properties into a Python Shelf database, dump out the contents
it finds, and replay that as a BACnet/IP device.

For example, running *snapshot.py* and putting the result into a database
called *foundthings*:

    $ python snapshot.py foundthings
    > whois 2000 2999
    ...
    > exit

Dump out the contents of the things it found.  The parameters are an optional
device instance number, optional object identifier, and optional property
identifier. To dump the things it found for a particular device:

    $ python dump.py foundthings 2000
    ...

Or the things it found for an object instance:

    $ python dump.py foundthings - analogValue:1
    ...

Or the names of things for in a device:

    $ python dump.py foundthings 2003 - objectName
    ...

To replay the contents, run the *replay.py* application.  The parameters are
similar to the *IP2VLANRouter.py* sample application in BACpypes, it is given
a BACnet/IP network number for the local network and another for a VLAN.  The
first device instance number will be on the local network, the rest of the
replayed devices will be on the VLAN.

Replaying the contents of device 2002 from the *foundthings* database on the
local network acting as a router between networks 10 (local) and 20 (VLAN).
There will be no devices on network 20:

    $ python replay.py foundthings 192.168.0.12/24 10 20 2002

Replaying the contents of many devices from the same database, device 2003
will be on network 10 (local) and the rest will be on network 20 (VLAN):

    $ python replay.py foundthings 192.168.0.12/24 10 20 2003 2004 2005 2006

### Notes

* The topologies could be very different from the source of the snapshot
* The local date and time, protocol services supported and object lists are
  from the BACpypes services.  Local date and time will be from the application,
  not the database, and the application will support **Read/Write Property** and
  **Read/Write Property Multiple** even if the snapshot does not.
* The objects that have a present value (like analog value objects) will support
  **Write Property**, just for fun.
* Trend logs and file contents are not available in the snapshot or the replay.
