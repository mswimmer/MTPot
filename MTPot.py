#!/usr/bin/env python2.7

import argparse
import logging
import gevent, gevent.server
from telnetsrv.green import TelnetHandler, command
import traceback

from config import HoneyConfig, MissingConfigField
from syslog_logger import get_syslog_logger

COMMANDS = {}
COMMANDS_EXECUTED = {}
BUSY_BOX = "/bin/busybox"
MIRAI_SCANNER_COMMANDS = ["shell", "sh", "enable"]
FINGERPRINTED_IPS = []

honey_logger = logging.getLogger("HoneyTelnet")
syslogger = None
config = None

class MyTelnetHandler(TelnetHandler):
    WELCOME = 'welcome'
    PROMPT = ">"
    authNeedUser = True
    authNeedPass = True

    @command(MIRAI_SCANNER_COMMANDS)
    def shell_respond(self, params):
        self.writeresponse("")

    @command([BUSY_BOX])
    def handle_busybox(self, params):
        full_response = self.get_busybox_response(params)
        honey_logger.debug(
            "[%s:%d] Responding: %s",
            self.client_address[0],
            self.client_address[1],
            full_response.strip())
        self.writeresponse(full_response)

    def is_fingerprinted(self):
        if all([COMMANDS_EXECUTED[self.client_address[0]].count(cmd) > 0 for cmd in COMMANDS]):
            honey_logger.info(
                "%s: confirmed IP: [%s:%d]",
                config.ddos_name,
                self.client_address[0],
                self.client_address[1])
            if syslogger:
                syslogger.info(
                    "%s: confirmed IP: [%s:%d]",
                    config.ddos_name,
                    self.client_address[0],
                    self.client_address[1])
            FINGERPRINTED_IPS.append(self.client_address[0])
            return True
        else:
            return False

    def store_command(self, cmd):
        honey_logger.debug(
            "[%s:%d] executed: %s",
            self.client_address[0],
            self.client_address[1],
            cmd.strip())
        if syslogger:
            syslogger.debug(
                "[%s:%d] executed: %s",
                self.client_address[0],
                self.client_address[1],
                cmd.strip())
        if self.client_address[0] in FINGERPRINTED_IPS:
            return
        if not COMMANDS_EXECUTED.has_key(self.client_address[0]):
            COMMANDS_EXECUTED[self.client_address[0]] = [cmd]
        else:
            COMMANDS_EXECUTED[self.client_address[0]].append(cmd)
        self.is_fingerprinted()

    def get_busybox_response(self, params):
        response = ""
        full_command = " ".join(params)
        for cmd in full_command.split(";"):
            cmd = cmd.strip()
            # Check for busy box executable
            if cmd.startswith(BUSY_BOX):
                cmd = cmd.replace(BUSY_BOX, "")
                cmd = cmd.strip()
            response += COMMANDS.get(cmd, "") + "\n"
            self.store_command(cmd)
        return response

    def authCallback(self, username, password):
        honey_logger.info(
            "[%s:%d] logon credentials used: user:%s pass:%s",
            self.client_address[0],
            self.client_address[1],
            username,
            password)

    def writeerror(self, text):
        '''Called to write any error information (like a mistyped command).
        Add a splash of color using ANSI to render the error text in red.
        see http://en.wikipedia.org/wiki/ANSI_escape_code'''
        #print("user error: %s" % text)
        pass
        #self.writeerror(self, "\x1b[91m%s\x1b[0m" % text )

    def session_start(self):
        '''Called after the user logs in.'''
        honey_logger.debug("[%s:%d] session started", self.client_address[0], self.client_address[1])

    def session_end(self):
        '''Called after the user logs off.'''
        honey_logger.debug("[%s:%d] session ended", self.client_address[0], self.client_address[1])

    def handleException(self, exc_type, exc_param, exc_tb):
        # Overide default exception handling behavior
        honey_logger.debug(traceback.format_exc())
        return True

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'config',
        type=str,
        help='Path to a json config file, see README for all available parameters')
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        required=False,
        help='Increase MTPot verbosity')
    parser.add_argument(
        '-o',
        '--output',
        type=str,
        required=False,
        help='Output the results to this file')
    return parser.parse_args()


def main():
    global COMMANDS
    global syslogger
    global config

    args = get_args()
    config = HoneyConfig(args.config)
    if args.output:
        logging.basicConfig(
            filename = args.output,
            level=logging.INFO,
            format='%(asctime)s [%(name)s] %(levelname)s %(filename)s:%(lineno)s %(message)s')
    else:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(name)s] %(levelname)s %(filename)s:%(lineno)s %(message)s')
    if args.verbose:
        honey_logger.setLevel(logging.DEBUG)
    try:
        syslogger = get_syslog_logger(config.syslog_address, config.syslog_port, config.syslog_protocol)
        if args.verbose:
            syslogger.setLevel(logging.DEBUG)
        honey_logger.info(
            "Setup syslog with parameters: IP:%s, PORT:%d, PROTOCOL:%s",
            config.syslog_address,
            config.syslog_port,
            config.syslog_protocol)
    except MissingConfigField:
        honey_logger.info("Syslog reporting disabled, to enable it add its configuration to the configuration file")
    COMMANDS = config.commands
    server = gevent.server.StreamServer((config.ip, 23), MyTelnetHandler.streamserver_handle)
    honey_logger.info("Listening on %d...", 23)
    server.serve_forever()

if __name__ == '__main__':
    main()
