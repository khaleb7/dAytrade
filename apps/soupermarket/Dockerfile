# syntax=docker/dockerfile:1
# Build from the repository root (the directory that contains apps/).
FROM python:3.11-slim-bookworm AS build
WORKDIR /build
COPY apps/soupermarket/requirements.txt .
RUN pip install --target=/opt/pydeps -r requirements.txt
# cursor-sdk's bridge launcher is "#!/usr/bin/env sh". Distroless has neither.
RUN apt-get update \
 && apt-get install -y --no-install-recommends busybox-static \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /opt/toolbox/bin /opt/toolbox/usr/bin \
 && cp /bin/busybox /opt/toolbox/bin/busybox \
 && cp /bin/busybox /opt/toolbox/bin/sh \
 && cp /bin/busybox /opt/toolbox/usr/bin/env

FROM gcr.io/distroless/python3-debian12
COPY --from=build /opt/pydeps /opt/pydeps
COPY --from=build /opt/toolbox/bin/busybox /bin/busybox
COPY --from=build /opt/toolbox/bin/sh /bin/sh
COPY --from=build /opt/toolbox/usr/bin/env /usr/bin/env
COPY apps/soupermarket/soupermarket /app/soupermarket

ENV PYTHONPATH=/opt/pydeps:/app \
    SOUPER_DB=/data/souper.db \
    SOUPER_BIND=0.0.0.0 \
    SOUPER_PORT=8080 \
    SOUPER_WORK=/work \
    SOUPER_MODEL=composer-2.5

WORKDIR /app
USER nonroot
EXPOSE 8080
ENTRYPOINT ["/usr/bin/python3", "-m", "soupermarket"]
