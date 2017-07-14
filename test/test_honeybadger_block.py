import unittest
import gevent
import random
from gevent.event import Event
from gevent.queue import Queue
from honeybadgerbft.core.commoncoin import shared_coin
from honeybadgerbft.core.binaryagreement import binaryagreement
from honeybadgerbft.core.reliablebroadcast import reliablebroadcast
from honeybadgerbft.core.commonsubset import commonsubset
import honeybadgerbft.core.honeybadger_block
reload(honeybadgerbft.core.honeybadger_block)
from honeybadgerbft.core.honeybadger_block import honeybadger_block
from honeybadgerbft.crypto.threshsig.boldyreva import dealer
from honeybadgerbft.crypto.threshenc import tpke
from collections import defaultdict

def simple_router(N, maxdelay=0.005, seed=None):
    """Builds a set of connected channels, with random delay
    @return (receives, sends)
    """
    rnd = random.Random(seed)
    #if seed is not None: print 'ROUTER SEED: %f' % (seed,)
    
    queues = [Queue() for _ in range(N)]
    _threads = []

    def makeSend(i):
        def _send(j, o):
            delay = rnd.random() * maxdelay
            #delay = 0.1
            #print 'SEND   %8s [%2d -> %2d] %2.1f' % (o[0], i, j, delay*1000), o[1:]
            gevent.spawn_later(delay, queues[j].put_nowait, (i,o))
        return _send

    def makeRecv(j):
        def _recv():
            (i,o) = queues[j].get()
            #print 'RECV %8s [%2d -> %2d]' % (o[0], i, j)
            return (i,o)
        return _recv
        
    return ([makeSend(i) for i in range(N)],
            [makeRecv(j) for j in range(N)])



### Make the threshold signature common coins
def _make_honeybadger(sid, pid, N, f, sPK, sSK, ePK, eSK, input, send, recv):

    def broadcast(o):
        for j in range(N): send(j, o)
    
    coin_recvs = [None] * N
    aba_recvs  = [None] * N
    rbc_recvs  = [None] * N

    aba_inputs  = [Queue(1) for _ in range(N)]
    aba_outputs = [Queue(1) for _ in range(N)]
    rbc_outputs = [Queue(1) for _ in range(N)]

    my_rbc_input = Queue(1)

    def _setup(j):
        def coin_bcast(o):
            broadcast(('ACS_COIN', j, o))

        coin_recvs[j] = Queue()
        coin = shared_coin(sid + 'COIN' + str(j), pid, N, f, sPK, sSK,
                           coin_bcast, coin_recvs[j].get)

        def aba_bcast(o):
            broadcast(('ACS_ABA', j, o))

        aba_recvs[j] = Queue()
        aba = gevent.spawn(binaryagreement, sid+'ABA'+str(j), pid, N, f, coin,
                           aba_inputs[j].get, aba_outputs[j].put_nowait,
                           aba_bcast, aba_recvs[j].get)

        def rbc_send(k, o):
            send(k, ('ACS_RBC', j, o))

        # Only leader gets input
        rbc_input = my_rbc_input.get if j == pid else None
        rbc_recvs[j] = Queue()
        rbc = gevent.spawn(reliablebroadcast, sid+'RBC'+str(j), pid, N, f, j,
                           rbc_input, rbc_recvs[j].get, rbc_send)
        rbc_outputs[j] = rbc.get  # block for output from rbc

    # N instances of ABA, RBC
    for j in range(N): _setup(j)

    # One instance of TPKE
    def tpke_bcast(o):
        broadcast(('TPKE', 0, o))

    tpke_recv = Queue()

    # One instance of ACS
    acs = gevent.spawn(commonsubset, pid, N, f, rbc_outputs,
                       [_.put_nowait for _ in aba_inputs],
                       [_.get for _ in aba_outputs])

    def _recv():
        while True:
            (sender, (tag, j, msg)) = recv()
            if   tag == 'ACS_COIN': coin_recvs[j].put_nowait((sender,msg))
            elif tag == 'ACS_RBC' : rbc_recvs [j].put_nowait((sender,msg))
            elif tag == 'ACS_ABA' : aba_recvs [j].put_nowait((sender,msg))
            elif tag == 'TPKE'    : tpke_recv.put_nowait((sender,msg))
            else:
                print 'Unknown tag!!', tag
                raise
    gevent.spawn(_recv)

    return honeybadger_block(pid, N, f, ePK, eSK, input,
                             acs_in=my_rbc_input.put_nowait, acs_out=acs.get,
                             tpke_bcast=tpke_bcast, tpke_recv=tpke_recv.get)


### Test asynchronous common subset
def _test_honeybadger(N=4, f=1, seed=None):
    # Generate threshold sig keys
    sid = 'sidA'
    sPK, sSKs = dealer(N, f+1, seed=seed)
    ePK, eSKs = tpke.dealer(N, f+1)
    
    rnd = random.Random(seed)
    #print 'SEED:', seed
    router_seed = rnd.random()
    sends, recvs = simple_router(N, seed=router_seed)

    inputs  = [None] * N
    threads = [None] * N
    for i in range(N):
        inputs[i] = Queue(1)
        threads[i] = gevent.spawn(_make_honeybadger, sid, i, N, f,
                                  sPK, sSKs[i],
                                  ePK, eSKs[i],
                                  inputs[i].get, sends[i], recvs[i])

    for i in range(N):
        #if i == 1: continue
        inputs[i].put('<[HBBFT Input %d]>' % i)

    #gevent.killall(threads[N-f:])
    #gevent.sleep(3)
    #for i in range(N-f, N):
    #    inputs[i].put(0)
    try:
        outs = [threads[i].get() for i in range(N)]

        # Consistency check
        assert len(set(outs)) == 1
        
    except KeyboardInterrupt:
        gevent.killall(threads)
        raise

from nose2.tools import params

def test_honeybadger():
    _test_honeybadger()

