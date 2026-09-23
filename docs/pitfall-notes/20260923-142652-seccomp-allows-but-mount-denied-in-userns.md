# seccomp profile fully applied, yet the inner sandbox probe dies at mount(EACCES)

**Symptom.** Dev container created with
`--security-opt seccomp=docker/seccomp/kirocrew-seccomp.json`. The gateway
log blames the sandbox:
`Kiro CLI ... could not be verified: the sandbox refused the probe (no_backend:
mount(MS_REC|MS_PRIVATE) on / failed with errno 13 (EACCES))`, and
`/api/kiro-prerequisite` reports `sandbox_unavailable=true`. Everything the
error points at (the seccomp profile) is already correct.

**Root cause.** Not seccomp. On this host the **kernel/AppArmor layer refuses
mounts inside unprivileged user namespaces**. `unshare -Ur` succeeds (so
userns creation itself is allowed), but any `mount` from that fresh userns —
`MS_REC|MS_PRIVATE` on `/`, a plain tmpfs mount — returns EACCES. The
profile extends the Docker default with `unshare`/`clone`/`mount` allows,
and those are genuinely in force; a lower LSM is still saying no. The
giveaway test: the identical command **on the host, no container**

```bash
unshare -Ur sh -c 'mount -t tmpfs none /mnt'   # → permission denied
```

fails the same way. No seccomp profile (any profile) can outrank that; the
only further lever would be `--privileged`/caps, which is a bigger isolation
trade than a dev harness should make.

**Fix.** For these containers, fall back to the product's audited opt-in
`KIROCREW_ALLOW_UNSANDBOXED=1` (same posture as the pre-existing
`kirocrew-docker`): the container remains the OS boundary,
`entrypoint.sh` seeds `sandbox=auto` + `sandbox_allow_unsandboxed_exec`, the
kiro-cli probe stops being wrapped, and `sandbox_unavailable` drops back to
`false`. Keep the seccomp profile mounted anyway — if the host's userns
policy is ever relaxed, deleting `config.json` and the env var restores the
inner sandbox with no image change.

**How to avoid.** When the sandbox probe fails inside a container, run the
failing syscall sequence once on the host under a bare `unshare -Ur` before
touching the seccomp profile. `seccomp` rejections and LSM/capability
rejections both surface as `EACCES`/`EPERM` from the syscall, but only one
of them is fixable from the `docker run` line; the host test separates them
in ten seconds. See also
[../guides/docker-dev-env.md](../guides/docker-dev-env.md).
