from jnpr.junos import Device

def dummy1():
    global dev
    dev = Device(host='172.19.161.129', user='labroot', passwd='lab123')
    dev.open()
    print "print facts from dummy1:"
    print dev.facts
    return dev

def dummy2():
    global dev
    # dev.open()
    print "print facts from dummy2:"
    print dev.facts

    if 0:
        global abc
        abc = 1
    if 1:
        global abc
        abc = 0

import ipdb; ipdb.set_trace()  # XXX BREAKPOINT
dummy1()
dummy2()
print "print facts from global:"
print dev.facts
