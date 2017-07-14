import sys
import yaml
import schedule

from datetime import datetime

import asyncio, gbulb, websockets
gbulb.install()

try:
    from MeteorClient import MeteorClient
except ImportError:
    MeteorClient = None

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
from gi.repository import Gst, GstVideo, GLib

Gst.init(None)

if not sys.argv[1]:
    print('Usage: slapdash.py <settings_file.yaml>')
    quit()

settings = yaml.load(open(sys.argv[1]))
    
class Main:
    def __init__(self):
        self.loop = asyncio.get_event_loop()
        
        self.sockets = set()
        self.queues = set()
        
        self.pipeline = Gst.Pipeline()
        self.clock = self.pipeline.get_pipeline_clock()
        
        self.stream_state = 'stopped'
        
        self.force_keyframes = False

        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.on_message)
    
    def build_pipeline(self):
        self.elements = set()
        self.muxqs = set()
        self.stop_actions = []
        
        video_settings = settings.get('video_settings', {})
        self.force_keyframes = video_settings.get('force_keyframes', True)
        
        audio_encode_props = settings.get('audio_settings', {}).copy()

        if audio_encode_props.get('encoder'):
            audio_encoder = audio_encode_props['encoder']
            del audio_encode_props['encoder']
        else:
            audio_encoder = 'avenc_aac'
        
        if audio_encode_props.get('bitrate'):
            audio_encode_props['bitrate'] *= 1000
                
        self.malm(settings['audio_source'] + [
            'audioconvert',
            {audio_encoder: audio_encode_props},
            'aacparse',
            {'tee': {'name': 'aall'}}
        ])

        self.malm(settings['video_source'] + [
            'videoconvert',
            {'tee': {'name': 'vinput'}}
        ])
        
        for rate in settings['video_rates']:
            name = list(rate)[0]
            props = rate[name]
            
            rate_is_used = False
            for target in settings['targets']:
                print(name, name in target[list(target)[0]]['rates'])
                if name in target[list(target)[0]]['rates']:
                    rate_is_used = True
                    break
            
            if not rate_is_used: continue
            
            caps = ['video/x-raw']

            if props.get('width'):
                caps.append('width = {}'.format(props['width']))
                del props['width']

            if props.get('height'):
                caps.append('height = {}'.format(props['height']))
                del props['height']

            if props.get('framerate'):
                caps.append('framerate = {}'.format(props['framerate']))
                del props['framerate']

            caps = ', '.join(caps)

            if props.get('tune') == None:
                props['tune'] = 'zerolatency'
            elif props.get('tune') == '':
                del props['tune']

            if props.get('option-string') == None:
                props['option-string'] = 'scenecut=0'
            elif props.get('option-string') == '':
                del props['option-string']

            if props.get('speed-preset') == None:
                props['speed-preset'] = 1
            elif props.get('speed-preset') == '':
                del props['spreed-preset']
            
            self.malm([
                {'queue': {'name': 'v{}'.format(name)}},
                'videorate',
                'videoscale',
                {'capsfilter': {'caps': caps}},
                {'x264enc': props},
                {'capsfilter': {'caps': 'video/x-h264, profile=baseline'}},
                'h264parse',
                {'tee': {'name': 't{}'.format(name)}}
            ])

            self.vinput.link(getattr(self, 'v{}'.format(name)))
        
        for target in settings['targets']:
            name = list(target)[0]
            props = target[name]
            
            filenames = []
                        
            for rate in props['rates']:
                if props['type'] == 'rtmp':
                    muxer = {'flvmux': {'name': 'm{}{}'.format(name, rate), 'streamable': True}}
                    sink = {'rtmpsink': {'location': props['location'] + rate}}

                elif props['type'] == 'file':
                    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    l = props['location']
                    prefix = l[:l.rfind('/')]
                    filename = '{} {}{}.{}'.format(ts, l[l.rfind('/') + 1:], rate, props['muxer'])
                    location = '{}/{}'.format(prefix, filename)

                    sink = {'filesink': {'location': location}}
                    filenames.append(filename)

                    if props['muxer'] == 'mp4':
                        muxer = {'mp4mux': {'name': 'm{}{}'.format(name, rate), 'faststart': True}}
                    elif props['muxer'] == 'mkv':
                        muxer = {'matroskamux': {'name': 'm{}{}'.format(name, rate)}}

                self.malm([muxer, sink])
                
                mux = getattr(self, 'm{}{}'.format(name, rate))
                rate_tee = getattr(self, 't{}'.format(rate))
                
                vq = Gst.ElementFactory.make('queue')
                aq = Gst.ElementFactory.make('queue')
                
                self.muxqs.add(vq)
                self.muxqs.add(aq)
                
                self.pipeline.add(vq)
                self.pipeline.add(aq)
                
                rate_tee.link(vq)
                vq.link(mux)
                
                self.aall.link(aq)
                aq.link(mux)
            
            action = props.get('stop_action')
            if action:
                action['filenames'] = filenames
                self.stop_actions.append(action)
                
    def malm(self, to_add):
        # Make-add-link multi
        prev = None
        for desc in to_add:
            if type(desc) == str:
                _type = desc
                props = None
                name = None

            elif type(desc) == dict:
                _type = list(desc)[0]
                props = desc.get(_type)
                
                name = props.get('name')
                if name: del props['name']
            
            element = Gst.ElementFactory.make(_type, name)

            if not element:
                raise Exception('cannot create element {}'.format(_type))

            self.elements.add(element)
            if name: setattr(self, name, element)
            
            if props:
                for p, v in props.items():
                    if p == 'caps':
                        caps = Gst.Caps.from_string(v)
                        element.set_property('caps', caps)
                    else:
                        element.set_property(p, v)
            
            self.pipeline.add(element)
            if prev: prev.link(element)
            
            prev = element
            
    def run(self):
        GLib.timeout_add(2 * 1000, self.do_keyframe, None)

        asyncio.ensure_future(self.run_scheduler())

        self.ws_server = websockets.serve(self.handler, '0.0.0.0', 8081)
        self.loop.run_until_complete(self.ws_server)
        self.loop.run_forever()

    async def run_scheduler(self):
        while True:
            schedule.run_pending()
            await asyncio.sleep(1)    

    def stop(self): 
        print('Exiting...')
        self.stream_stop()
        self.loop.stop()
        
    def do_keyframe(self, user_data):
        # Forces a keyframe on all video encoders
        if self.stream_state == 'streaming' and self.force_keyframes:
            event = GstVideo.video_event_new_downstream_force_key_unit(self.clock.get_time(), 0, 0, True, 0)
            self.pipeline.send_event(event)
        
        return True
    
    def on_message(self, bus, msg):
        sendmsg = None

        if msg.type == Gst.MessageType.ERROR:
            sendmsg = 'error {}'.format(msg.parse_error())
        
        if msg.type == Gst.MessageType.WARNING:
            sendmsg = 'warning {}'.format(msg.parse_error())
        
        if msg.type == Gst.MessageType.STATE_CHANGED:
            statemap = {
                Gst.State.NULL: 'stopped',
                Gst.State.READY: 'ready',
                Gst.State.PAUSED: 'paused',
                Gst.State.PLAYING: 'streaming'
            }
            
            newstate = statemap[msg.parse_state_changed().newstate]
            if not self.stream_state == newstate:
                self.stream_state = newstate
                sendmsg = 'state {}'.format(newstate)

        if sendmsg:
            print(sendmsg)
            self.publish(sendmsg)
    
    def stream_restart(self):
        self.stream_stop()
        asyncio.ensure_future(self._stream_restart_delay())

    async def _stream_restart_delay(self):
        await asyncio.sleep(3) 
        self.stream_start()

    def stream_stop(self):
        if self.stream_state == 'stopped': return

        print('stopping stream')
        Gst.debug_bin_to_dot_file(self.pipeline, Gst.DebugGraphDetails.ALL, 'slapdash')

        for queue in self.muxqs:
            muxpad = queue.get_static_pad('src').get_peer()
            muxpad.send_event(Gst.Event.new_eos())

        self.pipeline.set_state(Gst.State.NULL)
        for element in self.elements: self.pipeline.remove(element)

        self.stream_state = 'stopped'
        self.publish('state stopped')
        
        print(self.stop_actions)
        for action in self.stop_actions:
            if action.get('type') == 'cedar_media_add':
                if not MeteorClient:
                    print('Cannot perform stop action, meteor not installed')
                    return
            
            print('Attempting to connect to Cedar server')
            cedar = MeteorClient('ws://{}/websocket'.format(action.get('server')))
            cedar.on('connected', lambda: self.cedar_connected(cedar, action))
            cedar.on('failed', lambda: self.cedar_connect_failed(action.get('server')))
            cedar.connect()
    
    def cedar_connected(self, cedar, action):
        for filename in action['filenames']:
            print('Direct-adding file to Cedar server: ', filename)
            cedar.call('mediaDirectAdd', [filename])
    
    def cedar_connect_failed(self, server):
        print('Failed to connecte to Cedar server at ', server)
        
    def stream_start(self):
        if self.stream_state == 'streaming': return

        print('starting stream')
        self.build_pipeline()
        self.pipeline.set_state(Gst.State.PLAYING)
    
    def publish(self, message):
        for queue in self.queues:
            queue.put_nowait(message)
    
    async def consumer_handler(self, websocket):
        while True:
            try: message = await websocket.recv()
            except websockets.exceptions.ConnectionClosed: break
            
            if message == 'restart': self.stream_restart()
            elif message == 'stop': self.stream_stop()
            elif message == 'start': self.stream_start()

    async def producer_handler(self, websocket, queue):
        while True:
            message = await queue.get()
            await websocket.send(message)

    async def handler(self, websocket, path):
        print("connected: {}:{}".format(*websocket.remote_address))

        self.sockets.add(websocket)
        queue = asyncio.Queue()
        self.queues.add(queue)

        queue.put_nowait('state {}'.format(self.stream_state))
#        queue.put_nowait('stream_location {}'.format(settings['stream_location']))
        
        for job in schedule.jobs:
            queue.put_nowait('schedule {} {}'.format(job.job_func.__name__, job.next_run))
        
        try:
            consumer_task = asyncio.ensure_future(self.consumer_handler(websocket))
            producer_task = asyncio.ensure_future(self.producer_handler(websocket, queue))

            done, pending = await asyncio.wait(
                [consumer_task, producer_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            
        finally:
            print("disconnected: {c.host}:{c.port}".format(c = websocket))
            self.sockets.remove(websocket)
            self.queues.remove(queue)

            for task in pending:
                task.cancel()
        
main = Main()

for item in settings['schedule']:
    day = list(item)[0]
    
    for time, action in item[day].items():
        if action == 'start': action = main.stream_start
        elif action == 'stop': action = main.stream_stop
        else: raise Exception('Invalid schedule action: {}'.format(action))    

        if day == 'daily': schedule.every().day.at(time).do(action)
        elif day == 'sunday': schedule.every().sunday.at(time).do(action)
        elif day == 'monday': schedule.every().monday.at(time).do(action)
        elif day == 'tuesday': schedule.every().tuesday.at(time).do(action)
        elif day == 'wednesday': schedule.every().wednesday.at(time).do(action)
        elif day == 'thursday': schedule.every().thursday.at(time).do(action)
        elif day == 'friday': schedule.every().friday.at(time).do(action)
        elif day == 'saturday': schedule.every().saturday.at(time).do(action)
        else: raise Exception('Invalid schedule day: {}'.format(day))

try:
    main.run()
except KeyboardInterrupt:
    main.stop()
