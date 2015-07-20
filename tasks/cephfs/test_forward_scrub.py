
"""
Test that the forward scrub functionality can traverse metadata and apply
requested tags, on well formed metadata.

This is *not* the real testing for forward scrub, which will need to test
how the functionality responds to damaged metadata.

"""

import logging
from textwrap import dedent
import traceback
from collections import namedtuple

from teuthology.orchestra.run import CommandFailedError
from tasks.cephfs.cephfs_test_case import CephFSTestCase

import struct

log = logging.getLogger(__name__)


ValidationError = namedtuple("ValidationError", ["exception", "backtrace"])


class TestForwardScrub(CephFSTestCase):
    MDSS_REQUIRED = 1

    def _read_str_xattr(self, pool, obj, attr):
        """
        Read a ceph-encoded string from a rados xattr
        """
        output = self.fs.rados(["getxattr", obj, attr], pool=pool)
        strlen = struct.unpack('i', output[0:4])[0]
        return output[4:(4 + strlen)]

    def test_apply_tag(self):
        self.mount_a.run_shell(["mkdir", "parentdir"])
        self.mount_a.run_shell(["mkdir", "parentdir/childdir"])
        self.mount_a.run_shell(["touch", "rfile"])
        self.mount_a.run_shell(["touch", "parentdir/pfile"])
        self.mount_a.run_shell(["touch", "parentdir/childdir/cfile"])

        # Build a structure mapping path to inode, as we will later want
        # to check object by object and objects are named after ino number
        inos = {}
        p = self.mount_a.run_shell(["find", "./"])
        paths = p.stdout.getvalue().strip().split()
        for path in paths:
            inos[path] = self.mount_a.path_to_ino(path)

        # Flush metadata: this is a friendly test of forward scrub so we're skipping
        # the part where it's meant to cope with dirty metadata
        self.mount_a.umount_wait()
        self.fs.mds_asok(["flush", "journal"])

        tag = "mytag"

        # Execute tagging forward scrub
        self.fs.mds_asok(["tag", "path", "/parentdir", tag])
        # Wait for completion
        import time
        time.sleep(10)
        # FIXME watching clog isn't a nice mechanism for this, once we have a ScrubMap we'll
        # watch that instead

        # Check that dirs were tagged
        for dir in ["./parentdir", "./parentdir/childdir"]:
            dir_ino = inos[dir]
            dirfrag_obj_name = "{0:x}.00000000".format(dir_ino)
            wrote = self._read_str_xattr(
                self.fs.get_metadata_pool_name(),
                dirfrag_obj_name,
                "scrub_tag"
            )
            self.assertEqual(wrote, tag)

        # Check that files were tagged
        for file in ["./parentdir/pfile", "./parentdir/childdir/cfile"]:
            file_ino = inos[file]
            file_obj_name = "{0:x}.00000000".format(file_ino)
            wrote = self._read_str_xattr(
                self.fs.get_data_pool_name(),
                file_obj_name,
                "scrub_tag"
            )
            self.assertEqual(wrote, tag)

        # This guy wasn't in the tag path, shouldn't have been tagged
        rfile_ino = inos["./rfile"]
        rfile_obj_name = "{0:x}.00000000".format(rfile_ino)
        with self.assertRaises(CommandFailedError):
            self._read_str_xattr(
                self.fs.get_data_pool_name(),
                rfile_obj_name,
                "scrub_tag"
            )
