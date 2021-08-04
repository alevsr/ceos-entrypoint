# > CEOS_64=64 CEOS_EDITION=lab CEOS_VERSION=4.26.1F
# > docker build \
#   --build-arg "CEOS_64=${CEOS_64}" \
#   --build-arg "CEOS_EDITION=${CEOS_EDITION}" \
#   --build-arg "CEOS_VERSION=${CEOS_VERSION}" \
#   --tag arista-ceos:${CEOS_EDITION}${CEOS_64}-${CEOS_VERSION} \
#   --tag arista-ceos:latest .

FROM scratch
ARG CEOS_64=64
ARG CEOS_EDITION=lab
ARG CEOS_VERSION=4.26.1F

ADD cEOS${CEOS_64}-${CEOS_EDITION}-${CEOS_VERSION}.tar.xz /

ENV CEOS=1 \
    EOS_PLATFORM=ceoslab \
    INTFTYPE=et \
    MGMT_INTF=et0 \
    ETBA=1 \
    SKIP_ZEROTOUCH_BARRIER_IN_SYSDBINIT=1 \
    container=docker

VOLUME /mnt/flash

COPY ceos-entrypoint.py \
     ceos-entrypoint-init.service \
     ceos-entrypoint-cli.service \
     /

RUN chmod +x /ceos-entrypoint.py \
    && mv /ceos-entrypoint-*.service /etc/systemd/system/ \
    && systemctl enable ceos-entrypoint-init ceos-entrypoint-cli

# Don't use STOPSIGNAL SIGRTMIN+3 on privileged container:
# systemd would remount the host filesystems RO on container stop
STOPSIGNAL SIGRTMIN+13
ENTRYPOINT [ \
    "/sbin/init", \
    "systemd.setenv=CEOS=1", \
    "systemd.setenv=EOS_PLATFORM=ceoslab", \
    "systemd.setenv=INTFTYPE=et", \
    "systemd.setenv=MGMT_INTF=et0", \
    "systemd.setenv=ETBA=1", \
    "systemd.setenv=SKIP_ZEROTOUCH_BARRIER_IN_SYSDBINIT=1" \
]
CMD []
