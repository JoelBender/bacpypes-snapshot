import pickle
import sqlite3

from bacpypes.debugging import bacpypes_debugging, ModuleLogger

# some debugging
_debug = 0
_log = ModuleLogger(globals())


@bacpypes_debugging
class Snapshot:
    def __init__(self, filename):
        if _debug:
            Snapshot._debug("__init__ %r", filename)

        # make a connection, get a cursor
        self.connection = sqlite3.connect(filename)
        self.cursor = self.connection.cursor()

        # make sure the table exists
        self.cursor.execute(
            "create table if not exists snapshot(devid text, objid text, propid text, value, primary key (devid, objid, propid))"
        )

    def __getitem__(self, item):
        if _debug:
            Snapshot._debug("__getitem__ %r", item)

        self.cursor.execute(
            "select value from snapshot where (devid = ?) and (objid = ?) and (propid = ?)",
            item,
        )
        row = self.cursor.fetchone()
        if not row:
            return None

        return pickle.loads(row[0])

    def __setitem__(self, item, value):
        if _debug:
            Snapshot._debug("__setitem__ %r %r", item, value)

        try:
            self.cursor.execute(
                "insert into snapshot values (?, ?, ?, ?)",
                item + (pickle.dumps(value),),
            )
            self.connection.commit()
        except sqlite3.IntegrityError:
            self.cursor.execute(
                "update snapshot set value = ? where (devid = ?) and (objid = ?) and (propid = ?)",
                (pickle.dumps(value),) + item,
            )
            self.connection.commit()

    def items(self, devid=None, objid=None, propid=None):
        if _debug:
            Snapshot._debug("items %r %r %r", devid, objid, propid)

        query_str = "select devid, objid, propid, value from snapshot"
        query_vars = []
        query_args = []

        if devid is not None:
            query_vars.append("devid")
            query_args.append(devid)

        if objid is not None:
            query_vars.append("objid")
            query_args.append(objid)

        if propid is not None:
            query_vars.append("propid")
            query_args.append(propid)

        if query_vars:
            query_str += " where " + " and ".join(
                "(" + var_name + " = ?)" for var_name in query_vars
            )

        self.cursor.execute(query_str, tuple(query_args))
        for row in self.cursor.fetchall():
            value = pickle.loads(row[3])
            yield row[:3] + (value,)

    def close(self):
        if _debug:
            Snapshot._debug("close")

        self.cursor.close()
        self.connection.close()
