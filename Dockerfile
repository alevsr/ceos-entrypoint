# cEOS "entrypoint" script
# © 2021 Alexandre Levavasseur
# SPDX-License-Identifier: Apache-2.0
#
# Usage:
# > CEOS_64=64 CEOS_EDITION=lab CEOS_VERSION=4.27.0F
# > docker build \
#   --build-arg "CEOS_64=${CEOS_64}" \
#   --build-arg "CEOS_EDITION=${CEOS_EDITION}" \
#   --build-arg "CEOS_VERSION=${CEOS_VERSION}" \
#   --tag arista-ceos:${CEOS_EDITION}${CEOS_64}-${CEOS_VERSION} \
#   --tag arista-ceos:latest .

FROM scratch
ARG CEOS_64=64
ARG CEOS_EDITION=lab
ARG CEOS_VERSION=4.27.0F
ARG CONSOLE=getty

ADD cEOS${CEOS_64}-${CEOS_EDITION}-${CEOS_VERSION}.tar /

# Theses are the defaults used by the entrypoint script ;
# if required, override them here or at container creation time
# ENV CEOS=1 \
#     EOS_PLATFORM=ceoslab \
#     INTFTYPE=et \
#     MGMT_INTF=eth0 \
#     ETBA=1 \
#     SKIP_ZEROTOUCH_BARRIER_IN_SYSDBINIT=1 \
#     container=docker

VOLUME /mnt/flash

COPY ceos_entrypoint.py \
     ceos-console-cli.service \
     ceos-console-getty.service \
     /

RUN chmod +x /ceos_entrypoint.py \
    && mv \
        /ceos-console-getty.service \
        /ceos-console-cli.service \
        /etc/systemd/system/ \
    && systemctl enable ceos-console-${CONSOLE} \
    && systemctl mask shutdown.target umount.target

# Don't use STOPSIGNAL SIGRTMIN+3 on privileged container with shutdown.target
# unmasked: systemd would remount the host filesystems RO on container stop
STOPSIGNAL SIGRTMIN+13
ENTRYPOINT ["/ceos_entrypoint.py", "init_container"]
CMD []
