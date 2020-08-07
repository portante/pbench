#!/usr/bin/env python

# Copyright (C) 2020 Ashwin Nayak <ashwinnayak111@gmail.com>

# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.

# pylint: disable=bad-whitespace, line-too-long, too-many-return-statements
# pylint: disable=broad-except, too-many-branches, too-many-statements, inconsistent-return-statements
# pylint: disable=no-name-in-module, too-many-instance-attributes, no-self-use

""" launch pmie inference on metric data """

import subprocess
import os
import socket
import time
import logging
import json
import argparse
from pcp import pmapi
from pcp.pmapi import pmContext as PCP
import cpmapi as api

CWD = os.getcwd()
PORT = 44321 

class PCPPmie():
    """ Log pcp metric data """
    
    def __init__(self, hosts):
        """
        input: takes list of hosts
        what init function does:
        1. checks whether pmcd is active amongst the hosts mentions in the list.
        2. builds the pmie configuration file.
        3. builds the control file required by pmie_check tool.
        for more info on pmieconf and pmie_check check respective man pages.
        """
        self.logger = ""
        self.pmie_config_file = os.path.join(CWD, 'pmie.config')
        self.control_file = os.path.join(CWD, 'pmie.d')
        self.log_dir = os.path.join(CWD, 'pmie')
        self.hosts = []

        self.start_logger()
        self.check_connection(hosts)
        self.build_pmie_config()
        self.build_pmie_control_file(self.hosts)

    def start_logger(self):
        """ starting logging process """
        logging.basicConfig(filename='pmie.log',
                            filemode='w',
                            format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                            datefmt='%H:%M:%S',
                            level=logging.DEBUG)

        self.logger = logging.getLogger('pmie')

    def start_pmie(self):
        """ invoke pmie and start using pmie_check -c """
        # code to start logging
        self.logger.info("starting pmie")
        command = PCP.pmGetConfig('PCP_BINADM_DIR') + '/pmie_check -c {}'.format(self.control_file)
        self.logger.debug("start pmie command: %s", command)
        out = subprocess.Popen([command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        stdout, stderr = out.communicate()
        self.logger.debug("start pmie command output:%s", stdout.decode())

        if stdout.decode() != "":
            # pmie failed. Log it
            self.logger.error("not able to start pmie successfully due to:{}".format(stdout))
        else:
            self.logger.info("pmie started successfully")
                
    def stop_pmie(self):
        """ stop pmie using pmie_check -s """
        # stopping pmie
        self.logger.info("stopping pmie")
        command = PCP.pmGetConfig('PCP_BINADM_DIR') + '/pmie_check -s -c {}'.format(self.control_file)
        self.logger.debug("stop pmie command: %s", command)
        out = subprocess.Popen([command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        stdout, stderr = out.communicate()
        self.logger.debug("stop pmie command output:%s", stdout.decode())

        if stdout.decode() != "":
            # pmie failed. Log it
            self.logger.error("not able to stop pmie successfully due to:{}".format(stdout))
        else:
            self.logger.info("pmie stopped successfully")

    def check_connection(self, hosts):
        """ Check if pmcd is running in given list of hosts"""
        self.logger.info("checking connection")

        for idx, host in enumerate(hosts):
            res = ""
            try:
                self.logger.debug("checking connection on host:%s", host)
                res = pmapi.pmContext(api.PM_CONTEXT_HOST, host+":44321")
            except:
                res = None

            if res is not None:
                self.logger.info("Port 44321 is open in:{}".format(host))
                self.hosts.append(host) # logging only on those hosts with port 44321 active
            else:
                self.logger.error("Port 44321 is not open in:{}".format(host))
                self.logger.error("Ignoring host:%s", host)

    def build_pmie_config(self):
        """ Build pmie config files for each host. Returns true/false depending on success or failure in building files """
        # building pmie config file
        self.logger.info("building pmie config file")
        command = 'pmieconf -c {}'.format(self.pmie_config_file)
        self.logger.debug(" build pmie config command: %s", command)
        out = subprocess.Popen([command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        stdout, stderr = out.communicate()
        self.logger.debug("build pmie config command output:%s", stdout.decode())

        if stdout.decode() != "":
            # pmie failed. Log it
            self.logger.error("not able to build pmie config successfully due to:{}".format(stdout))
        else:
            self.logger.info("pmie config built successfully")
    
    def build_pmie_control_file(self, hosts):
        """ build control.d file. returns true/false depending on success or failure in building files"""

        string = ""

        # insert version
        string += "$version=1.1 \n" 

        for idx, host in enumerate(hosts):
            # build control file
            string += "{}  n  n {}  -c {}\n".format(host, os.path.join(self.log_dir, host), self.pmie_config_file)
            
        # save the file
        self.logger.debug("pmie.d file output:%s", string)
        try:
            with open(self.control_file, 'w') as file:
                file.write(string)
            self.logger.info("build pmie.d control file succesfully")
        except Exception as e:
            # log exception
            self.logger.error("error in build_control file:{}".format(e))
    
    def cleanup(self):
        # remove all temp gen files
        os.remove('pmie.config')
        os.remove('pmie.d')

if __name__ == '__main__':
    # Initiate the parser
    parser = argparse.ArgumentParser(description="launch pmie inference on metric data")

    # Add long and short argument for input
    parser.add_argument('-i','--input',action='append', nargs=1, help='input of form host1,host2,...hostN')

    # Read arguments from the command line
    args = parser.parse_args()

    for val in args.input:
        host = val[0].split(',')

        obj = PCPPmie(host)

        # start logging
        obj.start_pmie()

        # sleep for 10 seconds for testing purpose
        time.sleep(10)

        # stop logging
        obj.stop_pmie()