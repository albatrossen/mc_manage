#!/usr/bin/python
import ConfigParser
import retach
import os, sys
import daemon
import lockfile
import re
import textwrap
import time
import subprocess
import atexit

base_directory = os.path.dirname(sys.argv[0])

if base_directory:
    os.chdir(base_directory)

config = ConfigParser.RawConfigParser()
config.read('mc_manage.ini')

invocation = config.get('mcconfig','invocation').strip().split()
socketfile = config.get('mcconfig','socketfile')
pidfile = config.get('mcconfig','pidfile')
stop_message = config.get('mcconfig','stop_message')
presave_message = config.get('mcconfig','presave_message')
postsave_message = config.get('mcconfig','postsave_message')
stop_warntime = config.getint('mcconfig','stop_warntime')
stop_timeout = config.getint('mcconfig','stop_timeout')
max_say_line_width = config.getint('mcconfig','max_say_line_width')


def fold(msg):
    wrapper = textwrap.TextWrapper(width=max_say_line_width)
    for line in msg.split('\n'):
        for part in wrapper.wrap(line):
            yield part

class McManage(object):
    def start(self):
        if self._status():
            print 'Server already started'
            return
        print 'Starting Server'
        with daemon.DaemonContext(
                                  stdin=sys.stdin, 
                                  stdout=sys.stdout, 
                                  stderr=sys.stderr, 
                                  working_directory='.',
                                  pidfile=lockfile.FileLock(pidfile)
                                  ):
            with open(pidfile,'w+') as f:
                f.write(str(os.getpid())+"\n")
            atexit.register(os.unlink,pidfile)
            server = retach.RetachServer(socketfile=socketfile, command=invocation)
            server.wait()
    def stop(self):
        if not self._status():
            print 'Server already stopped'
            return
        print 'Sending warning'
        self.say(stop_message)
        time.sleep(stop_warntime)
        self.stop_now()
    def stop_now(self):
        if not self._status():
            print 'Server already stopped'
            return
        print 'Stopping server'
        self.client.ping('save-all\n',pong=re.escape('[INFO] CONSOLE: Save complete.'))
        self.client.ping('stop\n', return_on_send = False)        
    def restart(self):
        self.stop()
        self.start()
    def save(self):
        if not self._status():
            print 'Server not started'
            return
        self.say(presave_message)
        self.client.ping('save-off\n',pong=re.escape('[INFO] CONSOLE: Disabled level saving..'))
        self.client.ping('save-all\n',pong=re.escape('[INFO] CONSOLE: Save complete.'))
        #rsync?
        self.client.ping('save-on\n',pong=re.escape('[INFO] CONSOLE: Enabled level saving..'))
        self.say(postsave_message)
    def _status(self):
        
        try:
            with open(pidfile) as f:
                pid = int(f.read())
        except IOError:
            return
        try:
            return subprocess.check_output(['ps','--ppid', str(pid),'--no-headers','-o','%cpu,%mem']).split()
        except subprocess.CalledProcessError:
            return
    def status(self):
        result = self._status()
        if result:
            cpu, mem = result
            print("Status: Running...")
            print("CPU: %s" % cpu)
            print("RAM: %s" % mem)
#            self.client.ping('list\n',pong='\[INFO\] There are (\d+)/\d+ players online')
#            print("PLAYERS: %s" % self.client.match.group(1))
        else:
            print("Status: Stopped.")
    def command(self,*cmd):
        if not self._status():
            print 'Server not started'
            return
        self.client.ping("%s\n" % str.join(' ',cmd))
    def say(self, *msg):
        if not self._status():
            print 'Server not started'
            return
        lines = [' '.join(msg)] if msg else sys.stdin
        for line in lines:
#            for part in fold(line):
            self.client.ping("say %s\n" % line)
    @property
    def client(self):
        try:
            return self._client
        except AttributeError:
            self._client = retach.RetachClient(socketfile)
        return self._client
            

if __name__ == '__main__':
    def unknown(*args):
        print('Unknown command: %s' % sys.argv[1])
    if len(sys.argv) >= 2:
        func=getattr(McManage(),sys.argv[1],unknown)
        func(*sys.argv[2:])
    else:
        print('Too few arguments')
