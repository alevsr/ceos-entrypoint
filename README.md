# Arista cEOS entrypoint

## Description

Arista provides cEOS, a containerized version of EOS, in a `lab` edition for
educational purpose. But this version is provided in the raw `tar` format which
requires setting proper and mandatory environment variables to be usable, plus
generating one value in `/mnt/flash/ceos-config` and renaming the interfaces to
have some features to be fully functional.

The native launch sequence looks like:

```sh
docker create \
  --name=my_ceos --privileged -i -t \
  -e CEOS=1 \
  -e EOS_PLATFORM=ceoslab \
  -e INTFTYPE=eth \
  -e ETBA=1 \
  -e SKIP_ZEROTOUCH_BARRIER_IN_SYSDBINIT=1 \
  -e container=docker \
  ceosimage:4.27.0F \
  /sbin/init \
    systemd.setenv=CEOS=1 \
    systemd.setenv=EOS_PLATFORM=ceoslab \
    systemd.setenv=INTFTYPE=eth \
    systemd.setenv=ETBA=1 \
    systemd.setenv=SKIP_ZEROTOUCH_BARRIER_IN_SYSDBINIT=1 \
    systemd.setenv=container=docker

# Then to get the Cli prompt:
docker exec -it my_ceos Cli

# Then you need to generate a proper `system mac` (and it's a bit late to rename
# interfaces)
```

This entrypoint allows to build an out-of-the-box working image, taking care of:

* populating the required environment variables and passing them to
`systemd/init`
* renaming the interfaces according to `INTFTYPE` (`et` naming required for
`OSPF` and/or `ISIS` to work)
* generating a proper (UL/IG bits set to `0`) `system mac` (required for `MLAG`
to work at least)
* setting the `serial number`
* setting the `hostname`
* spawning continuously a prompt (`Cli`) on the console after the boot

## How to build

To build the image, place the cEOS `tar` file from Arista in the build context
(ie. this directory) then use the following snippet:

```sh
CEOS_64=64  # or `CEOS_64=` for the 32bit variant
CEOS_EDITION=lab
CEOS_VERSION=4.27.0F
docker build \
  --build-arg "CEOS_64=${CEOS_64}" \
  --build-arg "CEOS_EDITION=${CEOS_EDITION}" \
  --build-arg "CEOS_VERSION=${CEOS_VERSION}" \
  --tag arista-ceos:${CEOS_EDITION}${CEOS_64}-${CEOS_VERSION} \
  --tag arista-ceos:latest .
```

This will build an image tagged twice: one with the version
(`arista-ceos:lab64-4.27.0F` here) and one latest (`arista-ceos:latest`).

The built image can be used directly in GNS3 without setting any environment
variable.

## How to use in GNS3

See [the dedicated doc (gns3.md)](gns3.md).

## Misc

### Notes

Thanks Arista for open-sourcing ATD `=)`

You can find informations on cEOS at:

* <https://eos.arista.com/ceos-lab-in-gns3/>
* <https://eos.arista.com/veos-ceos-gns3-labs/>
* <https://eos.arista.com/ceos-lab-topo/>
  * <https://eos.arista.com/arista-robot-testing/>
  * <https://eos.arista.com/network-ci-part-3/>

This entrypoint was inspired by the containerlab cEOS container manager
(except this script runs inside the container):

* <https://containerlab.srlinux.dev/manual/kinds/ceos/>
* <https://github.com/srl-labs/containerlab/blob/v0.19.0/nodes/ceos/ceos.go>

### License

This project is released under [Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0)
([SPDX](https://spdx.org/licenses/Apache-2.0.html)).

### Systemd units for the console

#### About `ceos-console-getty.service` vs `ceos-console-cli.service`

It is possible to spawn a prompt on the console in 2 ways, with their own
advantages:

* for `getty` (enabled by default):
  * users logins are logged and correctly listed in `show users detail`
  * having a login prompt allows to test authentication (local and external
    sources, like TACACS+, ..)
  * (technical: Python doesn't own the console handle, it only spawn the process
    which will)
* for `Cli`:
  * since it spawn a full privilege `admin` shell, it provides an easy backup /
    backdoor access
    * such backup access can also be provided using
      `docker exec -it my_container Cli -p 15` if required

`mingetty` can be configured to enable autologin (see
`ceos-console-getty.service`) but the shell is unprivileged by default.

#### About `ceos-console-cli-systemd.service` and `ceos-console-getty-systemd.service`

`Cli` could be (re)launched directly by `init/systemd`, but inside the container
systemd is complaining about the dependencies of a dozen units each time this
unit starts, so instead Python is used to handle the restart without spamming
the console.

The alternative units launching `Cli` or `Agetty` directly are left if you
prefer them however, or want to try to fix the messages ; adjust the
`Dockerfile` in consequence to use them.

#### Arista unit `serial-getty@ttyS0.service`

While this unit was not designed for a container console, it could be hijacked
for the console, but would suffers the systemd messages issues, plus a
dependency to `dev-console.device` which is never met. It is also missing an
`Install` section.

To test:

```sh
cp -a "/etc/systemd/system/serial-getty@ttyS0.service" "/etc/systemd/system/multi-user.target.wants/serial-getty@console.service"
```

#### Native units `container-getty@.service`, `getty@.service`

The native units suffers the same systemd messages, plus `getty.target` missing.
This one can be restored by putting <https://github.com/systemd/systemd/blob/v219/units/getty.target>
at `/usr/lib/systemd/system/getty.target`.

The `getty` unit can then be enabled using `systemctl enable getty@console`, but
it will display the prompt before EOS finished booting.

The `container-getty` can also be started using `systemctl start container-getty@0`
but it is missing an `Install` section.

### Entrypoint script arguments

```text
$ python ceos_entrypoint.py -h
usage: ceos_entrypoint.py [-h] [--debug] {init_container,run_cli} ...

Entrypoint script used to prepare the container for cEOS and facilitate it's use, integration, configuration

positional arguments:
  {init_container,run_cli}
                        command
    init_container      Prepare (environment variables, interfaces name, system mac, serial number) and init container
    run_cli             Spawn Cli shell on pid1's stdio (console)

optional arguments:
  -h, --help            show this help message and exit
  --debug               Enable debug log level


$ python ceos_entrypoint.py init_container -h
usage: ceos_entrypoint.py init_container [-h] [--entrypoint-no-interface-rename] [--entrypoint-system-mac random|first|ab12.cd34.ef56|etX] [--entrypoint-change-system-mac]
                                         [--entrypoint-serial SERIALNUMBER] [--entrypoint-skip-config-hostname]
                                         [init_arguments ...]

positional arguments:
  init_arguments        Extra arguments to pass to init

optional arguments:
  -h, --help            show this help message and exit
  --entrypoint-no-interface-rename
                        Don't try to rename interfaces to match INTFTYPE
  --entrypoint-system-mac random|first|ab12.cd34.ef56|etX
                        Value to use to set SYSTEMMAC ; accepted values are: "random" to generate a random MAC", "first" to use the mac-address of the first interface, a mac-
                        address, an interface name (after rename) which mac-address will be read
  --entrypoint-change-system-mac
                        Change SYSTEMMAC in ceos-config after it has been set on first start
  --entrypoint-serial SERIALNUMBER
                        Value to set as SERIALNUMBER in ceos-config, or "ENV_HOSTNAME" to put the hostname (default) ; no change if empty
  --entrypoint-skip-config-hostname
                        Don't update hostname in the startup-configuration


$ python ceos_entrypoint.py run_cli -h
usage: ceos_entrypoint.py run_cli [-h] [cli_arguments ...]

positional arguments:
  cli_arguments  Extra arguments to pass to Cli

optional arguments:
  -h, --help     show this help message and exit
```

### Resources

Some Arista resources:

* <https://eos.arista.com/forum/can-ceos-inherit-docker-assigned-ip-address-on-management-interface/>
* <https://eos.arista.com/mlag-basic-configuration/>

Some resources used to construct this:

* Natural sort
  * <https://stackoverflow.com/questions/4836710/is-there-a-built-in-function-for-string-natural-sort>
* Subprocess
  * <https://stackoverflow.com/questions/1196074/how-to-start-a-background-process-in-python>
    * <https://stackoverflow.com/questions/4256107/running-bash-commands-in-python/51950538#51950538>
      * <https://nedbatchelder.com/text/unipain.html>
  * <https://stackoverflow.com/questions/1605520/how-to-launch-and-run-external-script-in-background#>
  * <https://linux.die.net/man/2/setsid>
  * <https://stackoverflow.com/questions/22916783/reset-python-sigint-to-default-signal-handler>
  * <https://github.com/fish-shell/fish-shell/issues/7247>
  * <https://man7.org/linux/man-pages/man7/signal.7.html>
* systemd
  * <https://unix.stackexchange.com/questions/460324/is-there-a-way-to-wait-for-boot-to-complete>
    * `systemctl is-system-running | grep -qE "running|degraded"`
  * <https://serverfault.com/questions/617398/is-there-a-way-to-see-the-execution-tree-of-systemd>
    * `sudo systemctl list-dependencies`
    * `systemd-analyze critical-chain`
  * <https://www.freedesktop.org/software/systemd/man/systemd.special.html>
  * <https://www.freedesktop.org/software/systemd/man/bootup.html>
  * <https://wiki.archlinux.org/title/Systemd>
  * <https://www.freedesktop.org/software/systemd/man/systemd-system.conf.html>
  * <https://stackoverflow.com/questions/43001223/how-to-ensure-that-there-is-a-delay-before-a-service-is-started-in-systemd>
  * <https://www.freedesktop.org/software/systemd/man/systemd.html>
  * <https://www.freedesktop.org/software/systemd/man/systemd.service.html>
  * <https://unix.stackexchange.com/questions/573041/how-can-i-send-specific-sig-signal-to-systemd>
  * <https://www.freedesktop.org/software/systemd/man/systemctl.html>
  * <https://www.freedesktop.org/software/systemd/man/systemd.exec.html>
  * <https://www.freedesktop.org/software/systemd/man/systemd.service.html>
  * <https://www.freedesktop.org/software/systemd/man/systemd.unit.html>
  * <https://unix.stackexchange.com/questions/289629/systemd-restart-always-is-not-honored>
  * <https://github.com/systemd/systemd/tree/v219/man>
  * <https://unix.stackexchange.com/questions/485156/what-is-dev-console-used-for>
  * <https://www.freedesktop.org/software/systemd/man/systemd.html>
  * <https://www.freedesktop.org/software/systemd/man/systemctl.html>
  * <https://linux.die.net/man/7/runlevel>
  * <https://askubuntu.com/questions/816285/what-is-the-difference-between-systemctl-mask-and-systemctl-disable>
* Terminal hijack
  * <https://github.com/dsnet/termijack>
  * <https://stackoverflow.com/questions/46181452/python-how-to-write-to-and-read-from-an-existing-pseudoterminal-pty-pts>
  * <https://stackoverflow.com/questions/5374255/how-to-write-data-to-existing-processs-stdin-from-external-process>
  * <https://www.mkssoftware.com/docs/man1/stty.1.asp>
  * <https://superuser.com/questions/640338/how-to-reset-a-broken-tty/640341>
    * `echo ^v^o`
    * `reset`
    * `printf "\033c"`
    * `stty sane`
    * <https://unix.stackexchange.com/questions/79684/fix-terminal-after-displaying-a-binary-file/79686#79686>
      * `alias fix='reset; stty sane; tput rs1; clear; echo -e "\033c"'`
  * <https://stackoverflow.com/questions/26413847/terminal-messed-up-not-displaying-new-lines-after-running-python-script>
  * <https://stackoverflow.com/questions/2084508/clear-terminal-in-python>
  * <https://stackoverflow.com/questions/38244830/running-bash-in-subprocess-breaks-stdout-of-tty-if-interrupted-while-waiting-on>
  * <https://docs.python.org/3/library/termios.html>
  * <https://stackoverflow.com/questions/46181452/python-how-to-write-to-and-read-from-an-existing-pseudoterminal-pty-pts>
  * <https://stackoverflow.com/questions/36102622/sending-curses-applications-output-to-tty1>
  * <http://blog.rtwilson.com/how-to-fix-warning-terminal-is-not-fully-functional-error-on-windows-with-cygwinmsysgit/>
* Docker
  * <https://docs.docker.com/engine/reference/builder/#understand-how-cmd-and-entrypoint-interact>
  * <https://docs.docker.com/develop/develop-images/baseimages/>
  * <https://github.com/Yelp/dumb-init>
    * <http://cr.yp.to/daemontools.html>
    * <http://supervisord.org/>
  * <https://github.com/krallin/tini>
  * <https://developers.redhat.com/blog/2014/05/05/running-systemd-within-docker-container>
  * <https://developers.redhat.com/blog/2016/09/13/running-systemd-in-a-non-privileged-container#docker_upstream_vs__systemd>
  * <https://developers.redhat.com/blog/2019/04/24/how-to-run-systemd-in-a-container>
  * <https://stackoverflow.com/questions/54727907/running-systemd-in-docker-container-causes-host-crash>
  * <https://forge.univention.org/bugzilla/show_bug.cgi?id=43455>
    * <https://docs.software-univention.de/release-notes-4.2-0-en.html>
    * <https://www.freedesktop.org/wiki/Software/systemd/ContainerInterface/>
* Linux interfaces
  * <https://unix.stackexchange.com/questions/451368/allowed-chars-in-linux-network-interface-names>
  * <https://access.redhat.com/solutions/652593>
* getty
  * <https://linux.die.net/man/8/mingetty>
  * <https://linux.die.net/man/8/agetty>
  * <http://0pointer.de/blog/projects/serial-console.html>
  * <https://www.freedesktop.org/software/systemd/man/systemd-getty-generator.html>
  * <https://man7.org/linux/man-pages/man2/setsid.2.html>
