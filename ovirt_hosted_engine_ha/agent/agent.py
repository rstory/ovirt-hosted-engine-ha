#
# ovirt-hosted-engine-ha -- ovirt hosted engine high availability
# Copyright (C) 2013 Red Hat, Inc.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#

from __future__ import print_function

import ConfigParser
import daemon
import grp
import logging
import logging.config
from optparse import OptionParser
import os
import pwd
import signal
import sys
import time

from ..lib import util
from ..lib import exceptions as ex
from . import constants
from . import hosted_engine


class Agent(object):
    def __init__(self):
        self._shutdown = False

    def run(self):
        parser = OptionParser(version=constants.FULL_PROG_NAME)
        parser.add_option("--no-daemon", action="store_false",
                          dest="daemon", help="don't start as a daemon")
        parser.add_option("--pdb", action="store_true",
                          dest="pdb", help="start pdb in case of crash")
        parser.add_option("--cleanup", action="store_true",
                          dest="cleanup", help="purge the metadata block")
        parser.add_option("--force-cleanup", action="store_true",
                          dest="force_cleanup", help="purge the metadata block"
                                                     "even when not clean")
        parser.add_option("--host-id", action="store", default=None,
                          type="int", dest="host_id",
                          help="override the host id")

        parser.set_defaults(daemon=True)
        (options, args) = parser.parse_args()

        def action_proper(he):
            return he.start_monitoring()

        def action_clean(he):
            return he.clean(options.force_cleanup)

        action = action_proper
        retries = constants.AGENT_START_RETRIES
        errcode = 0

        if options.cleanup:
            options.daemon = False
            action = action_clean
            retries = 1

        self._initialize_logging(options.daemon)
        self._log.info("%s started", constants.FULL_PROG_NAME)

        self._initialize_signal_handlers()

        try:
            self._log.debug("Verifying execution as root")
            if os.geteuid() != 0:
                raise Exception("This program must be run as root")

            vdsm_uid = pwd.getpwnam(constants.VDSM_USER).pw_uid
            vdsm_gid = grp.getgrnam(constants.VDSM_GROUP).gr_gid

            self._log.debug("Writing pid file")
            util.mkdir_recursive(os.path.dirname(constants.PID_FILE))
            os.chown(os.path.dirname(constants.PID_FILE), vdsm_uid, vdsm_gid)
            with open(constants.PID_FILE, 'w') as f:
                f.write(str(os.getpid()) + "\n")

            # FIXME exit if another ha-agent instance is already running...
            # can use python-lockfile since it's already available

            self._log.debug("Running as %s:%s (%d:%d)",
                            constants.VDSM_USER, constants.VDSM_GROUP,
                            vdsm_uid, vdsm_gid)
            if hasattr(os, 'initgroups'):
                os.initgroups(constants.VDSM_USER, vdsm_gid)
            else:
                vdsm_gids = [g.gr_gid for g in grp.getgrall()
                             if constants.VDSM_USER in g.gr_mem]
                vdsm_gids.append(vdsm_gid)
                os.setgroups(vdsm_gids)
            os.setgid(vdsm_gid)
            os.setuid(vdsm_uid)

            if options.daemon:
                self._log.debug("Running agent as daemon")
                # The logger expects its file descriptors to stay open
                logs = [x.stream for x in logging.getLogger().handlers
                        if hasattr(x, "stream")]
                logs.extend([x.socket for x in logging.getLogger().handlers
                             if hasattr(x, "socket")])
                self._log.debug("Preserving {0}".format(logs))

                with daemon.DaemonContext(signal_map=self._get_signal_map(),
                                          files_preserve=logs):
                    errcode = self._run_agent(action,
                                              options.host_id, retries)
            else:
                self._log.debug("Running agent in foreground")
                errcode = self._run_agent(action, options.host_id, retries)

        except Exception as e:
            self._log.critical("Could not start ha-agent", exc_info=True)
            print("Could not start ha-agent: {0} (see log for details)"
                  .format(str(e)), file=sys.stderr)
            if options.pdb:
                import pdb
                pdb.post_mortem()
            sys.exit(-98)
        except KeyboardInterrupt:
            if options.pdb:
                import pdb
                pdb.post_mortem()

        # Agent shutdown...
        self._log.info("Agent shutting down")
        os.unlink(constants.PID_FILE)
        sys.exit(errcode)

    def _initialize_logging(self, is_daemon):
        try:
            logging.config.fileConfig(constants.LOG_CONF_FILE,
                                      disable_existing_loggers=False)
            if not is_daemon:
                handler = logging.StreamHandler()
                handler.setLevel(logging.DEBUG)
                handler.setFormatter(logging.Formatter(
                    "%(levelname)s:%(name)s:%(message)s"))
                logging.getLogger('').addHandler(handler)
        except (ConfigParser.Error, ImportError, NameError, TypeError):
            logging.basicConfig(filename='/dev/stdout', filemode='w+',
                                level=logging.DEBUG)
            log = logging.getLogger("%s.Agent" % __name__)
            log.warn("Could not inititialize logging", exc_info=True)
        self._log = logging.getLogger("%s.Agent" % __name__)

    def _get_signal_map(self):
        return {signal.SIGINT: self._handle_quit,
                signal.SIGTERM: self._handle_quit}

    def _initialize_signal_handlers(self):
        for signum, handler in self._get_signal_map().iteritems():
            signal.signal(signum, handler)

    def _handle_quit(self, signum, frame):
        # Remain re-entrant
        self._shutdown = True

    def shutdown_requested(self):
        return self._shutdown

    def _run_agent(self, action, host_id=None,
                   retries=constants.AGENT_START_RETRIES):
        # Only one service type for now, run it in the main thread

        for attempt in range(retries):
            try:
                he = hosted_engine.HostedEngine(self.shutdown_requested,
                                                host_id=host_id)

                # if we're here, the agent stopped gracefully,
                # so we don't want to restart it
                return action(he)

            except hosted_engine.ServiceNotUpException as e:
                self._log.error("Service %s is not running and the admin"
                                " is responsible for starting it."
                                " Waiting..." % e.message)
            except ex.DisconnectionError as e:
                self._log.error("Disconnected from broker '{0}'"
                                " - reinitializing".format(str(e)))
            except (ex.BrokerInitializationError, ex.BrokerConnectionError)\
                    as e:
                self._log.error("Can't initialize brokerlink '{0}'"
                                " - reinitializing".format(str(e)))
            except Exception as e:
                self._log.error("Error: '{0}' - trying to restart agent"
                                .format(str(e)))

            time.sleep(constants.AGENT_START_RETRY_WAIT)
            self._log.warn("Restarting agent, attempt '{0}'".format(attempt))
        else:
            self._log.error("Too many errors occurred, giving up. "
                            "Please review the log and consider filing a bug.")
            return -99
