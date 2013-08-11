import os, sys, re

import socket
import pty
import asyncore, asynchat
import subprocess
import signal
import atexit
import logging
import logging

log = logging.getLogger()

#--delayrun
#--daemon
#retach socketname cmd line args

class ChildExit(Exception):
    pass

def handler(signum, frame):
    raise ChildExit('Closed')

class RetachForwarder(asyncore.dispatcher_with_send):
    def __init__(self, sock, runner):
        asyncore.dispatcher_with_send.__init__(self, sock)
        self.runner = runner
        self.runner.connect_listener(self.send)
    def handle_read(self):
        data = self.recv(256)
        self.runner.buffer += data
    def handle_close(self):
        self.runner.disconnect_listener(self.send)
        self.close()

class RetachServer(asyncore.dispatcher):
    def __init__(self, socketfile, command):
        asyncore.dispatcher.__init__(self)
        self.create_socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind(socketfile)
        atexit.register(os.unlink,socketfile)
        self.listen(5)
        self.runner = Runner(command)
    def handle_accept(self):
        pair = self.accept()
        if pair is not None:
            sock, addr = pair
            handler = RetachForwarder(sock, self.runner)
    def wait(self):
        signal.signal(signal.SIGCHLD, handler)
        try:
            asyncore.loop()
        except KeyboardInterrupt:
            log.info('Interupt received forcing stop')
            s.runner.process.kill()
        except ChildExit:
            pass

class Runner(asyncore.file_dispatcher):
    def __init__(self, command):
        self.listeners = set()
        self.buffer = ""
        self.connectbuffer = ""
        self.connectbuffer_size = 0
        oldaction = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        self.master, self.slave = pty.openpty()
        log.debug("Starting process")
        self.process = subprocess.Popen(command,
                     close_fds=True,
                     stdin=self.slave,
                     stdout=self.slave,
                     stderr=self.slave,
                     )
        signal.signal(signal.SIGTTOU, oldaction)
        asyncore.file_dispatcher.__init__(self, self.master)
    def writable(self):
        return len(self.buffer) > 0
    def handle_write(self):
        sent = self.send(self.buffer)
        self.buffer = self.buffer[sent:]
    def connect_listener(self,listener):
        log.debug("Client Connected")
        self.listeners.add(listener)
        if self.connectbuffer:
            listener(self.connectbuffer)
    def disconnect_listener(self,listener):
        log.debug("Client Disconnected")
        self.listeners.discard(listener)
    def handle_read(self):
        data = self.recv(256)
        if self.connectbuffer_size:
            self.connectbuffer += data
            self.connectbuffer = self.connectbuffer[-self.connectbuffer_size:]
        for func in list(self.listeners):
            func(data)

class RetachClient(asynchat.async_chat):
    def __init__(self, filename, terminator='\n'):
        asynchat.async_chat.__init__(self)
        self.create_socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connect(filename)
        self.ibuffer = []
        self.set_terminator(terminator)
    def more(self):
        self.match = True
        return ''
    def handle_close(self):
        self.match = True
        self.close()
    def collect_incoming_data(self, data):
        if self.matcher:
            self.ibuffer.append(data)
    def found_terminator(self):
        if self.matcher and not self.match:
            line = str.join("",self.ibuffer)
            self.match = self.matcher.search(line)
            del self.ibuffer[:]
    def ping(self, data, pong = None, return_on_send = True):
        self.match = None
        self.push(data)
        if not pong and return_on_send:
            self.push_with_producer(self)
        self.matcher = re.compile(pong,re.MULTILINE) if pong else None
        while not self.match:
            asyncore.loop(count=1)

#class CmdLine(asyncore.file_dispatcher):
#    def __init__(self,client):
#        asyncore.file_dispatcher.__init__(self, sys.stdin)
#        self.client = client
#    def writable(self):
#        return False
#    def handle_read(self):
#        data = self.recv(256)
#        self.client.send(data)
#    def handle_close(self):
#        self.client.close()
#        self.close()

def run_server(options):
    logging.basicConfig(level=logging.DEBUG)
    log.info('Server Started')
    signal.signal(signal.SIGCHLD, handler)
    s = RetachServer('test.sck')
    try:
        asyncore.loop()
    except KeyboardInterrupt:
        log.info('Interupt received forcing stop')
        s.runner.process.kill()
    except ChildExit:
        pass
    log.info('Server Stopped')

def main():
    return run_server(options)
    
if __name__ == '__main__':
    main()
