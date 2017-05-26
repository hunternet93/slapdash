# Slapdash

Slapdash is a Gstreamer-based DASH streaming system, designed to encode video and audio at multiple resolutions and bitrates and feed them to an [nginx-rtmp](https://github.com/ut0mt8/nginx-rtmp-module/) server. 

See [https://isrv.pw/html5-live-streaming-with-mpeg-dash](this page) for more information about setting up DASH streaming.

### Requirements

* Python 3.5 or greater
* Gstreamer 1.0 or greater
* Python GI bindings
* [Schedule](https://github.com/dbader/schedule)
* [gbulb](https://github.com/nathan-hoad/gbulb)
* [Websockets](https://websockets.readthedocs.io/en/stable/index.html)
* YAML

### Running slapdash

`python3 -m http.server 8080`
