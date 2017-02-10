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
from pprint import pprint as pp
from time import sleep, time
from lxml import etree
from jnpr.junos.utils.fs import FS
from jnpr.junos import Device
from jnpr.junos.utils.start_shell import StartShell
from jnpr.junos.utils.sw import SW
from jnpr.junos.utils.scp import SCP
from jnpr.junos.exception import *
logger_name = "mylogger"
root = logging.getLogger(logger_name)
for handler in root.handlers[:]:
    root.removeHandler(handler)
mylogger = logging.getLogger(logger_name)
mylogger.setLevel(logging.INFO)
mylogger.setLevel(logging.DEBUG)
sh = logging.StreamHandler()
sh.setLevel(logging.DEBUG)
fmt = "%(asctime)-15s %(levelname)s %(filename)s %(lineno)d %(process)d %(message)s"
datefmt = "%a %d %b %Y %H:%M:%S"
formatter = logging.Formatter(fmt, datefmt)
sh.setFormatter(formatter)
mylogger.addHandler(sh)
masterre      = '172.19.161.123'
re0           = '172.19.161.124'
re0           = 'idefix-re0.ultralab.juniper.net'
re1           = '172.19.161.125'
re1           = 'idefix-re1.ultralab.juniper.net'
normalize     = True
package       = '/var/tmp/junos-install-mx-x86-64-15.1F2-S13.tgz'
iteration_max = 2
iteration     = 0
attempt_max   = 2
attempt       = 0
user          = 'labroot'
password      = 'lab123'
router_file   = './router-lists.txt'
cli_file      = './cli-lists.txt'
log_dir       = os.path.expanduser('~/pypuller_logs')
if not os.path.exists(log_dir): os.makedirs(log_dir)
commit        = False
'''
apply_async doesn't work with nested function (issu).
cPickle.PicklingError: Can't pickle <type 'function'>: attribute lookup
    __builtin__.function failed
workarounded by Process call
'''
def rsi():                              # {{{2}}}
    global dev
    name = multiprocessing.current_process().name
    print '====%s Run task %s, PID(%s)...' % (curr_time(), name, os.getpid())
    start = time()
    ss = StartShell(dev)
    ss.open()
    ss.run('cli -c "request support information | save information.txt"')
    with SCP(dev, progress=True) as scp:
        scp.get('information.txt', 'info.txt')
    ss.close()
def get_config():                       # {{{2}}}
    global dev
    cnf = dev.rpc.get_config()
    print etree.tostring(cnf, method='text', pretty_print="True")
def fs():                                       # {{{2}}}
    fs = FS(dev)
    pprint(fs.ls('/var/tmp'))
def show_chassis_fpc():              # {{{2}}}
    global dev, attempt, attempt_max
    global host, user, password
    global re0
    name = multiprocessing.current_process().name
    print '====%s Run task %s, PID(%s)...' % (curr_time(), name, os.getpid())
    start = time()
    while attempt <= attempt_max:       # {{{3}}}
        try:                            # {{{4}}}
            print "====%s get rpc now via %s..." % (curr_time(), dev)
            fpc_info = dev.rpc.get_fpc_information()
            print (etree.tostring(fpc_info))
            dev.cli("show chassis fpc", warning=False)
            break
        except Exception:                      # {{{4}}}
            get_master_re(host=re1, user='labroot',password='lab123')
            show_chassis_fpc()
            return
    fpcs = fpc_info.findall("fpc")
    for fpc in fpcs:
        fpcslot = fpc.findtext("slot")
        fpcstate = fpc.findtext("state")
        print "fpc: %s, state: %s" % (fpcslot, fpcstate)
def test_show_chassis_fpc():        # {{{2}}}
    name = multiprocessing.current_process().name
    print '====%s Run task %s, PID(%s)...' % (curr_time(), name, os.getpid())
    start = time()
    global iteration_max, dev
    iteration = 0
    while iteration < iteration_max:
        iteration += 1
        print "====%s #%s show_chassis_fpc iteration!" % (curr_time(), iteration)
        show_chassis_fpc()
    print "====%s #%s iterations of show_chassis_fpc done, exit!" % \
                                        (curr_time(), iteration_max)
    end = time()
    print '====%s Task %s runs %0.2f seconds.' % (curr_time(), name, (end - start))
def upgrade():                    # {{{2}}}
    global dev, package
    sw = SW(dev)
    ok = sw.install(package=package, progress=myprogress)
    if ok:
        print 'rebooting'
        sw.reboot()
def save_cli_process(host, cli, fname=None):                 # {{{2}}}
    '''
    one process, to login one router
    '''
    global dev, normalize
    name = multiprocessing.current_process().name
    print '====%s Run task %s, PID(%s)...' % (curr_time(), name, os.getpid())
    start = time()
    normalize = False
    dev = get_master_re(host, user, password)
    normalize = True
    if fname is None:
        fname = "%s_%s" % (dev.hostname, curr_time())
        fname = dev.hostname
    cli_output = dev.cli(cli)
    write_file(fname, cli_output)
    end = time()
    print '====%s Task %s runs %0.2f sec.' % (curr_time(), name, (end - start))
def save_cli_mthread(host, cli_list, fname=None):                 # {{{2}}}
    '''
    multi-threading:
    for one host, iterate cli_list with multiple threads
    '''
    global dev, normalize
    name = multiprocessing.current_process().name
    print '====%s Run task %s, PID(%s)...' % (curr_time(), name, os.getpid())
    start = time()
    normalize = False
    dev = get_master_re(masterre, user, password)
    normalize = True
    if fname is None:
        fname = "%s_%s" % (dev.hostname, curr_time())
        fname = dev.hostname
    threads = []
    for cli in cli_list:
        t = threading.Thread(
                name=cli,
                target=save_cli_thread,
                args=(host, cli, fname)
        )
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    end = time()
    print '====%s Task %s runs %0.2f sec.' % (curr_time(), name, (end - start))
def save_cli_mprocess(host_list, cli, fname=None):              # {{{2}}}
    jobs = []
    for router in host_list:
        logging.debug("get a router: %s" % router)
        process_name = "%s" % router
        p = multiprocessing.Process(name=process_name,
                                    target=save_cli_process,
                                    args=(router, cli, fname))
        p.daemon = True
        jobs.append(p)
    for p in jobs:
        p.start()
    for p in jobs:
        p.join()
def issu(user, password):         # {{{2}}}
    global package, attempt_max, attempt, dev
    global iteration
    dev.open()
    sw = SW(dev)
    while attempt <= attempt_max:
        print "++++%s #%s attempt in #%s iteration!" % (curr_time(), attempt,
                                                        iteration)
        attempt += 1
        try:                            # {{{4}}}
            ok = sw.install(
                package=package,
                issu=True,
                no_copy=True,
                progress=myprogress)
            print '++++%s sw.install returns Install Status %s' % (curr_time(),
                                                                   ok)
            if ok is not True:
                print "++++%s sw.install returned False" % curr_time()
                print "++++%s will retry in 60s" % curr_time()
                sleep(60)
                return issu(user, password)
            else:
                print '++++%s sw.install returns Install Status %s' % \
                                                    (curr_time(), ok)
                print '++++%s ISSU succeeded!' % curr_time()
                return True
        except Exception as ex:         # {{{4}}}
            print "++++%s exception: message: %s, repr: %s, type: %s" % \
                        (curr_time(), ex.message, repr(ex), type(ex))
            if isinstance(ex, ConnectClosedError):
                dev.close()
                sleep(10)
                print "++++%s ConnectClosedError, will reconnect ..." % \
                                                            curr_time()
                dev = get_master_re(re0, user, password)
                return issu(user, password)
            elif isinstance(ex, RpcError):
                if ex.message == 'ISSU in progress':
                    print "++++%s sleeping 60s and retry..." % curr_time()
                    sleep(60)
                    return issu(user, password)
                elif ex.message == 'RE not master':
                    print "++++%s do ISSU on other re then ..." % curr_time()
                    if host == 're0':
                        host = 're1'
                    else:
                        host = 're0'
                    dev.close()
                    sleep(10)
                    dev = get_master_re(host, user ,password)
                    return issu(user, password)
                elif ex.message == 'ISSU Aborted!' or \
                     "'Graceful Switchover' not operational'" not in ex.message:
                    print "++++%s ISSU aborted, mostly another one is onging..." \
                                                                    % curr_time()
                    print "retry after 10s..."
                    sleep(10)
                    return issu(user, password)
                else:                   # {{{6}}}
                    print "++++%s unprocessed exception, exit..." % curr_time()
                    sys.exit()
            else:                       # {{{5}}}
                print "++++%s unprocessed exception, exit..." % curr_time()
                print "++++%s exception: message: %s, repr: %s, type: %s" \
                    % (curr_time(), ex.message, repr(ex), type(ex))
                sys.exit()
    else:
        print "++++%s no success after %s attempt, exit issu..." % (curr_time(),
                                                                    attempt_max)
def test_issu(user, password):              # {{{2}}}
    name = multiprocessing.current_process().name
    print '++++%s Run task %s, PID(%s)...' % (curr_time(), name, os.getpid())
    start = time()
    global iteration_max, dev
    while iteration < iteration_max:
        iteration += 1
        print "++++%s #%s ISSU iteration!" % (curr_time(), iteration)
        issu(user, password)
    print "++++%s %s iterations of ISSU done, exit!" % (curr_time(), iteration_max)
    end = time()
    print '++++%s Task %s runs %0.2f seconds.' % (curr_time(), name, (end - start))
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
        mylogger.debug(e)
        print "file write ERROR", fname
def git_submit():                       # {{{1}}}
    global log_dir
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
def get_master_re(host, user, password):         # {{{1}}}
    global re0, re1, dev, normalize
    try:                            # {{{2}}}
        dev = Device(host=host, user=user, password=password, normalize=normalize)
        mylogger.info("connecting to %s ..." % host)
        dev.open()
        return dev
    except ConnectTimeoutError:     # {{{2}}}
        sleep(10)
        print "ConnectTimeOutError, will reconnect afer 10s..."
        return get_master_re(host, user='labroot', password='lab123')
    except ConnectClosedError:      # {{{2}}}
        sleep(10)
        print "ConnectClosedError, will reconnect afer 10s..."
        dev = get_master_re(re0, user, password)
    except ConnectNotMasterError:   # {{{2}}}
        print "ConnectNotMasterError, connect to the other RE..."
        if host == re0:
            print " (since current RE0 is not master, go RE1...)"
            return get_master_re(host=re1, user='labroot',password='lab123')
        else:
            print " (since current RE1 is not master, go RE0...)"
            return get_master_re(host=re0, user='labroot', password='lab123')
def save_cli_thread(host, cli, fname=None):                 # {{{1}}}
    '''
    one thread: send one cli only and write the output
    '''
    global dev, normalize, log_dir
    name = threading.currentThread().getName()
    print '--->%s Run thread "%s"' % (curr_time(), name)
    start = time()
    cli_output = dev.cli(cli, warning=False)
    write_file(fname, cli_output)
    end = time()
    print '<---%s thread %s runs %0.2f sec.' % (curr_time(), name, (end - start))
def save_cli_process_mthread(host, cli_list, fname=None):                 # {{{1}}}
    '''
    one process, to login one router
    then multi-threading, each for a cli
    '''
    global dev, normalize
    name = multiprocessing.current_process().name
    print '===>%s Run Process %s, PID(%s)...' % (curr_time(), name, os.getpid())
    start = time()
    normalize = False
    dev = get_master_re(host, user, password)
    normalize = True
    if fname is None:
        fname = "%s_%s" % (dev.hostname, curr_time())
        fname = dev.hostname
        fname_full = log_dir + '/' + fname
    else:
        fname_full = fname
    if os.path.isfile(fname_full):
        os.remove(fname_full)
    threads = []
    for cli in cli_list:
        t = threading.Thread(
                name=cli,
                target=save_cli_thread,
                args=(host, cli, fname_full)
        )
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    cli_output = dev.cli(cli, warning=False)
    write_file(fname, cli_output)
    end = time()
    print '<===%s Process %s runs %0.2f sec.' % (curr_time(), name, (end - start))
def save_cli_mprocess_mthread(host_list, cli_list, fname=None):              # {{{1}}}
    jobs = []
    for router in host_list:
        logging.debug("get a router: %s" % router)
        process_name = "%s" % router
        p = multiprocessing.Process(name=process_name,
                                    target=save_cli_process_mthread,
                                    args=(router, cli_list, fname))
        p.daemon = True
        jobs.append(p)
    for p in jobs:
        p.start()
    for p in jobs:
        p.join()
def main():                     # {{{1}}}
    global re0, user, password, dev, normalize
    if 0:   # apply_async (not working) {{{2}}}
        dev = get_master_re(host, user, password)
        p = Pool()
        print ">>>%s one process to test_issu ..." % curr_time()
        test_issu_result = p.apply_async(test_issu, args=(user, password,))
        test_issu_result.get()
        print ">>>%s one process to show command ..." % curr_time()
        show_chassis_fpc_result = p.apply_async(show_chassis_fpc,
                                                args=(user, password,))
        show_chassis_fpc_result.get()
        p.apply_async(long_time_task, args=(1,))
        print '>>>%s Waiting for all subprocesses done...' % curr_time()
        p.close()
        p.join()
    if 0:   # Process {{{2}}}
        jobs = []
        normalize = False
        dev = get_master_re(masterre, user, password)
        dev.open()
        print ">>>%s one process to show command ..." % curr_time()
        p = multiprocessing.Process(name='test_show_chassis_fpc',
                                    target=test_show_chassis_fpc, args=())
        p.daemon = True
        jobs.append(p)
        print ">>>%s one process to collect rsi..." % curr_time()
        p = multiprocessing.Process(name='rsi', target=rsi, args=())
        p.daemon = True
        jobs.append(p)
        for p in jobs:
            p.start()
        for p in jobs:
            p.join()
    if 1:   # scanning routers: mp+mt{{{2}}}
        host_list = []
        cli_list  = []
        try:
            with open(router_file, 'r') as f:
                for line in f:
                    if not line.strip() == '':
                        host_list.append(line.strip())
        except Exception:
            print "file open ERROR", router_file
        try:
            with open(cli_file, 'r') as f:
                for line in f:
                    if not line.strip() == '':
                        cli_list.append(line.strip())
        except Exception:
            print "file open ERROR", cli_file
        mylogger.debug("host_list read %s" % host_list)
        mylogger.debug("cli_list read %s" % cli_list)
        fyaml = file('pypuller.yaml', 'r')
        pyaml = yaml.load_all(fyaml)
        pyaml_list = list(pyaml)
        mylogger.debug("the yaml data looks:")
        for pyaml1 in pyaml_list:
            mylogger.debug(pprint.pformat(pyaml1))
        host_list = pyaml_list[1]['hosts']
        cli_list  = pyaml_list[1]['clies']
        mylogger.debug("hosts: %s" % '. '.join(map(str, host_list)))
        mylogger.debug("clis: %s"    % ', '.join(map(str, cli_list)))
        sys.exit()
        save_cli_mprocess_mthread(host_list, cli_list)
        if commit:
            git_submit()
    if 0:   # simple test {{{2}}}
        import ipdb; ipdb.set_trace()  # XXX BREAKPOINT
        normalize = False
        dev = get_master_re(masterre, user, password)
        router_conf_file = "%s_%s" % (dev.hostname, curr_time())
        router_conf_file = dev.hostname
        rpc_get_config = dev.rpc.get_config()
        rpc_get_interface_info = dev.rpc.get_interface_information(
                                                    {'format': 'text'},
                                                    interface_name='lo0',
                                                    terse=True)
        rpc_get_interface_info = etree.tostring(rpc_get_interface_info)
        mylogger.debug("now write result to %s" % router_conf_file)
        write_file(router_conf_file, rpc_get_interface_info)
    if 0:   # mt test {{{2}}}
        cli_list = ["show version", "show interface lo0 terse", "show system uptime"]
        save_cli_mthread(masterre, cli_list)
if __name__ == '__main__':          # {{{1}}}
    name = multiprocessing.current_process().name
    print '====%s Parent process %s, PID(%s)...' % (curr_time(), name, os.getpid())
    start = time()
    main()
    end = time()
    print '====%s Task %s runs %0.2f seconds.' % (curr_time(), name, (end - start))

