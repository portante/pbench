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

""" Log pcp metric data """

import subprocess
import os
import socket
import time
import logging
import json
import argparse
import shutil
from pcp import pmapi
from pcp.pmapi import pmContext as PCP
import cpmapi as api

CWD = os.getcwd()
PORT = 44321 

class PCPPmlogger():
    """ Log pcp metric data """
    
    def __init__(self, hosts, tools):
        """
        input: takes list of hosts and tools
        what init function does:
        1. checks whether pmcd is active amongst the hosts mentions in the list.
        2. reads the pcp-mappig file.
        3. builds the pmlogger configuration based on the tools based on the list using pmlogconf tool.
        4. builds the control file required by pmlogger_check tool.
        for more info on pmlogconf and pmlogger_check check respective man pages.
        """
        # save external state
        self.temp_hosts, self.temp_tools = hosts, tools
        # initialize internal state
        self.logger = ""
        self.hosts, self.tools = [], []
        self.pmlog_config_files = []
        self.mapping = dict()
        self.control_file = os.path.join(CWD, '.temp', 'pcppmlogger.d')
        self.log_dir = os.path.join(CWD, 'results')
        # call init functions
        self.start_logger()
        self.check_connection(self.temp_hosts)
        self.read_json(os.path.join('/home/ashwin/github/gsoc/pbench/agent/util-scripts/pcpint', 'pcp-mapping.json'))
        self.build_pmlog_configs(self.hosts, self.tools)
        self.build_control_file(self.hosts)
    
    def start_logger(self):
        """ starting logging process """
        logging.basicConfig(filename='pmlogger.log',
                            filemode='w',
                            format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                            datefmt='%H:%M:%S',
                            level=logging.DEBUG)

        self.logger = logging.getLogger('pmlogger')
    
    def read_json(self, json_fn):
        """ read json file """
        try:
            self.logger.info("Reading the pcp mapping file")
            self.logger.debug("Reading file:%s", json_fn)
            with open(os.path.join(json_fn)) as json_file:
                self.mapping = json.loads(json_file.read())
        except Exception as e:
            self.logger.critical("Not able to load the mapping file\n:%s", e, exc_info=True)

    def start_logging(self):
        """ invoke pmlogger and start logging using pmlogger_check -c """
        # code to start logging
        self.logger.info("starting logger")

        command = PCP.pmGetConfig('PCP_BINADM_DIR') + '/pmlogger_check -c {}'.format(self.control_file)
        self.logger.debug("start logger command:%s", command)
        out = subprocess.Popen([command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        stdout, stderr = out.communicate()
        self.logger.debug("start logger command stdout:%s",stdout.decode())

        if stdout.decode() != "":
            # pmlogger failed to start. Log it
            self.logger.error("not able to start logger successfully")
        else:
            self.logger.info("logger started successfully")
                
    def stop_logging(self):
        """ stop logging using pmlogger_check -s """
        # code to stop logging
        self.logger.info("stop logger")

        command = PCP.pmGetConfig('PCP_BINADM_DIR') + '/pmlogger_check -s -c {}'.format(self.control_file)
        self.logger.debug("stop logger command:%s", command)
        out = subprocess.Popen([command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        stdout, stderr = out.communicate()
        self.logger.debug("stop logger command stdout:%s",stdout.decode())

        if stdout.decode() != "":
            # pmlogger failed to stop. Log it
            self.logger.error("not able to stop logger successfully")
        else:
            self.logger.info("logger stopped successfully")
        
        # All processes done, do cleanup
        self.cleanup()

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
                self.tools.append(self.temp_tools[idx]) # appending the given hosts tool group
            else:
                self.logger.error("Port 44321 is not open in:{}".format(host))
                self.logger.error("Ignoring host:%s", host)

    def build_pmlog_configs(self, hosts, tools):
        """ Build pmlog config files for each host. Returns true/false depending on success or failure in building files """
        self.logger.info("building pmlogger config files")

        for index, host in enumerate(hosts):
            # make a folder with name CWD/temp/host
            try:
                os.mkdir('.temp')
                self.logger.debug("Created folder :{}".format(os.path.join(CWD, '.temp')))
            except:
                self.logger.debug("Folder :{} already exists".format(os.path.join('.temp')))

            try:
                os.mkdir(os.path.join('.temp', host))
                self.logger.debug("Created folder :{}".format(os.path.join('.temp', host)))
            except:
                self.logger.debug("Folder :{} already exists".format(os.path.join('.temp', host)))

            try:
                for _, tool in enumerate(tools[index]):
        
                        try:
                            string = ""
                            string += "#pmlogconf-setup 2.0\n"
                            string += "ident   "+ self.mapping[tool]["ident"] + "\n"
                            string += "probe   "+ self.mapping[tool]["probe"] + " ? include : exclude\n\n"
                            for _, metric in enumerate(self.mapping[tool]["metrics"]):
                                string += "   " + metric + "\n"
                            
                            self.logger.debug("%s.summary output for host %s :\n%s", host, host, string)
                            with open(os.path.join('.temp', host, tool+'.summary'), "w") as file:
                                file.write(string)
                        except:
                            self.logger.error("tool:%s does not exist in mapping", tool)
                
                # code to build pmlogger configuration file
                self.logger.info("building pmlogger configuration file")
                command = 'pmlogconf -c -h {} -d {} {}.config '.format(host, os.path.join('.temp', host), host)
                self.logger.debug("pmlogconf command:%s", command)
                out = subprocess.Popen([command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
                stdout, stderr = out.communicate()
                self.logger.debug("stdout output:%s", stdout.decode())

                if stdout.decode().strip() != "":
                    # pmlogger failed to stop. Log it
                    self.logger.error("not able to build pmlogconf file")
                else:
                    self.logger.info("built config file for host:{}".format(host))

                self.pmlog_config_files.append("{}.config".format(host))
            except Exception as e:
                # log exception as we are not able to stop logger
                self.logger.error("not able to create a logger conf file\n", e, exc_info=True )

    def build_control_file(self, hosts):
        """ build control.d file. returns true/false depending on success or failure in building files"""
        self.logger.info("building pmlogger control file")
        self.logger.debug("pmlogger config files:%s", str(self.pmlog_config_files))
        string = ""

        # insert version
        string += "$version=1.1 \n" 

        for idx, host in enumerate(hosts):
            # build control file
            string += "{}  n  n {}  -r -T1m -c {}\n".format(host, os.path.join(self.log_dir,host), self.pmlog_config_files[idx])
            
        # save the file
        self.logger.debug("The control file\n:%s", string)
        self.logger.debug("The control file name:%s and stored at:%s", self.control_file, CWD)
        try:
            with open(self.control_file, 'w') as file:
                file.write(string)
            self.logger.info("successfully built the control file")
        except Exception as e:
            # log exception
            self.logger.critical("error in build_control file\n:%s", e, exc_info=True)
    
    def cleanup(self):
        """ Remove all temporary files """
        # Remove directory created for generating pmlogconf files
        try:
            # remove all the config files
            for path in self.build_pmlog_configs:
                os.remove(path)
        except Exception as e:
            self.logger.error("Error removing config files\n%s", e, exc_info=True)
            # remove the temp dir
        try:    
            shutil.rmtree('.temp')
            self.logger.info("deleted the .temp dir and config files")
        except Exception as e:
            self.logger.error("error removing the .temp directory\n%s",e, exc_info=True)

            
if __name__ == '__main__':
    # Initiate the parser
    parser = argparse.ArgumentParser(description="Log pcp metric data")

    # Add long and short argument for input
    parser.add_argument('-i','--input',action='append', nargs=1, help='input of form host,tool1,tool2,...toolN')

    # Read arguments from the command line
    args = parser.parse_args()

    host= []
    tools = []

    for val in args.input:
        val = val[0].split(',')
        host.append(val[0])
        tools.append(val[1:])

        obj = PCPPmlogger(host, tools)

        # start logging
        obj.start_logging()

        # sleep for 10 seconds for testing purpose
        time.sleep(10)

        # stop logging
        obj.stop_logging()