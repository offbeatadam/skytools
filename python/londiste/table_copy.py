#! /usr/bin/env python

"""Do a full table copy.

For internal usage.
"""

import sys, os, skytools

from skytools.dbstruct import *
from playback import *

__all__ = ['CopyTable']

class CopyTable(Replicator):
    def __init__(self, args, copy_thread = 1):
        Replicator.__init__(self, args)

        if copy_thread:
            self.pidfile += ".copy"
            self.consumer_id += "_copy"
            self.copy_thread = 1

    def init_optparse(self, parser=None):
        p = Replicator.init_optparse(self, parser)
        p.add_option("--skip-truncate", action="store_true", dest="skip_truncate",
                    help = "avoid truncate", default=False)
        return p

    def do_copy(self, tbl_stat):
        src_db = self.get_database('provider_db')
        dst_db = self.get_database('subscriber_db')

        # it should not matter to pgq
        src_db.commit()
        dst_db.commit()

        # change to SERIALIZABLE isolation level
        src_db.set_isolation_level(2)
        src_db.commit()

        # initial sync copy
        src_curs = src_db.cursor()
        dst_curs = dst_db.cursor()

        self.log.info("Starting full copy of %s" % tbl_stat.name)

        # find dst struct
        src_struct = TableStruct(src_curs, tbl_stat.name)
        dst_struct = TableStruct(dst_curs, tbl_stat.name)
        
        # check if columns match
        dlist = dst_struct.get_column_list()
        for c in src_struct.get_column_list():
            if c not in dlist:
                raise Exception('Column %s does not exist on dest side' % c)

        # drop unnecessary stuff
        objs = T_CONSTRAINT | T_INDEX | T_TRIGGER | T_RULE
        dst_struct.drop(dst_curs, objs, log = self.log)

        # do truncate & copy
        self.real_copy(src_curs, dst_curs, tbl_stat.name)

        # get snapshot
        src_curs.execute("select get_current_snapshot()")
        snapshot = src_curs.fetchone()[0]
        src_db.commit()

        # restore READ COMMITTED behaviour
        src_db.set_isolation_level(1)
        src_db.commit()

        # create previously dropped objects
        dst_struct.create(dst_curs, objs, log = self.log)

        # set state
        tbl_stat.change_snapshot(snapshot)
        if self.copy_thread:
            tbl_stat.change_state(TABLE_CATCHING_UP)
        else:
            tbl_stat.change_state(TABLE_OK)
        self.save_table_state(dst_curs)
        dst_db.commit()

    def real_copy(self, srccurs, dstcurs, tablename):
        "Main copy logic."

        # drop data
        if self.options.skip_truncate:
            self.log.info("%s: skipping truncate" % tablename)
        else:
            self.log.info("%s: truncating" % tablename)
            dstcurs.execute("truncate " + tablename)

        # do copy
        self.log.info("%s: start copy" % tablename)
        col_list = skytools.get_table_columns(srccurs, tablename)
        stats = skytools.full_copy(tablename, srccurs, dstcurs, col_list)
        if stats:
            self.log.info("%s: copy finished: %d bytes, %d rows" % (
                          tablename, stats[0], stats[1]))

if __name__ == '__main__':
    script = CopyTable(sys.argv[1:])
    script.start()

