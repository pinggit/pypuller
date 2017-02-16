#!/usr/bin/env python
import datetime
import multiprocessing
import threading
import sys, os
import logging
import imp
import subprocess
import signal
import yaml
import pprint
import argparse
from pprint import pprint as pp
from time import sleep, time
from lxml import etree
from jnpr.junos.utils.fs import FS
from jnpr.junos import Device
from jnpr.junos.utils.start_shell import StartShell
from jnpr.junos.utils.sw import SW
from jnpr.junos.utils.scp import SCP
from jnpr.junos.exception import *
options             = {}
options['user']     = 'labroot'       # -u, --user <USER>
options['password'] = 'lab123'        # -p, --password <PASSWORD>
options['router_file']   = './router-lists.txt'# -R, --router_file <ROUTER_FILE>
options['cli_file']      = './cli-lists.txt'   # -C, --cli_file <CLI_FILE>
options['yaml_file']     = './pypuller.yaml'   # -C, --cli_file <CLI_FILE>
options['log_dir']       = os.path.expanduser('~/pypuller_logs')
options['commit']        = False               # -g, --git
options['host_list'] = []
options['cli_list']  = []
options['normalize']     = True
options['package']       = '/var/tmp/junos-install-mx-x86-64-15.1F2-S13.tgz'
options['iteration_max'] = 2
options['iteration']     = 0
options['attempt_max']   = 2
options['attempt']       = 0
options['debug']         = 0
def myprogress(dev, report):            # {{{2}}}
    print "++++%s router %s ISSU progress: %s" % (curr_time(), dev.hostname,
													report)
def curr_time():                                # {{{2}}}
    return '{:%Y_%m_%d_%H_%M_%S}'.format(datetime.datetime.now())
def write_file(fname, string):          # {{{2}}}
    try:
        with open(fname, 'a') as f:
            mylogger.debug("write to file %s" % fname)
            f.write(string)
    except Exception as e:
        mylogger.debug("file write ERROR:" + fname)
        mylogger.debug(e)
def logger(args):                           # {{{2}}}
    logging.VERBOSE = 9 
    logging.addLevelName(logging.VERBOSE, "VERBOSE")
    def verbose(self, message, *args, **kws):
        if self.isEnabledFor(logging.VERBOSE):
            self._log(logging.VERBOSE, message, args, **kws) 
    logging.Logger.verbose = verbose
    if args.terse:
        root = multiprocessing.get_logger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        mylogger = multiprocessing.get_logger()
        multiprocessing.log_to_stderr()
    else:
        logger_name = "mylogger"
        root = logging.getLogger(logger_name)
        root = multiprocessing.get_logger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        mylogger = logging.getLogger(logger_name)
        log_path = "./pypuller.log"
        fh = logging.FileHandler(log_path)
        fh.setLevel(logging.VERBOSE)
        sh = logging.StreamHandler()
        sh.setLevel(logging.VERBOSE)
        fmt = "%(asctime)-15s %(levelname)s %(filename)s %(lineno)d %(process)d %(message)s"
        datefmt = "%a %d %b %Y %H:%M:%S"
        formatter = logging.Formatter(fmt, datefmt)
        fh.setFormatter(formatter)
        sh.setFormatter(formatter)
        mylogger.addHandler(fh)
        mylogger.addHandler(sh)
    return mylogger
def git_submit():                       # {{{1}}}
    global options
    log_dir = options['log_dir']
    logger.info('commit the new data')
    git_diff = "git diff"
    proc = subprocess.Popen(
            git_diff,
            shell  = True,
            cwd    = log_dir,
            stdin  = subprocess.PIPE,
            stdout = subprocess.PIPE,
    )
    proc.wait()
    git_add  = "git add -A ."
    subprocess.Popen(git_add  , shell=True , cwd=log_dir)
    git_cm   = "git commit -am 'new commit'"
    subprocess.Popen(git_cm   , shell=True , cwd=log_dir)
    git_st   = "git status"
    proc = subprocess.Popen(git_st   , shell=True , cwd=log_dir)
def get_master_re(host, user, password, attempt_max=10):         # {{{1}}}
    global re0, re1
    global dev, options
    normalize = options['normalize']
    for attempt in range(attempt_max):
        mylogger.debug("attempt (%s/%s)!" % (attempt, attempt_max))
        try:                            # {{{2}}}
            dev = Device(host=host, user=user, password=password,
                    normalize=normalize)
            dev.open()
            mylogger.info("%s connected!" % host)
            return dev
        except ConnectTimeoutError:     # {{{2}}}
	    mylogger.warn("%s:ConnectTimeOutError, will reconnect afer 10s..."
			   % host)
            sleep(10)
        except ConnectClosedError:      # {{{2}}}
            mylogger.warn("%s:ConnectClosedError, will reconnect afer 10s..." 
                    % host)
            sleep(10)
        except ConnectAuthError:        # {{{2}}}
            mylogger.warning(
                    "%s:ConnectAuthError, check the user name and password!"
                    % host)
            return None
        except ConnectRefusedError:     # {{{2}}}
            mylogger.warn("%s:ConnectRefusedError, check the router config!"
                    % host)
            return None
        except ConnectNotMasterError:   # {{{2}}}
            raise
            return None
        except:                         # {{{2}}}
            mylogger.warn("%s:unexpected error:" + sys.exc_info()[0])
def save_cli_thread(host, cli, fname=None):                 # {{{1}}}
    '''
    one thread: send one cli only and write the output
    '''
    global dev
    name = threading.currentThread().getName()
    mylogger.info('--->thread "%s" started, PID(%s)...' % \
                    (name, os.getpid())
    )
    start = time()
    cli_output = dev.cli(cli, warning=False)
    mylogger.verbose("output of cli '%s' looks:\n%s" % (cli, cli_output))
    write_file(fname, cli_output)
    end = time()
    mylogger.info('<---thread %s exited (%0.2f sec).' % \
                    (name, (end - start))
    )
def save_cli_process_mthread(options, host, fname=None): # {{{1}}}
    '''
    one process, to login one router
    then multi-threading, each for a cli
    '''
    global dev
    name = multiprocessing.current_process().name
    mylogger.info('===>Process %s started, PID(%s)...' % \
                    (name, os.getpid())
    )
    start = time()
    normalize_ori        = options['normalize']
    options['normalize'] = False
    hostname   = host
    user       = options['user']
    password   = options['password']
    cli_list   = options['cli_list']
    re0        = None
    re1        = None
    attempt_max = options['attempt_max']
    if options.get('host', {}):
        router_indiv = options['host'].get(host, [])
        if router_indiv:
            hostname = router_indiv[0].get('hostname', {})
            if not hostname:
                hostname = host
            re0 = router_indiv[0].get('re0', None)
            re1 = router_indiv[0].get('re1', None)
            access = router_indiv[0].get('access', {})
            if access:
                user = access.get('user', '')
                password = access.get('password', '')
                if not user:
                    user = options['user']
                if not password:
                    password = options['password']
            if len(router_indiv) > 1:
                cli_list = router_indiv[1].get('clies', [])
                if not cli_list:
                    cli_list = options['cli_list']
    mylogger.info("connecting to %s(%s) ..." % (host, hostname))
    try:
        dev = get_master_re(hostname, user, password, attempt_max)
    except ConnectNotMasterError:   # {{{2}}}
        if re0 and re1:
            mylogger.info("ConnectNotMasterError, connect to the other RE...")
            if host == re0:
                mylogger.info(" (since current RE0 is not master, go RE1...)")
                dev = get_master_re(re1, user, password, attempt_max)
            else:
                mylogger.info(" (since current RE1 is not master, go RE0...)")
                dev = get_master_re(re0, user, password, attempt_max)
        else:
            mylogger.info("ConnectNotMasterError, other RE info N/A...")
    if not dev:
        mylogger.info("%s login failed", host)
        return None
    options['normalize'] = normalize_ori
    if fname is None:
        fname = "%s_%s" % (dev.hostname, curr_time())
        fname = dev.hostname
        fname_full = options['log_dir'] + '/' + fname
    else:
        fname_full = fname
    mylogger.verbose("log file full path looks:" + fname_full)
    if os.path.isfile(fname_full):
        os.remove(fname_full)
    threads = []
    for cli in cli_list:
        t = threading.Thread(
                name='"' + cli + '"',
                target=save_cli_thread,
                args=(host, cli, fname_full)
        )
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    end = time()
    mylogger.info('<===Process %s exited (%0.2f sec).' % \
                    (name, (end - start))
    )
def save_cli_mprocess_mthread(options, fname=None): # {{{1}}}
    host_list = options['host_list']
    cli_list  = options['cli_list']
    jobs = []
    for host in host_list:
        mylogger.debug("get a host: %s" % host)
        process_name = "%s" % host
        p = multiprocessing.Process(name=process_name,
                                    target=save_cli_process_mthread,
                                    args=(options, host, fname))
        p.daemon = True
        jobs.append(p)
    for p in jobs:
        p.start()
    for p in jobs:
        p.join()
def args_gen(): # {{{1}}}
    parser = argparse.ArgumentParser()
    parser.add_argument('-u', action='store',
                        dest='user',
                        help='user name')
    parser.add_argument('-p', action='store',
                        dest='password',
                        help='password')
    parser.add_argument('-R', action='store',
                        dest='router_file',
                        help="a file that has list of routers")
    parser.add_argument('-C', action='store',
                        dest='cli_file',
                        help='a file that has list of CLIes')
    parser.add_argument('-l', action='store',
                        dest='log_dir',
                        help='log dir')
    parser.add_argument('-y', action='store',
                        dest='yaml_file',
                        help='yaml_file, use "NONE" to suppress')
    parser.add_argument('-r', action='append',
                        dest='host_list',
                        default=[],
                        help='Add hosts to a list')
    parser.add_argument('-c', action='append',
                        dest='cli_list',
                        default=[],
                        help='Add CLIes to a list')
    parser.add_argument('-g', action='store_true',
                        default=False,
                        dest='commit',
                        help='commit to repo (via git)')
    parser.add_argument('--version', action='version',
                        version='%(prog)s 1.0')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-d', '-dd', action='count',
                        default=0,
                        dest='debug',
                        help='increase debug verbosity, -dd for even more info')
    group.add_argument('-t', '--terse', action='store_true',
                        default=False,
                        dest='terse',
                        help='decrease verbosity')
    args = parser.parse_args()
    return args
def args_process(args, options): # {{{1}}}
    if not args.debug:
        mylogger.setLevel(logging.INFO)
    elif args.debug == 1:
        options['debug'] = args.debug
        mylogger.setLevel(logging.DEBUG)
    elif args.debug > 1:
        options['debug'] = args.debug
        mylogger.setLevel(logging.VERBOSE)
    mylogger.debug('command line options read:')
    mylogger.debug('debug = %r' % args.debug)
    mylogger.debug('user = %r' % args.user)
    mylogger.debug('password = %r' % args.password)
    mylogger.debug('router_file = %r' % args.router_file)
    mylogger.debug('cli_file = %r' % args.cli_file)
    mylogger.debug('log_dir = %r' % args.log_dir)
    mylogger.debug('host_list = %r' % args.host_list)
    mylogger.debug('cli_list = %r' % args.cli_list)
    mylogger.debug('commit = %r' % args.commit)
    if args.router_file is not None:
        options['router_file'] = args.router_file
    if args.cli_file is not None:
        options['cli_file'] = args.cli_file
    if os.path.isfile(options['router_file']):
        try:
            with open(options['router_file'], 'r') as f:
                for line in f:
                    if not line.strip() == '':
                        options['host_list'].append(line.strip())
        except Exception as e:
            print "file open ERROR:", options['router_file']
            print e
    if os.path.isfile(options['cli_file']):
        try:
            with open(options['cli_file'], 'r') as f:
                for line in f:
                    if not line.strip() == '':
                        options['cli_list'].append(line.strip())
        except Exception as e:
            print "file open ERROR", options['cli_file']
            print e
    mylogger.verbose("host_list read from %s: %s" % \
            (options['router_file'], options['host_list']))
    mylogger.verbose("cli_list read from %s: %s" % \
            (options['cli_file'], options['cli_list']))
    if args.yaml_file is not None:
        options['yaml_file'] = args.yaml_file
        if args.yaml_file == "NONE":
            options['yaml_file'] = None
    if options['yaml_file'] and os.path.isfile(options['yaml_file']):
        fyaml = file(options['yaml_file'], 'r')
        pyaml = yaml.load_all(fyaml)
        pyaml_list = list(pyaml)
        mylogger.verbose("the yaml data looks:")
        if options['debug'] > 1:
            pp(pyaml_list)
        y0 = pyaml_list[0]
        y1 = pyaml_list[1]
        y1_routers = [a for a in y1 if a not in ['hosts', 'clies']]
        options['host']         = {}
        for router in y1_routers:
            options['host'][router] = y1[router]
        if pyaml_list[1].get('hosts') is not None:
            options['host_list'] = y1_routers + y1['hosts']
        if pyaml_list[1].get('clies') is not None:
            options['cli_list']  = y1['clies']
    mylogger.debug("host_list after read from %s: %s" % \
            (options['yaml_file'], options['host_list']))
    mylogger.debug("cli_list after read from %s: %s" % \
            (options['yaml_file'], options['cli_list']))
    if args.user is not None:
        options['user'] = args.user
    if args.password is not None:
        options['password'] = args.password
    if args.log_dir is not None:
        options['log_dir'] = args.log_dir
    if not os.path.exists(options['log_dir']):
        os.makedirs(options['log_dir'])
    if args.commit is not None:
        options['commit'] = args.commit
    if args.host_list:
        options['host_list'] = args.host_list
    if args.cli_list:
        options['cli_list'] = args.cli_list
    mylogger.debug("final host_list: %s" % options['host_list'])
    mylogger.debug("final cli_list: %s" % options['cli_list'])
    mylogger.debug("after processing command line argument options looks:")
    if options['debug'] > 1:
        pp(options)
    return options
def main():                     # {{{1}}}
    global options
    global mylogger
    args = args_gen()
    mylogger = logger(args)
    options = args_process(args, options)
    name = multiprocessing.current_process().name
    mylogger.info('====Parent process %s started, PID(%s)...' % \
                    (name, os.getpid())
    )
    start = time()
    save_cli_mprocess_mthread(options)
    if options['commit']:
        git_submit()
    end = time()
    mylogger.info('====Task %s runs %0.2f seconds.' % \
                    (name, (end - start))
    )
if __name__ == '__main__':          # {{{1}}}
    main()
