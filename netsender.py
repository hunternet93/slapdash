import asyncio

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
from gi.repository import Gst, GstApp

# Protocol:
# First message contains the target filename as a UTF-8 string.
#   If file exists, it will be overwritten
# Next messages are a sample to write to file.
# Connection is closed when file is finished.

async def netsender_create_connection(loop, func, location, port):
    try:
        await loop.create_connection(func, location, port)
    except Exception as e:
        print('Error connecting to "{}:{}": {}'.format(location, port, e))

class NetSender(asyncio.Protocol):
    def __init__(self, location, filename, appsink, publish, loop):
        print('netsender created')
        self.location = location
        self.filename = filename
        self.publish = publish
        self.loop = loop
        self.queue = asyncio.Queue()
        
        self.eos = False
        self.done = False

        appsink.connect('new-sample', self.appsink_sample)
        appsink.connect('eos', self.appsink_eos)

    def connection_made(self, transport):
        print('netsend connected to endpoint')
        self.publish('netsend connected to endpoint')
        
        self.transport = transport
        self.transport.set_write_buffer_limits(high = 10**9)
        self.transport.write(self.filename.encode())
        
        self.loop.create_task(self.send_things())
        self.loop.create_task(self.monitor_queue())
    
    async def send_things(self):
        while not self.eos:
            thing = await self.queue.get()
            self.transport.write(thing)
            
        self.publish('netsend done!')
        self.transport.close()
    
    async def monitor_queue(self):
        while not self.done:
            self.publish('netsend_buffer {} {}/{}'.format(
                self.transport.get_write_buffer_size() / 10**6,
                self.location, self.filename
            ))
            await asyncio.sleep(1)
    
    def appsink_sample(self, appsink):
        sample = appsink.pull_sample()
        if not self.eos:
            buf = sample.get_buffer()
            res, info = buf.map(Gst.MapFlags.READ)
            if res:
                self.queue.put_nowait(info.data)
        
        return Gst.FlowReturn.OK
        
    def appsink_eos(self, appsink):
        self.eos = True
        self.transport.close()
    
    def data_received(self, data):
        print('Netsend received: {!r}'.format(data.decode()))

    def connection_lost(self, exc):
        self.done = True
        if exc:
            print('Netsend exception', exc)
            self.publish('netsend connection lost with error {}', exc)
            self.eos = True

        elif self.eos:
            self.publish('netsend finished successfully')
            self.publish('netsend_buffer {} {}/{}'.format(
                'done', self.location, self.filename
            ))
        else:
            self.publish('netsend connection_lost before EOS!')
            self.eos = True

