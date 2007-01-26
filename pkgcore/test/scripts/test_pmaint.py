# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from StringIO import StringIO
from pkgcore.util.formatters import PlainTextFormatter
from pkgcore.interfaces.repo import (nonlivefs_install,
    nonlivefs_uninstall, nonlivefs_replace)
from pkgcore.test import TestCase
from pkgcore.test.misc import Options
from pkgcore.scripts import pmaint
from pkgcore.test.scripts import helpers
from pkgcore.config import basics, ConfigHint
from pkgcore.repository import util, syncable
from pkgcore.sync import base
from pkgcore.ebuild.cpv import CPV
from pkgcore.util.currying import partial


class FakeSyncer(base.syncer):

    def __init__(self,  *args, **kwargs):
        self.succeed = kwargs.pop('succeed', True)
        base.syncer.__init__(self, *args, **kwargs)
        self.synced = False

    def _sync(self, verbosity, output_fd, **kwds):
        self.synced = True
        return self.succeed


class SyncableRepo(syncable.tree_mixin, util.SimpleTree):

    pkgcore_config_type = ConfigHint(typename='repo')

    def __init__(self, succeed=True):
        util.SimpleTree.__init__(self, {})
        syncer = FakeSyncer('/fake', 'fake', succeed=succeed)
        syncable.tree_mixin.__init__(self, syncer)


success_section = basics.HardCodedConfigSection({'class': SyncableRepo,
                                                 'succeed': True})
failure_section = basics.HardCodedConfigSection({'class': SyncableRepo,
                                                 'succeed': False})


class SyncTest(TestCase, helpers.MainMixin):

    parser = helpers.mangle_parser(pmaint.SyncOptionParser())
    main = staticmethod(pmaint.sync_main)

    def test_parser(self):
        self.assertError(
            "repo 'missing' doesn't exist:\nvalid repos ['repo']",
            'missing', repo=success_section)
        values = self.parse(repo=success_section)
        self.assertEquals(['repo'], values.repos)
        values = self.parse('repo', repo=success_section)
        self.assertEquals(['repo'], values.repos)

    def test_sync(self):
        config = self.assertOut(
            [
                "*** syncing 'myrepo'...",
                "*** synced 'myrepo'",
                ],
            myrepo=success_section)
        self.assertTrue(config.repo['myrepo']._sync.synced)
        self.assertOut(
            [
                "*** syncing 'myrepo'...",
                "*** failed syncing 'myrepo'",
                ],
            myrepo=failure_section)
        self.assertOutAndErr(
            [
                "*** syncing 'goodrepo'...",
                "*** synced 'goodrepo'",
                "*** syncing 'badrepo'...",
                "*** failed syncing 'badrepo'",
                "*** synced 'goodrepo'",
                ], [
                "!!! failed sync'ing 'badrepo'",
                ],
            'goodrepo', 'badrepo',
            goodrepo=success_section, badrepo=failure_section)


class fake_pkg(CPV):

    def __init__(self, repo, *a, **kw):
        CPV.__init__(self, *a, **kw)
        object.__setattr__(self, 'repo', repo)

def derive_op(op, *a, **kw):
    class new_op(op):
        def modify_repo(*a, **kw):
            return True
    return new_op(*a, **kw)

class fake_repo(util.SimpleTree):

    def __init__(self, data, frozen=False, livefs=False):
        self.installed = []
        self.replaced = []
        self.uninstalled = []
        util.SimpleTree.__init__(self, data,
            pkg_klass=partial(fake_pkg, self))
        self.livefs = livefs
        self.frozen = frozen
    
    def _install(self, pkg, *a, **kw):
        self.installed.append(pkg)
        kw.pop("force", None)
        return derive_op(nonlivefs_install, self, pkg, *a, **kw)

    def _replace(self, old, new, *a, **kw):
        self.replaced.append((old, new))
        kw.pop("force", None)
        return derive_op(nonlivefs_replace, self, old, new, *a, **kw)

    def _uninstall(self, pkg, *a, **kw):
        self.uninstalled.append(pkg)
        kw.pop("force", None)
        return derive_op(nonlivefs_uninstall, self, pkg, *a, **kw)


def make_repo_config(repo_data, livefs=False, frozen=False):
    def repo():
        return fake_repo(repo_data, livefs=livefs, frozen=frozen)
    repo.pkgcore_config_type=ConfigHint(typename='repo')
    return basics.HardCodedConfigSection({'class':repo})


class CopyTest(TestCase, helpers.MainMixin):

    parser = helpers.mangle_parser(pmaint.CopyParser())
    main = staticmethod(pmaint.copy_main)

    def execute_main(self, *a, **kw):
        config = self.parse(*a, **kw)
        out = PlainTextFormatter(StringIO())
        ret = self.main(config, out, out)
        return ret, config, out

    def test_parser(self):
        self.assertError("target_report wasn't specified- specify it either as "
            "the last arguement, or via --target-repo")
        self.assertError("target_report wasn't specified- specify it either as "
            "the last arguement, or via --target-repo", "sys-apps/portage")
        self.assertError("target repo 'sys-apps/portage' was not found, known "
            "repos-\nNone", "--target-repo",
                "sys-apps/portage", config=Options(repo={}))
        self.assertError("source repo 'sys-apps/portage' was not found, known "
            "repos-\n('dar', 'foo')", "--source-repo", "sys-apps/portage", "foo",
                "dar", dar=make_repo_config({}), foo=make_repo_config({}))
    
    def test_force(self):
        self.assertError("target repo 'trg' is frozen; --force is required to override this",
            '--target-repo', 'trg', '--source-repo', 'src',
            '=sys-apps/portage-2.1',
                src=make_repo_config({'sys-apps':{'portage':['2.1', '2.3']}}),
                trg=make_repo_config({}, frozen=True)
            )
        ret, config, out = self.execute_main(
            '--target-repo', 'trg', '--source-repo', 'src',
            '=sys-apps/portage-2.1',
                src=make_repo_config({'sys-apps':{'portage':['2.1', '2.3']}}),
                trg=make_repo_config({})
            )
        self.assertEqual(ret, 0, "expected non zero exit code")
        self.assertEqual(map(str, config.target_repo.installed),
            ['sys-apps/portage-2.1'])

    def test_normal_function(self):
        ret, config, out = self.execute_main(
            '--target-repo', 'trg', '--source-repo', 'src',
            '*',
                src=make_repo_config({'sys-apps':{'portage':['2.1', '2.3']}}),
                trg=make_repo_config({})
            )
        self.assertEqual(ret, 0, "expected non zero exit code")
        self.assertEqual(map(str, config.target_repo.installed),
            ['sys-apps/portage-2.1', 'sys-apps/portage-2.3'])
        self.assertEqual(config.target_repo.uninstalled,
            config.target_repo.replaced,
            msg="uninstalled should be the same as replaced; empty")

        d = {'sys-apps':{'portage':['2.1', '2.2']}}
        ret, config, out = self.execute_main(
            '--target-repo', 'trg', '--source-repo', 'src',
            '=sys-apps/portage-2.1',
                src=make_repo_config(d),
                trg=make_repo_config(d)
            )
        self.assertEqual(ret, 0, "expected non zero exit code")
        self.assertEqual([map(str, x) for x in config.target_repo.replaced],
            [['sys-apps/portage-2.1', 'sys-apps/portage-2.1']])
        self.assertEqual(config.target_repo.uninstalled,
            config.target_repo.installed,
            msg="installed should be the same as uninstalled; empty")
