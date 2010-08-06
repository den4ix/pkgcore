# Copyright: 2005-2008 Brian Harring <ferringb@gmail.com>
# License: GPL2/BSD

"""
repository modifications (installing, removing, replacing)
"""

__all__ = ("Failure", "base", "install", "uninstall", "replace")

from snakeoil.dependant_methods import ForcedDepends
from snakeoil.weakrefs import WeakRefFinalizer
from snakeoil.demandload import demandload
demandload(globals(), "pkgcore.log:logger",
    "pkgcore.merge.engine:MergeEngine",
    "pkgcore.merge:errors@merge_errors",
    "pkgcore.package.mutated:MutatedPkg",
    "snakeoil.osutils:pjoin",
    "os",
    "shutil",
    "tempfile",
    )


class fake_lock(object):
    def __init__(self):
        pass

    acquire_write_lock = acquire_read_lock = __init__
    release_read_lock = release_write_lock = __init__


class finalizer_base(WeakRefFinalizer, ForcedDepends):

    pass

class Failure(Exception):
    pass


class base(object):

    __metaclass__ = finalizer_base

    stage_depends = {}

    stage_hooks = []

    def __init__(self, domain, repo, observer, triggers, offset):
        self.domain = domain
        self.repo = repo
        self.underway = False
        self.offset = offset
        self.observer = observer
        self.triggers = triggers
        self.create_op()
        self.lock = getattr(repo, "lock")
        self.tempspace = None
        if self.lock is None:
            self.lock = fake_lock()

    def create_op(self):
        raise NotImplementedError(self, 'create_op')

    def create_repo_op(self):
        raise NotImplementedError(self, 'create_repo_op')

    def create_engine(self):
        raise NotImplementedError(self, 'create_repo_op')

    def _create_tempspace(self):
        self.tempspace = tempfile.mkdtemp(dir=self.domain._get_tempspace(),
            prefix="merge-engine-tmp")

    def _add_triggers(self, engine):
        for trigger in self.triggers:
            trigger.register(engine)

    def customize_engine(self, engine):
        pass

    def start(self):
        """start the transaction"""
        self._create_tempspace()
        self.me = engine = self.create_engine()
        self.format_op.add_triggers(self, engine)
        self._add_triggers(engine)
        self.customize_engine(engine)
        self.underway = True
        self.lock.acquire_write_lock()
        self.me.sanity_check()
        return True

    def finish(self):
        """finish the transaction"""
        self.me.final()
        self.lock.release_write_lock()
        self.underway = False
        self.clean_tempdir()
        return True

    def finalize_repo(self):
        """finalize the repository operations"""
        return self.repo_op.finish()

    def clean_tempdir(self):
        if self.tempspace:
            try:
                shutil.rmtree(self.tempspace)
            except EnvironmentError, e:
                if e.errno != errno.ENOENT:
                    raise
        self.tempspace = None
        return True

    def _modify_repo_cache(self):
        raise NotImplementedError

    def __del__(self):
        if getattr(self, 'underway', False):
            print "warning: %s merge was underway, but wasn't completed"
            self.lock.release_write_lock()
        self.clean_tempdir()


class install(base):

    """base interface for installing a pkg into a livefs repo.

    repositories should override as needed.
    """

    stage_depends = {
        "finish": "postinst",
        "postinst": "finalize_repo",
        "finalize_repo": "repo_add",
        "repo_add": "create_repo_op",
        "create_repo_op": "transfer",
        "transfer": "preinst",
        "preinst": "start"
        }

    stage_hooks = ["merge_metadata", "postinst", "preinst", "transfer"]
    format_install_op_name = "_repo_install_op"
    engine_kls = staticmethod(MergeEngine.install)

    def __init__(self, domain, repo, pkg, observer, triggers, offset):
        self.new_pkg = pkg
        base.__init__(self, domain, repo, observer, triggers, offset)

    def create_op(self):
        self.format_op = getattr(self.new_pkg,
            self.format_install_op_name)(self.domain, self.observer)

    def create_repo_op(self):
        self.repo_op = self.repo.operations.install(self.new_pkg,
            self.observer)
        return True

    def create_engine(self):
        return self.engine_kls(self.tempspace, self.new_pkg,
            offset=self.offset, observer=self.observer)

    def preinst(self):
        """execute any pre-transfer steps required"""
        return self.format_op.preinst()

    def _update_new_pkg(self, cset):
        self.new_pkg = MutatedPkg(self.new_pkg,
            {"contents":cset})

    def transfer(self):
        """execute the actual transfer"""
        for merge_phase in (self.me.pre_merge, self.me.merge,
            self.me.post_merge):
            try:
                merge_phase()
            except merge_errors.NonFatalModification, e:
                print "warning caught: %s" % e
        self._update_new_pkg(self.me.get_merged_cset())
        return True

    def postinst(self):
        """execute any post-transfer steps required"""
        return self.format_op.postinst()

    def repo_add(self):
        return self.repo_op.add_data()

    def finish(self):
        ret = self.format_op.finalize()
        if not ret:
            logger.warn("ignoring unexpected result from install finalize- "
                "%r" % ret)
        return base.finish(self)


class uninstall(base):

    """base interface for uninstalling a pkg from a livefs repo.

    Repositories should override as needed.
    """

    stage_depends = {
        "finish":"postrm",
        "postrm": "finalize_repo",
        "finalize_repo": "repo_remove",
        "repo_remove": "remove",
        "remove": "prerm",
        "prerm": "create_repo_op",
        "create_repo_op": "start"}

    stage_hooks = ["merge_metadata", "postrm", "prerm", "remove"]
    format_uninstall_op_name = "_repo_uninstall_op"
    engine_kls = staticmethod(MergeEngine.uninstall)

    def __init__(self, domain, repo, pkg, observer, triggers, offset):
        self.old_pkg = pkg
        base.__init__(self, domain, repo, observer, triggers, offset)

    def create_op(self):
        self.format_op = getattr(self.old_pkg,
            self.format_uninstall_op_name)(self.domain, self.observer)

    def create_repo_op(self):
        self.repo_op = self.repo.operations.uninstall(self.old_pkg,
            self.observer)
        return True

    def create_engine(self):
        return self.engine_kls(self.tempspace, self.old_pkg,
            offset=self.offset, observer=self.observer)

    def prerm(self):
        """execute any pre-removal steps required"""
        return self.format_op.prerm()

    def remove(self):
        """execute any removal steps required"""
        for unmerge_phase in (self.me.pre_unmerge, self.me.unmerge,
            self.me.post_unmerge):
            try:
                unmerge_phase()
            except merge_errors.NonFatalModification, e:
                print "warning caught: %s" % e
        return True

    def postrm(self):
        """execute any post-removal steps required"""
        return self.format_op.postrm()

    def repo_remove(self):
        return self.repo_op.remove_data()

    def finish(self):
        ret = self.format_op.finalize()
        self.format_op.cleanup(disable_observer=True)
        if not ret:
            logger.warn("ignoring unexpected result from uninstall finalize- "
                "%r" % ret)
        return base.finish(self)

    def __del__(self):
        if getattr(self, 'underway', False):
            print "warning: %s unmerge was underway, but wasn't completed" % \
                self.old_pkg
            self.lock.release_write_lock()


class replace(install, uninstall):

    """base interface for replacing a pkg in a livefs repo with another.

    Repositories should override as needed.
    """

    stage_depends = {
        "finish":"finalize_repo",
        "finalize_repo":"repo_remove",
        "repo_remove": "postinst",
        "postinst": "postrm",
        "postrm": "remove",
        "remove": "prerm",
        "prerm": "repo_add",
        "repo_add": "create_repo_op",
        "create_repo_op": "transfer",
        "transfer": "preinst",
        "preinst": "start"}

    stage_hooks = [
        "merge_metadata", "unmerge_metadata", "postrm", "prerm", "postinst",
        "preinst", "unmerge_metadata", "merge_metadata"]
    engine_kls = staticmethod(MergeEngine.replace)
    format_replace_op_name = "_repo_replace_op"

    def __init__(self, domain, repo, oldpkg, newpkg, observer, triggers, offset):
        self.old_pkg = oldpkg
        self.new_pkg = newpkg
        base.__init__(self, domain, repo, observer, triggers, offset)

    def create_op(self):
        self.format_op = getattr(self.new_pkg,
            self.format_replace_op_name)(self.domain, self.old_pkg,
                self.observer)
        return True

    def create_repo_op(self):
        self.repo_op = self.repo.operations.replace(self.old_pkg,
            self.new_pkg, self.observer)
        return True

    def create_engine(self):
        return self.engine_kls(self.tempspace, self.old_pkg, self.new_pkg,
            offset=self.offset, observer=self.observer)

    def finish(self):
        ret = self.format_op.finalize()
        if not ret:
            logger.warn("ignoring unexpected result from replace finalize- "
                "%r" % ret)
        return base.finish(self)

    def __del__(self):
        if getattr(self, 'underway', False):
            print "warning: %s -> %s replacement was underway, " \
                "but wasn't completed" % (self.old_pkg, self.new_pkg)
            self.lock.release_write_lock()
