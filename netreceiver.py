import os
import sys
import asyncio

try:
    from MeteorClient import MeteorClient
except ImportError:
    MeteorClient = None

targetdir = sys.argv[1]

if len(sys.argv) == 3:
    if MeteorClient:
        cedarurl = sys.argv[2]
    else:
        print('python-meteor module not installed, cannot add files to a Cedar server')
        cedarurl = None
else:
    cedarurl = None

class NetReceiver(asyncio.Protocol):
    def connection_made(self, transport):
        peername = transport.get_extra_info('peername')
        print('Connection from {}'.format(peername))
        self.transport = transport
        
        self.file = None
        self.cedar = None

    def data_received(self, data):
        if not self.file:
            self.filename = data.decode()
            self.file = open(os.path.join(targetdir, self.filename), 'wb')
            print('Opened file with filename {}'.format(self.filename))
        else:
            self.file.write(data)

    def connection_lost(self, exc):
        if exc: print('Exception', exc)
        if self.file:
            self.file.close()
            print('Finished receiving file {}'.format(self.filename))

            if cedarurl: asyncio.get_event_loop().create_task(self.reencap_and_add())
    
    async def reencap_and_add(self):
        # This is the kind of thing that happens when a deadline gets moved up two months.
        # I'd like to say I'll burn it all down and fix it, but if it works OK then I'll probably forget about it until I need to fix something.
        # Sorry, future me.
        # Anyway, this whole mess will hopefully eventually get replaced by Cedar proper.
        
        dest = self.filename.replace('mkv', 'mp4')
        print('Reencapsulating {} because reasons.'.format(self.filename))
        proc = await asyncio.create_subprocess_exec(
            '/usr/bin/ffmpeg', '-i', os.path.join(targetdir, self.filename),
            '-c:v', 'copy', '-c:a', 'copy', os.path.join(targetdir, dest)
        )
        await proc.wait()
        
        os.unlink(os.path.join(targetdir, self.filename))
        
        self.filename = dest
        
        print('Attempting to connect to Cedar server', cedarurl)
        self.cedar = MeteorClient('ws://{}/websocket'.format(cedarurl))
        self.cedar.on('connected', self.cedar_connected)
        self.cedar.on('failed', self.cedar_connect_failed)
        self.cedar.connect()
    
    def cedar_connected(self):
        print('Direct-adding file to Cedar server: ', self.filename)
        self.cedar.call('mediaDirectAdd', [self.filename])
    
    def cedar_connect_failed(self):
        print('Failed to connecte to Cedar server at ', cedarurl)
            
loop = asyncio.get_event_loop()
# Each client connection will create a new protocol instance
coro = loop.create_server(NetReceiver, '0.0.0.0', 8123)
server = loop.run_until_complete(coro)

# Serve requests until Ctrl+C is pressed
print('Serving on {}'.format(server.sockets[0].getsockname()))
try:
    loop.run_forever()
except KeyboardInterrupt:
    pass

# Close the server
server.close()
loop.run_until_complete(server.wait_closed())
loop.close()
