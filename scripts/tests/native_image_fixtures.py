"""Real file reads; Linux proc routing/root ownership explicitly substituted."""
from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from relay_core import native_image


@contextmanager
def executable_fixture(directory, *, pid=13, body=b"\x7fELFsynthetic-native-image"):
    path = Path(directory) / "native-image"
    path.write_bytes(body)
    path.chmod(0o500)
    other = Path(directory) / "other-image"
    other.write_bytes(body)
    other.chmod(0o500)
    expected = "/opt/ccrelay/native/fixture-1/codex"
    proc = "/proc/" + str(pid) + "/exe"
    state = SimpleNamespace(path=path, other=other, proc_target=path, link=expected, uid=0, mode=None,
                            executable=expected, byte_digest="sha256:" + hashlib.sha256(body).hexdigest(),
                            after_read=lambda: None, after_open=lambda: None, opened=set(), reads=0,
                            deny_path=False, on_stat=lambda: None)
    original_open, original_close, original_read = os.open, os.close, os.read
    original_stat, original_fstat = os.stat, os.fstat

    def metadata(raw):
        values = {key: getattr(raw, key) for key in ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode",
                  "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}
        return SimpleNamespace(**{**values, "st_uid": state.uid,
                                  "st_mode": raw.st_mode if state.mode is None else state.mode})

    def opened(target, flags, *args, **kwargs):
        target = os.fspath(target)
        if target in {expected, proc}:
            fd = original_open(path if target == expected else state.proc_target, flags, *args, **kwargs)
            state.opened.add(fd)
            state.after_open()
            return fd
        return original_open(target, flags, *args, **kwargs)

    def closed(fd):
        state.opened.discard(fd)
        return original_close(fd)

    def read(fd, maximum):
        value = original_read(fd, maximum)
        if fd in state.opened:
            state.reads += 1
            state.after_read()
        return value

    def fstat(fd):
        value = original_fstat(fd)
        return metadata(value) if fd in state.opened else value

    def stated(target, *args, **kwargs):
        target = os.fspath(target)
        if target in {expected, proc}:
            state.on_stat()
            return metadata(original_stat(path if target == expected else state.proc_target, *args, **kwargs))
        return original_stat(target, *args, **kwargs)

    def protected(target, **kwargs):
        assert target == expected and kwargs == {"owners": {0}}
        if state.deny_path:
            raise native_image.Denied("fixture unprotected ancestor")
        return Path(target)

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(native_image.sys, "platform", "linux"))
        stack.enter_context(mock.patch.object(native_image, "protected_path", side_effect=protected))
        stack.enter_context(mock.patch.object(os, "readlink", side_effect=lambda target: state.link if target == proc else "unsupported"))
        for name, method in (("open", opened), ("close", closed), ("read", read), ("fstat", fstat), ("stat", stated)):
            stack.enter_context(mock.patch.object(os, name, side_effect=method))
        yield state
    assert not state.opened, "image observation leaked owned descriptors"
