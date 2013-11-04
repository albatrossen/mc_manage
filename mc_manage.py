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
import curses
from curses.wrapper import wrapper
import curses.ascii
import time
import asyncore
import signal
        

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
    def start_foreground(self):
        if self._status():
            print 'Server already started'
            return
        print 'Starting Server'
        with open(pidfile,'w+') as f:
            f.write(str(os.getpid())+"\n")
        atexit.register(os.unlink,pidfile)
        server = retach.RetachServer(socketfile=socketfile, command=invocation)
        server.wait()
    def stop(self, warning=stop_message):
        if not self._status():
            print 'Server already stopped'
            return
        print 'Sending warning'
        self.say(warning)
        time.sleep(stop_warntime)
        self.stop_now()
    def stop_now(self):
        if not self._status():
            print 'Server already stopped'
            return
        print 'Stopping server'
        self.client.ping('save-all\n',pong=re.escape('[Server thread/INFO]: Saved the world'))
        #self.client.ping('stop\n')
        if not self.client.wait_for_disconnect(timeout=stop_timeout):
            print("Server did not stop within the expected time")
            self.force_stop()
    def force_stop(self):
        self.client
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
            self.client.ping('list\n',pong='\[Server thread/INFO\]: There are (\d+)/\d+ players online')
            if self.client.match:
                print("PLAYERS: %s" % self.client.match.group(1))
            else:
                print("PLAYERS: Unknown")
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
    def console(self):
        ui = UI(self.client)
        ui.run()

import traceback

class UI(asyncore.file_dispatcher):
    index = 0
    ibuffer = []
    buffer_size = 300
    _exc = None
    def run_python(self,char):
        if self.ibuffer:
            try:
                self.lines.append(repr(eval(''.join(self.ibuffer))))
            except:
                self.lines.append(str(sys.exc_info()[1]))
            self.redraw()
    def run_cmd(self,char):
        if self.ibuffer:
            self.client.push(''.join(self.ibuffer)+'\n')
        del self.ibuffer[:]
        self.index = 0
    def on_line(self,line):
        self.lines.append(line)
        del self.lines[:-self.buffer_size]
        self.redraw()
    def exit(self,char):
        self.close()
    def __init__(self, client):
        self.lines = []
        self.client = client
        client.linehandler = self.on_line
        client.push(retach.KEY_SENDBUFFER)
        asyncore.file_dispatcher.__init__(self, sys.stdin)
    def writable(self):
        return False
    def handle_read(self):
        try:
            data = self.stdscr.getch()
            if data in self.map:
                self.map[data](self,data)
            elif curses.ascii.isprint(data):
                self.ibuffer.insert(self.index,chr(data))
                self.index += 1
            self.redraw()
        except:
            self._exc = sys.exc_info()
            print("error")
    def redraw(self):
            self.stdscr.erase()
            max_y,max_x = self.stdscr.getmaxyx()
            for y,line in enumerate(self.lines[-(max_y-2):]):
                self.stdscr.addstr(y,0,line[:max_x])
            self.stdscr.addstr(max_y-2,0,"="*max_x)
            self.stdscr.addstr(max_y-1,0,''.join(self.ibuffer))
            self.stdscr.move(max_y-1,self.index)
            self.stdscr.refresh()
    def handle_close(self):
        self.close()
    def _run(self,stdscr):
        self.stdscr = stdscr
        self.stdscr.nodelay(True)
        self.handle_read()
        while True:
            try:
                asyncore.loop()
            except IOError:
                self.stdscr.redrawwin()
                self.redraw()
            except KeyboardInterrupt:
                self.close()
                break
    def run(self):
        curses.wrapper(self._run)
        if self._exc:
            traceback.print_exception(*self._exc)
    def left(self, char):
        self.index = max(0,self.index - 1)
        self.stdscr.addstr(2,2,'left')
    def right(self, char):
        self.index = min(len(self.ibuffer),self.index + 1)
        self.stdscr.addstr(2,2,'right')
    def backspace(self, char):
        if self.index >= 1:
            self.index -= 1
            del self.ibuffer[self.index]
    map = {
        ord('\n'):run_cmd,
        curses.KEY_LEFT:left,
        curses.KEY_RIGHT:right,
        curses.KEY_BACKSPACE:backspace,
        curses.ascii.ctrl(ord('p')):run_python,
    }

if __name__ == '__main__':
    def unknown(*args):
        print('Unknown command: %s' % sys.argv[1])
    if len(sys.argv) >= 2:
        func=getattr(McManage(),sys.argv[1],unknown)
        func(*sys.argv[2:])
    else:
        print('Too few arguments')
