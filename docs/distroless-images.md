# Building the distroless images

Newstracker, Daytrader, and SouperMarket are Linux images. The final stage of each Dockerfile is a Google distroless base: no shell, no package manager, non-root uid 65532. Build them from the git root, the directory that contains `apps/`.

Rancher Desktop on this machine does not expose Docker's named pipe. Use `nerdctl` against containerd. A client error of `npipe:////./pipe/docker_engine` means something tried to talk to Docker Desktop, which is not installed.

## Tooling

Rancher Desktop's Windows binaries:

```text
C:\Program Files\Rancher Desktop\resources\resources\win32\bin\nerdctl.exe
C:\Program Files\Rancher Desktop\resources\resources\win32\bin\kubectl.exe
```

k3s only sees images in the containerd namespace `k8s.io`. A plain `nerdctl build` stores the image in the `default` namespace, and the pod then fails to find it. Pass `--namespace k8s.io` on the build.

PowerShell, from the git root:

```powershell
$nerdctl = "C:\Program Files\Rancher Desktop\resources\resources\win32\bin\nerdctl.exe"
& $nerdctl --namespace k8s.io build -f apps/newstracker/Dockerfile -t newstracker:latest .
& $nerdctl --namespace k8s.io build -f apps/daytrader/Dockerfile -t daytrader:latest .
& $nerdctl --namespace k8s.io build -f apps/soupermarket/Dockerfile -t soupermarket:latest .
```

The same commands work with `docker build` on a host where the Docker engine is actually running. Drop `--namespace k8s.io` in that case, and push or load the image onto the node some other way.

`.dockerignore` drops `.git`, `state`, `node_modules`, `dist`, and SQLite files. That keeps a Windows `node_modules` tree out of the Linux build context.

## What each Dockerfile does

**Newstracker** is one stage. `gcr.io/distroless/python3-debian12` already has `/usr/bin/python3`. The image copies the package and runs `python3 -m newstracker`. There is no pip install. The app is the standard library only.

**Daytrader** builds on `node:22-bookworm-slim`: `npm ci`, then `tsc`. The runtime stage is `gcr.io/distroless/nodejs22-debian12`. Distroless Node does not put `node` on `PATH`. The entrypoint is `/nodejs/bin/node dist/cli.js`. `node_modules` in the image comes from that Linux `npm ci`, not from a Windows install.

**SouperMarket** installs `cursor-sdk` on `python:3.11-slim-bookworm` with `pip install --target=/opt/pydeps`, then copies that tree onto distroless Python. The install has to happen in the Linux build stage so the wheel is the manylinux build. `PYTHONPATH` is `/opt/pydeps:/app`.

The SDK bridge launcher is `#!/usr/bin/env sh`. Distroless has neither `sh` nor `env`, so the build also copies a static busybox to `/bin/sh` and `/usr/bin/env`. The bundled `node` next to that launcher runs as-is. Without those two files the process dies with `ENOENT` on `cursor-sdk-bridge` even though the script is present.

## After a rebuild

The manifests use `imagePullPolicy: IfNotPresent` and the tag `latest`. k3s will not pull a registry. It uses the image already in `k8s.io`. After a new build of the same tag, restart the workload so the pod is created against the new digest:

```powershell
$kubectl = "C:\Program Files\Rancher Desktop\resources\resources\win32\bin\kubectl.exe"
& $kubectl -n daytrade rollout restart deployment/newstracker
& $kubectl -n daytrade rollout restart deployment/soupermarket
```

Daytrader is a CronJob. The next Job resolves `daytrader:latest` when it starts. A running Job keeps the digest it already started with.

Confirm the pod is on the build you just made:

```powershell
& $kubectl -n daytrade get pods -o custom-columns=NAME:.metadata.name,IMAGE:.status.containerStatuses[0].imageID
```
