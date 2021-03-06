# opsipxeconfd

opsipxeconfd is part of the client management solution [opsi](https://www.opsi.org/).
There it is used to write named pipes for clients that boot over PXE to provide a one-time configuration.

The named pipes are _empty_ and will be filled on-the-fly once a read is requested. They will be removed after one read request.

## Usage

opsipxeconfd is usually running as a service.

    # Starting the service
    systemctl start opsipxeconfd.service
    # Stopping the service.
    systemctl stop opsipxeconfd.service

Manual control is also possible.

    opsipxeconfd start

The configuration is made through a configuration file. This file usually resides at `/etc/opsi/opsipxeconfd.conf`. Starting with a different configuration file is possible with:

    opsipxeconfd --conffile /path/to/configfile start

To avoid daemonizing you can use `--no-fork`. Along with setting a high log level through `--log-level` this can be used for debugging.

### Commandline Interface

opsipxeconfd has a simple CLI.

To check the version of opsipxeconfd:

    opsipxeconfd version

To check for connections:

    opsipxeconfd status

To update the boot configuration of a client:

    opsipxeconfd update <clientId>

To update the boot configuration of a client from a specific cache file:

	opsipxeconfd update <clientId> <path to cache file>

To stop opsipxeconfd:

    opsipxeconfd stop

