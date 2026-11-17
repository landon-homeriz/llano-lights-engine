// Llano Light Link: sends each deck's beat state out of Mixxx as SysEx so the
// gigbar_lights app can run the light show on the beat.
//
// Load this mapping on a loopMIDI port named "Llano Mixxx" (Preferences >
// Controllers). It reads only; it never changes anything in Mixxx.
// Wire format is documented in gigbar_lights/mixxx_link.py; keep the two in step.

var LlanoLightLink = {};

LlanoLightLink.DECKS = 4;
LlanoLightLink.connections = [];
LlanoLightLink.timers = [];

LlanoLightLink.pack7 = function(value, count) {
    var out = [];
    var v = Math.max(0, Math.round(value));
    for (var i = 0; i < count; i++) {
        out.push(v % 128);
        v = Math.floor(v / 128);
    }
    return out;
};

LlanoLightLink.send = function(bytes) {
    midi.sendSysexMsg(bytes, bytes.length);
};

// How audible a deck is, the way Mixxx's own "current playing deck" judges it:
// playing, pregain above 0.25, channel volume, weighted by the crossfader side.
LlanoLightLink.weight = function(group) {
    if (!engine.getValue(group, "play") || engine.getValue(group, "pregain") <= 0.25) {
        return 0;
    }
    var xf = engine.getValue("[Master]", "crossfader");
    var orientation = engine.getValue(group, "orientation"); // 0 left, 1 center, 2 right
    var side = 1;
    if (orientation === 0) {
        side = Math.min(1, Math.max(0, 1 - xf));
    } else if (orientation === 2) {
        side = Math.min(1, Math.max(0, 1 + xf));
    }
    return Math.min(1, engine.getValue(group, "volume") * side);
};

// Length of the active loop in beats (0 when none), at the track's own tempo.
LlanoLightLink.loopBeats = function(group) {
    if (!engine.getValue(group, "loop_enabled")) {
        return 0;
    }
    var start = engine.getValue(group, "loop_start_position");
    var end = engine.getValue(group, "loop_end_position");
    var rate = engine.getValue(group, "track_samplerate");
    var fileBpm = engine.getValue(group, "file_bpm");
    if (start < 0 || end <= start || rate <= 0 || fileBpm <= 0) {
        return 0;
    }
    // Loop positions are in samples across both stereo channels.
    return (end - start) / 2 / (rate * 60 / fileBpm);
};

LlanoLightLink.sendTick = function(deck, beatDistance) {
    var group = "[Channel" + deck + "]";
    var loaded = engine.getValue(group, "track_loaded");
    var flags = (engine.getValue(group, "play") ? 1 : 0) | (loaded ? 2 : 0);
    // track_samples counts both stereo channels, so frames = samples / 2.
    var posFrames = loaded ?
        engine.getValue(group, "playposition") * engine.getValue(group, "track_samples") / 2 : 0;
    // Use the value the connection delivered, so each engine step goes out as it was.
    var raw = (beatDistance === undefined) ? engine.getValue(group, "beat_distance") : beatDistance;
    var distance = Math.min(1, Math.max(0, raw));
    var msg = [0xF0, 0x7D, 0x4C, 0x01, deck, flags]
        .concat(LlanoLightLink.pack7(engine.getValue(group, "bpm") * 100, 3))
        .concat(LlanoLightLink.pack7(distance * 16383, 2))
        .concat(LlanoLightLink.pack7(posFrames, 5))
        .concat([Math.round(LlanoLightLink.weight(group) * 127),
            Math.round(Math.min(1, Math.max(0, engine.getValue(group, "vu_meter"))) * 127)])
        .concat(LlanoLightLink.pack7(Math.min(255, LlanoLightLink.loopBeats(group)) * 64, 2))
        .concat([0xF7]);
    LlanoLightLink.send(msg);
};

LlanoLightLink.sendTrack = function(deck) {
    var group = "[Channel" + deck + "]";
    var msg = [0xF0, 0x7D, 0x4C, 0x02, deck]
        .concat(LlanoLightLink.pack7(engine.getValue(group, "track_samplerate"), 3))
        .concat(LlanoLightLink.pack7(engine.getValue(group, "duration") * 100, 4))
        .concat(LlanoLightLink.pack7(engine.getValue(group, "file_bpm") * 100, 3))
        .concat([0xF7]);
    LlanoLightLink.send(msg);
};

LlanoLightLink.sendAudio = function() {
    var latency = engine.getValue("[Master]", "latency");
    LlanoLightLink.send([0xF0, 0x7D, 0x4C, 0x03]
        .concat(LlanoLightLink.pack7(latency * 10, 2))
        .concat([0xF7]));
};

LlanoLightLink.init = function(_id, _debugging) {
    for (var d = 1; d <= LlanoLightLink.DECKS; d++) {
        var group = "[Channel" + d + "]";
        // beat_distance changes once per audio buffer while a deck plays. The
        // unbuffered connection delivers every update instead of only the latest,
        // so the app sees each step and can smooth the jitter itself.
        LlanoLightLink.connections.push(engine.makeUnbufferedConnection(group, "beat_distance",
            (function(deck) {
                return function(value) { LlanoLightLink.sendTick(deck, value); };
            })(d)));
        // A new track's duration and file BPM can land after track_samples, so resend the
        // track identity whenever any of the three changes.
        ["track_samples", "duration", "file_bpm"].forEach(function(key) {
            LlanoLightLink.connections.push(engine.makeConnection(group, key,
                (function(deck) {
                    return function() { LlanoLightLink.sendTrack(deck); };
                })(d)));
        });
        LlanoLightLink.sendTrack(d);
    }
    // Stopped decks never move beat_distance, so a slow heartbeat keeps play,
    // volume and crossfader changes flowing; track and latency repeat for an app
    // started after Mixxx.
    LlanoLightLink.timers.push(engine.beginTimer(100, function() {
        for (var d = 1; d <= LlanoLightLink.DECKS; d++) {
            LlanoLightLink.sendTick(d);
        }
    }));
    LlanoLightLink.timers.push(engine.beginTimer(2000, function() {
        for (var d = 1; d <= LlanoLightLink.DECKS; d++) {
            LlanoLightLink.sendTrack(d);
        }
        LlanoLightLink.sendAudio();
    }));
    LlanoLightLink.sendAudio();
};

LlanoLightLink.shutdown = function() {
    LlanoLightLink.timers.forEach(function(t) { engine.stopTimer(t); });
    LlanoLightLink.connections.forEach(function(c) { c.disconnect(); });
    LlanoLightLink.timers = [];
    LlanoLightLink.connections = [];
};
