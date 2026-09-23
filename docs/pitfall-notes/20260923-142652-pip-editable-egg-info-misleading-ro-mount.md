# `pip install -e` on a read-only tree fails with "Cannot update time stamp of directory"

**Symptom.** Running the dev bootstrap against a bind-mounted source tree
mounted `:ro` (the upstream reference container) dies at:

```
running egg_info
error: Cannot update time stamp of directory 'src/kirocrew.egg-info'
```

Nothing about "read-only" appears, so the first instinct is a permissions
or mtime oddity of the mount.

**Root cause.** Two layers. (1) PEP 660 editable installs still run
`egg_info`, which writes/timestamps `<project>.egg-info` **inside the source
root** — impossible on an `:ro` bind mount, and setuptools words the EROFS
failure as the timestamp message above. (2) In this specific case the mount
was not even the intended target: the bootstrap script had a hardcoded
`pip install -e /workspace` while only the guard clause was parameterized
(`KIROCREW_DEV_SRC`), so the install was pointed at the read-only mount
instead of the writable snapshot in the home volume. The misleading error
came first; the script bug made it permanent.

**Fix.** Do not editable-install a read-only tree. Snapshot the tree into a
writable location once (`tar | tar` inside the container's home volume) and
point `KIROCREW_DEV_SRC` at the copy; parameterize **every** use of the
source path in the script, not just the checks. The reference instance then
installs cleanly, while the upstream checkout itself is never written
(`git status` stays empty, verified).

**How to avoid.** Treat `Cannot update time stamp of directory '<x>.egg-info'`
as `EROFS on the project root`: ask "is the source tree writable?" and "is
the path this script installs from actually the one I think it is?" before
anything else. If a tree must stay pristine (upstream comparison, vendor
checkout), mount `:ro` and install from a snapshot copy — never rw-mount and
hope the egg-info write is harmless. See also
[../guides/docker-dev-env.md](../guides/docker-dev-env.md).
