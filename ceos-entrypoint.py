#!/usr/bin/env python3
#
# cEOS "entrypoint" script
# © 2021 Alexandre Levavasseur
# Thank you for open-sourcing ATD

import sys, argparse, logging, time, os, subprocess, pathlib, re


def main():
  arg_parser = argparse.ArgumentParser(
    epilog='You can set en environment variable "CEOS_ENTRYPOINT_DEBUG" to '
    'a truthy value to enable debug logging'
  )
  arg_subparsers = arg_parser.add_subparsers(help='action', required=True, dest='action')
  arg_subparser_init = arg_subparsers.add_parser('prepare_container', help='Prepare container')
  arg_subparser_cli  = arg_subparsers.add_parser('run_cli_on_pid1_stdio', help="Spawn Cli shell on pid1's stdio")
  args = arg_parser.parse_args()

  ceos_entrypoint = CEOSEntrypoint()
  try:
    if args.action == 'prepare_container':
      ceos_entrypoint.rename_interfaces()
      ceos_entrypoint.ceos_config()
    elif args.action == 'run_cli_on_pid1_stdio':
      ceos_entrypoint.run_cli_on_pid1_stdio()
  except Exception as e:
    ceos_entrypoint.log.critical(e, exc_info=True)
    raise SystemExit(1)


class CEOSEntrypoint:
  """"""

  eos_default_environment = {
    'CEOS': '1',
    'EOS_PLATFORM': 'ceoslab',
    'INTFTYPE': 'et',
    'MGMT_INTF': 'et0',
    'ETBA': '1',
    'SKIP_ZEROTOUCH_BARRIER_IN_SYSDBINIT': '1',
    'container': 'docker',
  }
  ceos_config_path = pathlib.Path('/mnt/flash/ceos-config')
  startup_config_path = pathlib.Path('/mnt/flash/startup-config')
  cli_cmdline = ('/usr/bin/Cli', '-p', '15')
  log_file = '/var/log/ceos-entrypoint.log'

  def __init__(self):
    self.log = self.init_logger()
    self.interfaces = None

  def init_logger(self):
    """"""
    handlers = (
      logging.StreamHandler(stream=sys.stderr),
      logging.FileHandler(self.log_file, mode='a', encoding='utf8')
    )
    formatter = logging.Formatter(
      fmt='{asctime}:t={relativeCreated:05.4g}s:{levelname}:{name}:{message}',
      datefmt=None,
      style='{'
    )
    logger = logging.getLogger('ceos-entrypoint')
    logging_level = logging.INFO
    if os.environ.get('CEOS_ENTRYPOINT_DEBUG', '').lower() in {'1', 'y', 'yes', 'true'}:
      logging_level = logging.DEBUG
    logger.setLevel(logging_level)
    for handler in handlers:
      handler.setFormatter(formatter)
      logger.addHandler(handler)
    return logger

  @staticmethod
  def natural_sort_key(value):
    """"""
    return tuple(int(part) if part.isdecimal() else part for part in re.split('([0-9]+)', value))

  def list_interfaces(self):
    """
    List interfaces, generate proper hostname if given
    """
    sysfs_interfaces = pathlib.Path('/sys/class/net/').iterdir()
    return sorted((int_path.name for int_path in sysfs_interfaces if not re.match('^lo[0-9]*$', int_path.name)), key=self.natural_sort_key)

  def gen_system_mac(self):
    """"""
    interfaces = self.list_interfaces()
    with pathlib.Path(f'/sys/class/net/{interfaces[0]}/address').open('r') as first_interface_address_handle:
      first_mac = first_interface_address_handle.read().strip()

    first_mac_hexa = re.sub('[^0-9a-fA-F]', '', first_mac)
    # Force the first byte to 00 because the one generated might contain unwanted bits set (like local-link 0x02)
    return f'00{first_mac_hexa[2:4]}.{first_mac_hexa[4:8]}.{first_mac_hexa[8:12]}'

  def get_hostname(self):
    """"""
    if os.environ.get('HOSTNAME'):
      return re.sub('[^0-9a-zA-Z.-]', '-', os.environ.get('HOSTNAME'))
    return False

  def ceos_config(self):
    """
    Setup/update ceos-config file with system mac and "serial number"
    """
    hostname = self.get_hostname()
    ceos_config_generated = False
    if not self.ceos_config_path.is_file():
      ceos_config_generated = True
      # Otherwise generate a proper system mac with the hostname as serial number
      system_mac = self.gen_system_mac()
      self.log.info(f'Generating ceos-config with system_mac={system_mac!r}, serialnumber={hostname!r}')
      with self.ceos_config_path.open('w') as ceos_config_handle:
        print(f'SYSTEMMACADDR={system_mac}', file=ceos_config_handle)
        if hostname:
          print(f'SERIALNUMBER={hostname}', file=ceos_config_handle)
    if hostname:
      if not ceos_config_generated and self.ceos_config_path.is_file():
        # Update the serial number to reflect the hostname if it's given
        self.log.info(f'Updating ceos-config with serialnumber={hostname!r}')
        self._replace_line_in_file(self.ceos_config_path, 'SERIALNUMBER=', hostname)
      if not self.startup_config_path.is_file():
        self.log.info(f'Creating startup-config with hostname={hostname!r}')
        with self.startup_config_path.open('w') as startup_config_handle:
          print(f'hostname {hostname}', file=startup_config_handle)
      else:
        self.log.info(f'Updating startup-config with hostname={hostname!r}')
        self._replace_line_in_file(self.startup_config_path, 'hostname ', hostname)

  def _replace_line_in_file(self, file, prefix, value):
    """"""
    with file.open('r+') as file_handle:
      ceos_config_lines = file_handle.readlines()
      file_handle.seek(0)
      file_handle.truncate()
      for line in ceos_config_lines:
        if line.startswith(prefix):
          file_handle.write(f'{prefix}{value}\n')
        else:
          file_handle.write(line)

  def rename_interfaces(self):
    """
    Rename interface according to INTFTYPE (handle only 'eth' and 'et' prefixes)
    """
    intf_type = os.environ.get('INTFTYPE')
    if intf_type:
      interfaces = self.list_interfaces()
      interfaces_to_prefixes = {interface: self.natural_sort_key(interface)[0] for interface in interfaces}
      interfaces_prefixes = set(interfaces_to_prefixes.values())
      if intf_type not in interfaces_prefixes:
        if intf_type == 'et' and 'eth' in interfaces_prefixes:
          # Eth -> Et
          self.log.info(f'Renaming ethX interfaces to etX')
          for int_name, int_prefix in interfaces_to_prefixes.items():
            if int_prefix == 'eth':
              self.rename_interface(int_name, int_name.replace('eth', 'et'))
        elif intf_type == 'eth' and 'et' in interfaces_prefixes:
          # Et -> Eth
          self.log.info(f'Renaming etX interfaces to ethX')
          for int_name, int_prefix in interfaces_to_prefixes.values():
            if int_prefix == 'et':
              self.rename_interface(int_name, int_name.replace('et', 'eth'))
        else:
          # Want to rename to xx but don't know what source to use from {}
          self.log.warning(
            f"INTFTYPE set to {intf_type!r} but don't know which type to rename"
            f"from in [{', '.join(interfaces_prefixes)}]"
          )
      else:
        self.log.info(f'Interfaces seems to already be named {intf_type}X')
    else:
      self.log.info('INTFTYPE not found in environment variables, skipping interface rename')

  def rename_interface(self, old_name, new_name):
    """"""
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

  def run_cli_on_pid1_stdio(self):
    """"""
    # time.sleep(2)  # Handled with systemd.unit type=idle
    with open('/proc/1/fd/0', 'rb') as init_stdin, \
         open('/proc/1/fd/1', 'wb') as init_stdout, \
         open('/proc/1/fd/2', 'wb') as init_stderr:
      init_stdout.write(b'\n')
      init_stdout.flush()
      while True:
        self.log.info('Spawning a shell using stdio from init')
        subprocess.run(self.cli_cmdline, stdin=init_stdin, stdout=init_stdout, stderr=init_stderr)
        time.sleep(0.5)  # In case Cli goes crazy


if __name__ == '__main__':
  main()
