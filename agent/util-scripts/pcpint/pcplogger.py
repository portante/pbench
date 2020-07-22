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
from pcp import pmapi
from pcp.pmapi import pmContext as PCP
import cpmapi as api

CWD = os.getcwd()
PORT = 44321 

class PCPRedis():
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
        self.logger = logging.getLogger('pcp-pbench')

        self.temp_hosts, self.temp_tools = hosts, tools
        self.hosts, self.tools = [], []
        self.pmlog_config_files = []
        self.mapping = dict()
        self.control_file = os.path.join(CWD, 'pcp-pbench.d')
        self.log_dir = os.path.join(CWD, 'results')

        self.check_connection(self.temp_hosts)
        self.read_json(os.path.join(CWD, 'pcp-mapping.json'))
        self.build_pmlog_configs(self.hosts, self.tools)
        self.build_control_file(self.hosts)
    
    def read_json(self, json_fn):
        """ read json file """
        try:
            with open(os.path.join(CWD, json_fn)) as json_file:
                self.mapping = json.loads(json_file.read())
        except IOError:
            self.log.error("Not able to load the mapping file\n")

    def start_logging(self):
        """ invoke pmlogger and start logging using pmlogger_check -c """
        # code to start logging
        self.logger.info("starting logger")
        command = PCP.pmGetConfig('PCP_BINADM_DIR') + '/pmlogger_check -c {}'.format(self.control_file)
        out = subprocess.Popen([command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        stdout, stderr = out.communicate()

        if stdout != None:
            # pmlogger failed to log. Log it
            self.logger.error("not able to start log successfully due to:{}".format(stdout))
        else:
            self.logger.info("logger started successfully")
                
    def stop_logging(self):
        """ stop logging using pmlogger_check -s """
        try:
            # code to stop logging
            self.logger.info("stopping logging")
            command = PCP.pmGetConfig('PCP_BINADM_DIR') + '/pmlogger_check -s {}'.format(self.control_file)
            out = subprocess.Popen([command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
            stdout, stderr = out.communicate()
        
        except Exception as e:
            # log exception as we are not able to stop logger
            self.logger.error("not able to stop log successfully due to:{}".format(e))

    def check_connection(self, hosts):
        """ Check if pmcd is running in given list of hosts"""
        for idx, host in enumerate(hosts):
            res = ""
            try:
                res = pmapi.pmContext(api.PM_CONTEXT_HOST, host+":44321")
            except:
                res = None

            if res is not None:
                self.logger.info("Port 44321 is open in:{}".format(host))
                self.hosts.append(host) # logging only on those hosts with port 44321 active
                self.tools.append(self.temp_tools[idx]) # appending the given hosts tool group
            else:
                self.logger.error("Port 44321 is not open in:{}".format(host))

    def build_pmlog_configs(self, hosts, tools):
        """ Build pmlog config files for each host. Returns true/false depending on success or failure in building files """

        for index, host in enumerate(hosts):
            # make a folder with name CWD/temp/host
            try:
                os.mkdir(os.path.join(CWD, 'temp'))
                self.logger.info("Created folder :{}".format(os.path.join(CWD, 'temp')))
            except:
                self.logger.info("Folder :{} already exists".format(os.path.join(CWD, 'temp')))
                pass

            try:
                os.mkdir(os.path.join(CWD, 'temp', host))
                self.logger.info("Created folder :{}".format(os.path.join(CWD, 'temp', host)))
            except:
                self.logger.info("Folder :{} already exists".format(os.path.join(CWD, 'temp', host)))
                pass

            # check if the tool is present in mapping
            try:
                self.mapping[tools[index]]
                self.logger.info("tool is present in mapping")
            except:
                self.logger.error("tool not present in mapping, not logging")
                continue

            try:
                for _, tool in enumerate(tools[index]):
        
                        string = ""
                        string += "#pmlogconf-setup 2.0\n"
                        string += "ident "+ self.mapping[tool]["ident"] + "\n"
                        string += "probe "+ self.mapping[tool]["probe"] + " exists ? include : exclude\n\n"
                        for _, metric in enumerate(self.mapping[tool]["metrics"]):
                            string += "   " + metric + "\n"
                        
                        try:
                            os.mkdir(os.path.join(CWD, 'temp', host, tool))
                        except:
                            pass
                        
                        with open(os.path.join(CWD, 'temp', host, tool, 'pmlogconf.summary'), "w") as file:
                            file.write(string)
                
                # code to build pmlogger configuration file
                self.logger.info("building pmlogger configuration file")
                command = 'pmlogconf -h {} -d {} {}.config'.format(host, os.path.join(CWD, 'temp', host), host)
                out = subprocess.Popen([command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
                stdout, stderr = out.communicate()

                self.pmlog_config_files.append(os.path.join(CWD, "{}.config".format(host)))
                self.logger.info("built config file for host:{}".format(host))
    
            except Exception as e:
                # log exception as we are not able to stop logger
                self.logger.error("not able to create a logger conf file due to:{}".format(e))
            
        # All successful
        os.rmdir(os.path.join(CWD, 'temp'))
        return True
    
    def build_control_file(self, hosts):
        """ build control.d file. returns true/false depending on success or failure in building files"""

        string = ""

        # insert version
        string += "$version=1.1 \n" 

        for idx, host in enumerate(hosts):
            # build control file
            string += "{}  n  n {}  -r -T1m -c {}\n".format(host, os.path.join(self.log_dir,host), self.pmlog_config_files[idx])
            
        # save the file
        try:
            with open(os.path.join(CWD, self.control_file), 'w') as file:
                file.write(string)

        except Exception as e:
            # log exception
            self.logger.error("error in build_control file:{}".format(e))
            return False
        
        # Successful
        return True


# if __name__ == '__main__':

#     logging.basicConfig(filename='pcp-redis.log',
#                             filemode='a',
#                             format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
#                             datefmt='%H:%M:%S',
#                             level=logging.DEBUG)

#     logging.info("Running program")

#     obj = PCPRedis(['127.0.0.1'], [['tool1', 'tool2']])

#     # start logging
#     obj.start_logging()

#     # sleep for 10 seconds for testing purpose
#     time.sleep(10)

#     # stop logging
#     obj.stop_logging()