#!/usr/bin/env python3

# cEOS "entrypoint" script
#
# © 2021 Alexandre Levavasseur
# SPDX-License-Identifier: Apache-2.0

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations  # Py >= 3.7
import sys, argparse, logging, pathlib, re, os, time, subprocess

# EOS required environment variables
eos_default_environment = {
  'CEOS': '1',
  'EOS_PLATFORM': 'ceoslab',
  'INTFTYPE': 'et',
  'MGMT_INTF': 'eth0',
  'ETBA': '1',  # 4 = ?
  'SKIP_ZEROTOUCH_BARRIER_IN_SYSDBINIT': '1',
  # 'CEOS_PYTHON': '3',
  'container': 'docker',  # This one is for systemd
}
# Console command-lines
getty_cmdline = ['/usr/sbin/mingetty', '/dev/console', '--noclear']
cli_cmdline = ['/usr/bin/Cli', '-p', '15']
# Log entrypoint actions in:
log_file = '/ceos_entrypoint.log'


def main():
  arg_parser = argparse.ArgumentParser(
    description="Entrypoint script used to prepare the container for cEOS and "
                "facilitate it's use, integration, configuration"
  )
  arg_parser.add_argument(
    '--debug',
    action='store_true',
    help='Enable debug log level',
  )
  arg_subparsers = arg_parser.add_subparsers(dest='command', required=True)
  arg_subparser_init = arg_subparsers.add_parser(
    'init_container',
    help='Prepare (environment variables, interfaces name, system mac, serial '
         'number) and init container',
  )
  arg_subparser_init.add_argument(
    '--entrypoint-no-interface-rename',
    action='store_true',
    help="Don't try to rename interfaces to match INTFTYPE",
  )
  arg_subparser_init.add_argument(
    '--entrypoint-system-mac',
    type=CEOSEntrypoint.arg_system_mac,
    default='first',
    metavar='random|first|ab12.cd34.ef56|etX',
    help='Value to use to set SYSTEMMAC ; accepted values are: '
    '"random" to generate a random MAC", '
    '"first" to use the mac-address of the first interface, '
    'a mac-address, '
    'an interface name (after rename) which mac-address will be read',
  )
  arg_subparser_init.add_argument(
    '--entrypoint-change-system-mac',
    action='store_true',
    help='Change SYSTEMMAC in ceos-config after it has been set on first start',
  )
  arg_subparser_init.add_argument(
    '--entrypoint-serial',
    type=CEOSEntrypoint.arg_serial,
    default='ENV_HOSTNAME',
    metavar='SERIALNUMBER',
    help='Value to set as SERIALNUMBER in ceos-config, or "ENV_HOSTNAME" to '
         'put the hostname (default) ; no change if empty',
  )
  arg_subparser_init.add_argument(
    '--entrypoint-skip-config-hostname',
    action='store_true',
    help="Don't update hostname in the startup-configuration",
  )
  arg_subparser_init.add_argument(
    '--entrypoint-routing-model',
    choices=('ribd', 'multi-agent', 'force-ribd', 'force-multi-agent'),
    default='multi-agent',
    help='Set the routing protocol model in the startup-configuration ; cEOS '
    'default is "ribd" but this entrypoint defaults it to "multi-agent" ; when '
    'the "force" prefix is used, configuration is changed even when it already '
    'exists',
  )
  arg_subparser_init.add_argument(
    'init_arguments',
    nargs='*',
    help='Extra arguments to pass to init'
  )
  arg_subparser_getty = arg_subparsers.add_parser(
    'run_getty',
    help="Spawn (min)getty shell on pid1's stdio (container console)"
  )
  arg_subparser_getty.add_argument(
    'getty_arguments',
    nargs='*',
    help='Extra arguments to pass to (min)getty'
  )
  arg_subparser_cli = arg_subparsers.add_parser(
    'run_cli',
    help="Spawn Cli shell on pid1's stdio (container console)"
  )
  arg_subparser_cli.add_argument(
    'cli_arguments',
    nargs='*',
    help='Extra arguments to pass to Cli'
  )
  args = arg_parser.parse_args()

  ceos_entrypoint = CEOSEntrypoint(debug=args.debug)
  try:
    if args.command == 'init_container':
      if not args.entrypoint_no_interface_rename:
        ceos_entrypoint.rename_interfaces()
      ceos_entrypoint.ceos_config(
        system_mac=args.entrypoint_system_mac,
        change_system_mac=args.entrypoint_change_system_mac,
        serial=args.entrypoint_serial,
        routing_model=args.entrypoint_routing_model,
        set_hostname=not args.entrypoint_skip_config_hostname,
      )
      ceos_entrypoint.exec_init(args.init_arguments)
    elif args.command == 'run_getty':
      ceos_entrypoint.run_getty_on_console(args.getty_arguments)
    elif args.command == 'run_cli':
      ceos_entrypoint.run_cli_on_console(args.cli_arguments)
  except Exception as e:
    ceos_entrypoint.log.critical(e, exc_info=True)
    raise SystemExit(1)


class CEOSEntrypoint:
  """
  CEOS Entrypoint object to handle preparation of the container
  """

  ceos_config_path = pathlib.Path('/mnt/flash/ceos-config')
  startup_config_path = pathlib.Path('/mnt/flash/startup-config')
  init_cmdline = ['/sbin/init']

  def __init__(self, debug: bool = False):
    """
    Initialize object with logger and setup environment
    """
    self.log = self.init_logger(debug)
    self.fix_env()

  def init_logger(self, debug: bool) -> logging.Logger:
    """
    Initialize logger with formatter and handlers
    """
    handlers = (
      logging.StreamHandler(stream=sys.stderr),
      logging.FileHandler(log_file, mode='a', encoding='utf8')
    )
    formatter = logging.Formatter(
      fmt='{asctime}:{levelname}:{name}:{message}',
      datefmt=None,
      style='{'
    )
    logger = logging.getLogger('ceos-entrypoint')
    logging_level = logging.INFO
    if debug:
      logging_level = logging.DEBUG
    logger.setLevel(logging_level)
    for handler in handlers:
      handler.setFormatter(formatter)
      logger.addHandler(handler)
    return logger

  def fix_env(self) -> os._Environ:
    """
    Fix environment for the current and new processes, to ensure variables
    required by EOS are set
    """
    for environment_variable, default_value in eos_default_environment.items():
      if environment_variable not in os.environ or environment_variable == 'container':
        os.environ[environment_variable] = default_value
    return os.environ

  # ---

  def rename_interfaces(self):
    """
    Rename interface according to INTFTYPE (handle only 'eth' and 'et' prefixes)
    """
    intf_type = os.environ.get('INTFTYPE')
    if intf_type:
      self.log.info(
        f'Interface rename: designated management interface {os.environ.get("MGMT_INTF")!r} will not be considered '
        'if already correctly named'
      )
      interfaces = [interface for interface in self.list_interfaces() if interface != os.environ.get('MGMT_INTF')]
      interfaces_to_prefixes = {interface: self.natural_sort_key(interface)[0] for interface in interfaces}
      interfaces_prefixes = set(interfaces_to_prefixes.values())
      if intf_type not in interfaces_prefixes:
        if intf_type == 'et' and 'eth' in interfaces_prefixes:
          # Eth -> Et
          self.log.info('Renaming ethX interfaces to etX')
          for int_name, int_prefix in interfaces_to_prefixes.items():
            if int_prefix == 'eth':
              self.rename_interface(int_name, int_name.replace('eth', 'et'))
        elif intf_type == 'eth' and 'et' in interfaces_prefixes:
          # Et -> Eth
          self.log.info('Renaming etX interfaces to ethX')
          for int_name, int_prefix in interfaces_to_prefixes.values():
            if int_prefix == 'et':
              self.rename_interface(int_name, int_name.replace('et', 'eth'))
        else:
          self.log.warning(
            f"INTFTYPE set to {intf_type!r} but don't know which type to rename "
            f"from in the available types ([{', '.join(interfaces_prefixes)}])"
          )
      else:
        self.log.info(f'Interfaces seems to already be named {intf_type}X')
    else:
      self.log.info('INTFTYPE not found in environment variables, skipping interface rename')

  def rename_interface(self, old_name: str, new_name: str):
    """
    Rename an interface
    """
    self.log.info(f'Renaming interface {old_name!r} to {new_name!r}')
    try:
      common_kwargs = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=2,
        check=True,
        text=True
      )
      subprocess.run(('/usr/sbin/ip', 'link', 'set', old_name, 'down'), **common_kwargs)
      subprocess.run(('/usr/sbin/ip', 'link', 'set', old_name, 'name', new_name), **common_kwargs)
      subprocess.run(('/usr/sbin/ip', 'link', 'set', new_name, 'up'), **common_kwargs)
    except subprocess.TimeoutExpired as e:
      self.log.error(f'Renaming failed: command {" ".join(e.cmd)!r} did not returned within {e.timeout} seconds')
    except subprocess.CalledProcessError as e:
      self.log.error(f'Renaming failed: command {" ".join(e.cmd)!r} exited with non-zero ({e.returncode}) return code.')
      self.log.debug(f'stdout/stderr={e.stdout}')

  @staticmethod
  def natural_sort_key(value: str) -> tuple:
    """
    Return a natural sort key from a string
    """
    return tuple(int(part) if part.isdecimal() else part for part in re.split(r'([0-9]+)', value))

  @classmethod
  def list_interfaces(cls) -> list:
    """
    List interfaces, generate proper hostname if given
    """
    sysfs_interfaces = pathlib.Path('/sys/class/net/').iterdir()
    return sorted(
      (int_path.name for int_path in sysfs_interfaces if not re.match(r'^lo[0-9]*$', int_path.name)),
      key=cls.natural_sort_key
    )

  # ---

  @classmethod
  def arg_system_mac(cls, arg: str) -> str:
    """
    Process the system mac argument from choices: random|first|mac|int_name
    """
    arg = arg.strip()
    if arg.lower() == 'random':  # Random MAC
      return cls.sanitize_mac(os.urandom(6).hex())
    elif arg.lower() == 'first':  # MAC of first interface
      interfaces = cls.list_interfaces()
      with pathlib.Path(f'/sys/class/net/{interfaces[0]}/address').open('r') as interface_address_handle:
        return cls.sanitize_mac(re.sub(r'[^0-9a-fA-F]', '', interface_address_handle.read()))
    else:
      hexa_arg = re.sub(r'[^0-9a-fA-F]', '', arg)
      if len(hexa_arg) == 12:  # MAC given as argument
        return cls.sanitize_mac(hexa_arg)
      else:  # MAC from interface name
        if not re.fullmatch(r'[^/\0\s]{1,15}', arg):
          raise argparse.ArgumentTypeError('not a mac address and invalid as interface name')
        try:
          with pathlib.Path(f'/sys/class/net/{arg}/address').open('r') as interface_address_handle:
            return cls.sanitize_mac(re.sub(r'[^0-9a-fA-F]', '', interface_address_handle.read()))
        except OSError:
          raise argparse.ArgumentTypeError(
            'not a mac address or interface given to use as system mac not found or unreadable'
          )

  @staticmethod
  def sanitize_mac(mac: str, mac_fmt: str = '{}{}.{}{}.{}{}') -> str:
    """
    Return a mac address with U/L and I/G bits set to 0
    """
    normalized_mac = format(int(mac, 16) & ~0x03_00_00_00_00_00, '012x')
    mac_bytes = [normalized_mac[i:i + 2] for i in range(0, 12, 2)]
    return mac_fmt.format(*mac_bytes)

  @classmethod
  def arg_serial(cls, arg: str) -> str:
    """
    Process serial number argument (replace ENV_HOSTNAME to container hostname
    or use value with valid characters only)
    """
    arg = arg.strip()
    if arg == 'ENV_HOSTNAME':
      return cls.get_hostname()
    else:
      return arg

  @staticmethod
  def get_hostname() -> str:
    """
    Get sanitized hostname from environment variable HOSTNAME
    """
    return re.sub(r'[^0-9a-zA-Z.-]', '-', os.environ.get('HOSTNAME', ''))

  def ceos_config(
    self,
    system_mac: str,
    serial: str,
    routing_model: str,
    change_system_mac: bool = False,
    set_hostname: bool = True,
  ):
    """
    Setup/update ceos-config file with:
      * system mac
      * "serial number" (hostname)
      * routing model
    """
    # Ensure the file contains a system mac
    valid_system_mac = False
    if not change_system_mac:
      valid_system_mac = self._pattern_in_file(
        self.ceos_config_path,
        r'^SYSTEMMACADDR=[0-9a-fA-F:.-]{12,17}(?:$|\s+)'
      )
    if not valid_system_mac:
      self.log.info(f'ceos-config: setting SYSTEMMACADDR={system_mac!r}')
      self._replace_append_line_in_file(self.ceos_config_path, 'SYSTEMMACADDR=', system_mac)
    else:
      self.log.info('ceos-config: SYSTEMMACADDR unchanged')

    if serial:
      self.log.info(f'ceos-config: setting SERIALNUMBER={serial!r}')
      self._replace_append_line_in_file(self.ceos_config_path, 'SERIALNUMBER=', serial)
    else:
      self.log.info('ceos-config: no serial to set, skipping')

    hostname = self.get_hostname()
    if hostname:
      if set_hostname:
        self.log.info(f'startup-config: setting hostname to {hostname!r}')
        self._replace_append_line_in_file(self.startup_config_path, 'hostname ', hostname)
      else:
        self.log.info('startup-config: skipping setting hostname')
    else:
      self.log.warning('Container hostname not found in environment variables')

    set_routing_model = True
    # Check if the startup-config already contains a routing model configuration
    if not routing_model.startswith('force-'):
      set_routing_model = not self._pattern_in_file(
        self.startup_config_path,
        r'^service routing protocols model \S+(?:$|\s+)'
      )
    if set_routing_model:
      self.log.info(f'startup-config: setting service routing protocols model to {routing_model!r}')
      self._replace_append_line_in_file(
        self.startup_config_path,
        'service routing protocols model ',
        routing_model.replace('force-', '')
      )
    else:
      self.log.info('startup-config: service routing protocols model untouched')

  @staticmethod
  def _pattern_in_file(file: pathlib.Path, pattern: str):
    """
    Check if pattern is found in file
    """
    if not file.is_file():
      return False
    with file.open('r') as fh:
      return bool(re.search(pattern, fh.read(), re.M))

  @staticmethod
  def _replace_append_line_in_file(file: pathlib.Path, prefix: str, value: str):
    """
    Replace the first line beginning with `prefix` with `prefix+value`,
    or add the line at the end of the file
    """
    # Either touch()+open('r+') or open('a+')+seek(0)+truncate()
    # Because in 'a+' mode, any write will be at the end of the file
    with file.open('a+') as file_handle:
      found = False
      file_handle.seek(0)
      lines = file_handle.readlines()
      file_handle.seek(0)
      file_handle.truncate()
      for line in lines:
        if not found and line.startswith(prefix):
          found = True
          file_handle.write(f'{prefix}{value}\n')
        else:
          file_handle.write(line)
      if not found:
        file_handle.write(f'{prefix}{value}\n')

  # ---

  def get_init_cmdline(self) -> list:
    """
    Give init the right arguments
    """
    init_cmdline = self.init_cmdline.copy()
    for environment_variable in eos_default_environment.keys():
      init_cmdline.append(f'systemd.setenv={environment_variable}={os.environ.get(environment_variable)}')
    return init_cmdline

  def exec_init(self, additional_arguments: list):
    """
    Hand over to init
    """
    init_cmdline = self.get_init_cmdline()
    init_cmdline += additional_arguments
    self.log.info('Replacing entrypoint process with systemd init')
    self.log.info(f'init cmdline={" ".join(init_cmdline)}')
    try:
      import gc, atexit
      logging.shutdown()
      atexit._run_exitfuncs()
      gc.collect()
    except Exception:
      pass
    os.execve(init_cmdline[0], init_cmdline, os.environ)

  # ---

  def run_getty_on_console(self, additional_arguments: list):
    """
    Spawn (min)getty on /dev/console
    """
    # time.sleep(2)  # Handled with systemd.unit type=idle
    cmdline = getty_cmdline + additional_arguments
    self.log.info(f'getty cmdline={" ".join(cmdline)}')
    while True:
      self.log.info('Spawning getty on /dev/console')
      subprocess.run(
        cmdline,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
      )
      time.sleep(0.5)  # In case called process goes crazy

  # ---

  def run_cli_on_console(self, additional_arguments: list):
    """
    Spawn Cli on /dev/console
    """
    # time.sleep(2)  # Handled with systemd.unit type=idle
    import signal
    cmdline = cli_cmdline + additional_arguments
    self.log.info(f'Cli cmdline={" ".join(cmdline)}')
    with open('/dev/console', 'rb+', buffering=0) as console_fh:
      while True:
        self.log.info('Spawning Cli on /dev/console')
        console_fh.write(b'\n')
        console_fh.flush()
        # Handle ^C in Cli (because Python owns the console handle)
        original_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
        subprocess.run(
          cmdline,
          stdin=console_fh,
          stdout=console_fh,
          stderr=subprocess.STDOUT,
          start_new_session=True,
        )
        signal.signal(signal.SIGINT, original_handler)
        time.sleep(0.5)  # In case called process goes crazy


if __name__ == '__main__':
  main()
