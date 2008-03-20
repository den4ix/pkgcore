# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

import os
from pkgcore.fs import fs
from pkgcore.interfaces.data_source import data_source
from pkgcore.chksum import get_chksums
from pkgcore.test import TestCase
from snakeoil.test.mixins import tempdir_decorator
from snakeoil.osutils import pjoin, normpath

class base(object):

    kls = None

    def make_obj(self, location="/tmp/foo", **kwds):
        kwds.setdefault("strict", False)
        return self.kls(location, **kwds)

    def test_basename(self):
        self.assertEqual(self.make_obj(location='/asdf').basename, 'asdf')
        self.assertEqual(self.make_obj(location='/a/b').basename, 'b')

    def test_dirname(self):
        self.assertEqual(self.make_obj(location='/asdf').dirname, '/')
        self.assertEqual(self.make_obj(location='/a/b').dirname, '/a')

    def test_location_normalization(self):
        for loc in ('/tmp/a', '/tmp//a', '/tmp//', '/tmp/a/..'):
            self.assertEqual(self.make_obj(location=loc).location,
                normpath(loc), reflective=False)

    def test_change_attributes(self):
        # simple test...
        o = self.make_obj("/foon")
        self.assertNotEqual(o, o.change_attributes(location="/nanners"))

    def test_init(self):
        mkobj = self.make_obj
        o = mkobj("/tmp/foo")
        self.assertEqual(o.location, "/tmp/foo")
        self.assertEqual(mkobj(mtime=100l).mtime, 100l)
        self.assertEqual(mkobj(mode=0660).mode, 0660)
        # ensure the highband stays in..
        self.assertEqual(mkobj(mode=042660).mode, 042660)
        self.assertEqual(mkobj(uid=0).uid, 0)
        self.assertEqual(mkobj(gid=0).gid, 0)

    def test_hash(self):
        # might seem odd, but done this way to avoid the any potential
        # false positives from str's hash returning the same
        d = {self.make_obj("/tmp/foo"):None}
        # ensure it's accessible without a KeyError
        d[self.make_obj("/tmp/foo")]

    def test_eq(self):
        o = self.make_obj("/tmp/foo")
        self.assertEqual(o, self.make_obj("/tmp/foo"))
        self.assertNotEqual(o, self.make_obj("/tmp/foo2"))

    def test_setattr(self):
        o = self.make_obj()
        for attr in o.__attrs__:
            self.assertRaises(AttributeError, setattr, o, attr, "monkies")

    @tempdir_decorator
    def test_realpath(self):
        # just to be safe, since this could trash some tests.
        self.dir = os.path.realpath(self.dir)
        os.mkdir(pjoin(self.dir, "test1"))
        obj = self.make_obj(location=pjoin(self.dir, "test1", "foon"))
        self.assertIdentical(obj, obj.realpath())
        os.symlink(pjoin(self.dir, "test1"), pjoin(self.dir, "test2"))
        obj = self.make_obj(location=pjoin(self.dir, "test2", "foon"))
        new_obj = obj.realpath()
        self.assertNotIdentical(obj, new_obj)
        self.assertEqual(new_obj.location, pjoin(self.dir, "test1", "foon"), reflective=False)
        os.symlink(pjoin(self.dir, "test3"), pjoin(self.dir, "nonexistant"))
        obj = self.make_obj(pjoin(self.dir, "nonexistant", "foon"))
        # path is incomplete; should still realpath it.
        new_obj = obj.realpath()
        self.assertNotIdentical(obj, new_obj)
        self.assertEqual(new_obj.location, pjoin(self.dir, "test3", "foon"))


class Test_fsFile(TestCase, base):

    kls = fs.fsFile

    def test_init(self):
        base.test_init(self)
        mkobj = self.make_obj
        o = mkobj("/etc/passwd")
        raw_data = open("/etc/passwd").read()
        self.assertEqual(o.data.get_fileobj().read(), raw_data)
        o = mkobj("/bin/this-file-should-not-exist-nor-be-read",
            data_source=data_source(raw_data))
        self.assertEqual(o.data.get_fileobj().read(), raw_data)
        keys = o.chksums.keys()
        self.assertEqual([o.chksums[x] for x in keys],
            list(get_chksums(data_source(raw_data), *keys)))

        chksums = dict(o.chksums.iteritems())
        self.assertEqual(sorted(mkobj(chksums=chksums).chksums.iteritems()),
            sorted(chksums.iteritems()))


class Test_fsLink(TestCase, base):
    kls = fs.fsLink

    def make_obj(self, location="/tmp/foo", **kwds):
        target = kwds.pop("target", pjoin(location, "target"))
        kwds.setdefault("strict", False)
        return self.kls(location, target, **kwds)

    def test_init(self):
        base.test_init(self)
        mkobj = self.make_obj
        self.assertEqual(mkobj(target="k9").target, "k9")
        self.assertEqual(mkobj(target="../foon").target, "../foon")

    def test_resolved_target(self):
        self.assertEqual(self.make_obj(location="/tmp/foon", target="dar").resolved_target,
            "/tmp/dar")
        self.assertEqual(self.make_obj(location="/tmp/foon", target="/dar").resolved_target,
            "/dar")

class Test_fsDev(TestCase, base):
    kls = fs.fsDev

    def test_init(self):
        base.test_init(self)
        mkobj = self.make_obj
        self.assertRaises(TypeError, mkobj, major=-1, strict=True)
        self.assertRaises(TypeError, mkobj, minor=-1, strict=True)
        self.assertEqual(mkobj(major=1).major, 1)
        self.assertEqual(mkobj(minor=1).minor, 1)


class Test_fsFifo(TestCase, base):
    kls = fs.fsFifo


class Test_fsDir(TestCase, base):
    kls = fs.fsDir
