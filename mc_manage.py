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

def reverse_wrapped_lines(lines,width):
    for line in reversed(lines):
        for i in range(len(line)/width,-1,-1):
            yield line[i*width:(i+1)*width]

def split_line(line,width):
    for i in range(len(line)/width,-1,-1):
        yield line[i*width:(i+1)*width]

import traceback

class UI(asyncore.file_dispatcher):
    index = 0
    ibuffer = []
    buffer_size = 300
    _exc = None
    display_offset_y = None
    display_offset_x = 0
    def run_python(self,char):
        if self.ibuffer:
            try:
                self.on_line(repr(eval(''.join(self.ibuffer))))
            except:
                self.on_line(str(sys.exc_info()[1]))
            self.redraw()
    def handle_winch(self,a,b):
        curses.endwin()
	self.redraw()
    def run_cmd(self,char):
        if self.ibuffer:
            self.client.push(''.join(self.ibuffer)+'\n')
        del self.ibuffer[:]
        self.index = 0
    def on_line(self,line):
        self.lines.append(line)
        if self.display_offset_y is None:
            del self.lines[:-self.buffer_size]
        else:
            self.add_offset(-1)
        self.redraw()
    def exit(self,char):
        self.close()
    def __init__(self, client):
        self.lines = []
        self.client = client
        client.linehandler = self.on_line
        client.push(retach.COMMAND_SENDBUFFER)
        asyncore.file_dispatcher.__init__(self, sys.stdin)
        self.map = {
            ord('\n'):self.run_cmd,
            curses.KEY_LEFT:self.left,
            curses.KEY_RIGHT:self.right,
            curses.KEY_UP:lambda c:self.add_offset(-1),
            curses.KEY_DOWN:lambda c:self.add_offset(1),
            curses.KEY_BACKSPACE:self.backspace,
            curses.ascii.ctrl(ord('p')):self.run_python,
            curses.ascii.ctrl(ord('j')):lambda c:self.add_offset_x(-1),
            curses.ascii.ctrl(ord('l')):lambda c:self.add_offset_x(1),
        }
        signal.signal(signal.SIGWINCH,self.handle_winch)
    def add_offset_x(self,x):
        self.display_offset_x = max(0,self.display_offset_x+x)
    def add_offset(self,x):
        self.display_offset_y = self.display_offset_y + x if self.display_offset_y is not None else x
        if self.display_offset_y >= 0:
            self.display_offset_y = None
    def writable(self):
        return False
    def handle_read(self):
        try:
            data = self.stdscr.getch()
            if data in self.map:
                self.map[data](data)
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
            for i,line in enumerate(reversed(self.lines[:self.display_offset_y])):
                y = max_y - i - 3
                if y < 0:
                    break
                self.stdscr.addstr(y,0,line[self.display_offset_x:self.display_offset_x+max_x])
            if self.display_offset_y is None:
                self.stdscr.addstr(max_y-2,0,"="*max_x)
            else:
                self.stdscr.addstr(max_y-2,0,"v"*max_x)
            self.stdscr.addstr(max_y-1,0,''.join(self.ibuffer))
            self.stdscr.move(max_y-1,self.index)
            self.stdscr.refresh()
    def handle_close(self):
        self.close()
    def _run(self,stdscr):
        self.stdscr = stdscr
        self.stdscr.nodelay(True)
        self.handle_read()
        self.max_y, self.max_x = self.stdscr.getmaxyx()
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

if __name__ == '__main__':
    def unknown(*args):
        print('Unknown command: %s' % sys.argv[1])
    if len(sys.argv) >= 2:
        func=getattr(McManage(),sys.argv[1],unknown)
        func(*sys.argv[2:])
    else:
        print('Too few arguments')
