__author__ = 'aluex'

from gevent.queue import Queue
from gevent import Greenlet
from utils import bcolors, mylog
from includeTransaction import honestParty, Transaction
from collections import defaultdict
from bkr_acs import initBeforeBinaryConsensus
from utils import ACSException
import gevent
import os
#import random
from utils import myRandom as random
import fcp
import json
import pickle
#print state

nameList = ["Alice", "Bob", "Christina", "David", "Eco", "Francis", "Gerald", "Harris", "Ive", "Jessica"]

def exception(msg):
    mylog(bcolors.WARNING + "Exception: %s\n" % msg + bcolors.ENDC)
    os.exit(1)

def randomTransaction():
    tx = Transaction()
    tx.source = random.choice(nameList)
    tx.target = random.choice(nameList)
    tx.amount = random.randint(1, 100)
    return tx

def randomTransactionStr():
    return repr(randomTransaction())

publicKeys = []
USKPublicKeys = []
nodeList = []

def generateFreenetKeys(N):
    global publicKeys, nodeList
    mylog("Initiating ...")
    privateList = []
    USKPrivateList = []
    for i in range(N):
        mylog("Registering node %d" % i)
        n = fcp.node.FCPNode()
        public, private = n.genkey()
        USKPublic, USKPrivate = n.genkey(name='badger', usk=True)
        mylog("Got public key %s, private key %s, USKPublic key %s, USKPrivate key %s" % (
            public, private, USKPublic, USKPrivate))
        mylog("Initializing msg_count for node %d" % i)
        # Set the initial counter
        n.put(uri=USKPrivate, data="0",
            mimetype="application/octet-stream", realtime=True, priority=0)
        # Update the lists
        publicKeys.append(public)
        USKPublicKeys.append(USKPublic)
        privateList.append(private)
        USKPrivateList.append(USKPrivate)
        nodeList.append(n)
    return privateList, USKPrivateList

def shutdownNodes(nodeList):
    for node in nodeList:
        node.shutdown()

def encode(m):
    return pickle.dumps(m)

def decode(s):
    return pickle.loads(s)

def client_test_freenet(N, t):
    '''
    Test for the client with random delay channels

    command list
        i [target]: send a transaction to include for some particular party
        h [target]: stop some particular party
        m [target]: manually make particular party send some message
        help: show the help screen

    :param N: the number of parties
    :param t: the number of malicious parties
    :return None:
    '''
    maxdelay = 0.01

    privateList, USKPrivateList = generateFreenetKeys(N)

    #buffers = map(lambda _: Queue(1), range(N))

    # Instantiate the "broadcast" instruction
    def makeBroadcast(i):
        counter = [0] * N
        def _broadcast(v):
            # deliever
            counter[i] += 1
            mylog("[%d] writing msg %s..." % (i, encode(v)))
            nodeList[i].put(uri=privateList[i]+str(counter[i]), data=encode(v),
                            mimetype="application/octet-stream", realtime=True, priority=0)
            mylog("[%d] Updating msg_counter to %d..." % (i, counter[i]))
            nodeList[i].put(uri=USKPrivateList[i], #.replace('/0', '/'+str(counter[i])),
                            data=str(counter[i]),
                            mimetype="application/octet-stream", realtime=True, priority=0)
            # mylog(bcolors.OKGREEN + "     [%d] -> [%d]: Finish" % (i, j) + bcolors.ENDC)
        return _broadcast

    def makeListen(i):
        recvChannel = Queue()
        recvCounter = [0] * N
        def listener(j, recvCounter):
            while True:
                mylog("[%d] Updating msg_counter of %d..." % (i, j))
                uskjob = nodeList[i].get(uri=USKPublicKeys[j], async=True, realtime=True, priority=0)
                # The reason I use async here is that from the tutorial it is said this would be faster
                mime, data, meta = uskjob.wait()
                newestNum = int(data)
                mylog("[%d] found msg_counter of %d is %d..." % (i, j, newestNum))
                if newestNum > recvCounter[j]:
                    for c in range(recvCounter[j], newestNum):
                        job = nodeList[i].get(uri=publicKeys[j]+str(c+1),
                                              async=True, realtime=True, priority=0)
                        mime, data, meta = job.wait()
                        recvCounter += 1
                        recvChannel.put((j, decode(data)))
                    recvCounter[j] = newestNum
        for k in range(N):
            Greenlet(listener, k, recvCounter).start()
        def _recv():
            recvChannel.get()
        return _recv

    while True:
        initBeforeBinaryConsensus()
        ts = []
        controlChannels = [Queue() for _ in range(N)]
        for i in range(N):
            bc = makeBroadcast(i)
            recv = makeListen(i)
            th = Greenlet(honestParty, i, N, t, controlChannels[i], bc, recv)
            #controlChannels[i].put(('IncludeTransaction', randomTransaction()))
            controlChannels[i].put(('IncludeTransaction', randomTransactionStr()))
            th.start_later(random.random() * maxdelay)
            ts.append(th)

        #Greenlet(monitorUserInput).start()
        try:
            gevent.joinall(ts)
        except ACSException:
            gevent.killall(ts)
        except gevent.hub.LoopExit: # Manual fix for early stop
            print "Concensus Finished"
            mylog(bcolors.OKGREEN + ">>>" + bcolors.ENDC)

    shutdownNodes()

if __name__ == '__main__':
    client_test_freenet(5, 1)