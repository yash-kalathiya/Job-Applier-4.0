"""Secure atomic evidence file writer.

Enforces:
- Small stdlib Linux-first strict descriptor operations
- Preservation of lexical paths (abspath, never realpath/resolve before writer)
- Symlink rejection for destination, intermediate components, and dangling symlinks
- Walk every directory component from trusted root fd using O_DIRECTORY | O_NOFOLLOW and dir_fd
- mkdir relative to verified dir_fd with 0700 on newly created leaf components (no arbitrary chmod of existing dirs)
- Pin final parent directory fd
- Stage random temp name via os.open(O_CREAT | O_EXCL | O_NOFOLLOW, 0600, dir_fd=parent_fd), write/fsync closed
- Overwrite via os.replace(temp, dest, src_dir_fd=fd, dst_dir_fd=fd) after destination symlink refusal
- Default no-overwrite via os.link(temp, dest, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
  atomic no-clobber of completed bytes then unlink temp, directory fsync, robust cleanup
- Unsupported platform primitives fail explicitly vs false guarantee
"""
import errno
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Callable, Optional, Union

_TEST_POST_WALK_HOOK: Optional[Callable[[int, str], None]] = None
_TEST_POST_MKDIR_HOOK: Optional[Callable[[int, str], None]] = None
_TEST_PRE_COMMIT_HOOK: Optional[Callable[[int, str], None]] = None


def _check_platform_capabilities() -> None:
    if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY'):
        raise NotImplementedError("Platform does not support O_NOFOLLOW / O_DIRECTORY; failing closed for safe IO")
    if os.stat not in os.supports_dir_fd or os.open not in os.supports_dir_fd or os.link not in os.supports_dir_fd:
        raise NotImplementedError("Platform does not support dir_fd operations; failing closed for safe IO")


def _secure_walk_to_parent(path_str: str) -> tuple[int, str]:
    """Walk every directory component from trusted root fd and pin the final parent directory fd.

    Returns (parent_fd, filename). Caller must close parent_fd.
    """
    norm_str = os.path.normpath(path_str)
    if not norm_str.startswith('/'):
        raise ValueError(f"Path must be absolute: {path_str}")

    parts = [p for p in norm_str.split('/') if p]
    if not parts:
        raise ValueError(f"Invalid path with no filename component: {path_str}")

    dir_parts = parts[:-1]
    filename = parts[-1]

    root_fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    curr_fd = root_fd

    try:
        for comp in dir_parts:
            try:
                next_fd = os.open(comp, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=curr_fd)
                st = os.fstat(next_fd)
                if stat.S_ISLNK(st.st_mode):
                    os.close(next_fd)
                    raise ValueError(f"Refusing to traverse symlink component: {comp}")
            except FileNotFoundError:
                # Create directory relative to verified curr_fd
                try:
                    os.mkdir(comp, mode=0o700, dir_fd=curr_fd)
                except FileExistsError:
                    pass

                if _TEST_POST_MKDIR_HOOK is not None:
                    _TEST_POST_MKDIR_HOOK(curr_fd, comp)

                next_fd = os.open(comp, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=curr_fd)
                st = os.fstat(next_fd)
                if stat.S_ISLNK(st.st_mode):
                    os.close(next_fd)
                    raise ValueError(f"Refusing to traverse symlink component: {comp}")
                # Verify opened directory permissions: reject if writable by group/others; never chmod
                if (st.st_mode & 0o022) != 0:
                    os.close(next_fd)
                    raise PermissionError(f"Newly opened directory component is writable by group/others: {comp}")
            except OSError as exc:
                if exc.errno == errno.ELOOP or exc.errno == errno.ENOTDIR:
                    raise ValueError(f"Refusing to access path through symlink component: {comp}") from exc
                raise

            os.close(curr_fd)
            curr_fd = next_fd

        # Reject final output directories writable by group/others rather than support attacker-writable staging
        # (os.fstat mode; private leaf); ancestors can be shared sticky /tmp but pinned traversal nofollow.
        leaf_st = os.fstat(curr_fd)
        if (leaf_st.st_mode & 0o022) != 0:
            raise PermissionError(
                f"Refusing to write into directory writable by group/others (mode {oct(leaf_st.st_mode)}): {norm_str}"
            )
    except Exception:
        os.close(curr_fd)
        raise

    return curr_fd, filename


def write_bytes_atomic(path: Union[str, Path], data: bytes, overwrite: bool = False) -> Path:
    """Write bytes atomically to path with 0600 permissions and symlink rejection."""
    _check_platform_capabilities()

    raw_path_str = os.path.abspath(os.path.expanduser(str(path)))
    parent_fd, filename = _secure_walk_to_parent(raw_path_str)

    if _TEST_POST_WALK_HOOK is not None:
        _TEST_POST_WALK_HOOK(parent_fd, raw_path_str)

    temp_name = f".tmp_safe_{secrets.token_hex(16)}"
    temp_staged = False
    temp_fd: Optional[int] = None

    try:
        # Check destination in pinned parent_fd using descriptor operations
        dest_exists = False
        try:
            st = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
            dest_exists = True
            if stat.S_ISLNK(st.st_mode):
                raise ValueError(f"Refusing to write to symlink destination: {filename}")
        except FileNotFoundError:
            dest_exists = False
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise ValueError(f"Refusing to write to symlink destination: {filename}") from exc
            raise

        if not overwrite and dest_exists:
            raise FileExistsError(f"Path already exists and overwrite is False: {raw_path_str}")

        # Stage random temp name via os.open(...O_CREAT|O_EXCL|O_NOFOLLOW, 0600, dir_fd=parent_fd)
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        temp_staged = True

        total_written = 0
        while total_written < len(data):
            chunk = data[total_written:]
            n = os.write(temp_fd, chunk)
            if n == 0:
                raise OSError("write returned 0 bytes")
            total_written += n
        os.fsync(temp_fd)
        temp_stat = os.fstat(temp_fd)

        if _TEST_PRE_COMMIT_HOOK is not None:
            _TEST_PRE_COMMIT_HOOK(parent_fd, temp_name)

        # Precommit descriptor identity verification against directory entry
        # Keep temp_fd open throughout check and commit to prevent inode reuse
        st_named = os.stat(temp_name, dir_fd=parent_fd, follow_symlinks=False)
        temp_stat_live = os.fstat(temp_fd)
        if stat.S_ISLNK(st_named.st_mode):
            raise ValueError(f"Staged temporary file was replaced with a symlink: {temp_name}")
        if (st_named.st_dev, st_named.st_ino) != (temp_stat_live.st_dev, temp_stat_live.st_ino):
            raise ValueError(f"Staged temporary file descriptor identity mismatch (replaced): {temp_name}")

        if overwrite:
            # Overwrite via os.replace(temp, dest, src_dir_fd=fd, dst_dir_fd=fd)
            # Recheck destination to refuse symlink replacement
            try:
                st = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
                if stat.S_ISLNK(st.st_mode):
                    raise ValueError(f"Refusing to overwrite symlink target: {filename}")
            except FileNotFoundError:
                pass
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise ValueError(f"Refusing to overwrite symlink target: {filename}") from exc
                raise

            os.replace(temp_name, filename, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            temp_staged = False
            try:
                os.fsync(parent_fd)
            except OSError:
                pass
        else:
            # Default no-overwrite via os.link(temp, dest, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            try:
                os.link(
                    temp_name,
                    filename,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                raise FileExistsError(f"Path already exists and overwrite is False: {raw_path_str}")
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    raise FileExistsError(f"Path already exists and overwrite is False: {raw_path_str}") from exc
                raise

            # Atomic publication succeeded; remove staged temp link
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
                temp_staged = False
            except OSError:
                pass
            try:
                os.fsync(parent_fd)
            except OSError:
                pass

        return Path(raw_path_str)
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if temp_staged:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)


def write_json_atomic(path: Union[str, Path], data: Any, overwrite: bool = False, indent: int = 2) -> Path:
    """Write JSON data atomically to path with 0600 permissions and symlink rejection."""
    encoded = (json.dumps(data, indent=indent, ensure_ascii=False) + '\n').encode('utf-8')
    return write_bytes_atomic(path, encoded, overwrite=overwrite)
