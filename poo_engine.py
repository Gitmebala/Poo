"""
Poo - creature simulation.

The renderer never asks for a pose. It asks the simulation what Poo is doing,
and a pose falls out of that. Underneath there are drives that drift on their
own, a memory that persists between sessions, idle behaviours that fire when
nobody is watching, and a pendulum body: she hangs from a string anchored
above the screen and swings the way a real pendant does when the phone tilts.

Layers, outermost first:
  drives     - happiness / energy / sleepiness / curiosity / affection
  memory     - how she has been treated, saved to disk
  behaviour  - scripted little acts chosen from mood + randomness
  physics    - a damped pendulum, driven by device tilt and by flings
  secondary  - springs that lag behind the body (lean, jiggle, gaze, rig)
"""
import json
import math
import os
import random
import time

import personality as pers

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "poo")
MEMORY_FILE = "poo_memory.json"

# ---------------------------------------------------------------- poses ----
POSE_FILES = {
    "neutral":   ["p_neutral.png",   "face_neutral.png"],
    "content":   ["p_content.png",   "p_neutral.png"],
    "happy":     ["p_happy.png",     "face_happy.png"],
    "excited":   ["p_excited.png",   "p_happy.png"],
    "wink":      ["p_wink.png",      "p_content.png"],
    "sleepy":    ["p_sleepy.png",    "face_sleepy.png"],
    "shy":       ["p_shy.png",       "face_shy.png"],
    "curious":   ["p_curious.png",   "face_curious.png"],
    "lookup":    ["p_lookup.png",    "p_curious.png"],
    "surprised": ["p_surprised.png", "p_curious.png"],
    "falling":   ["p_falling.png",   "p_surprised.png"],
    "splat":     ["p_splat.png",     "p_surprised.png"],
}


def resolve_poses():
    out = {}
    for name, candidates in POSE_FILES.items():
        for f in candidates:
            p = os.path.join(ASSET_DIR, f)
            if os.path.exists(p):
                out[name] = p
                break
    return out


# --------------------------------------------------------------- tuning ----
# Pendulum: she hangs from a string anchored just above the top of the screen.
# Tilting the phone rotates gravity relative to the phone's own frame, which is
# what actually makes a real pendant swing when you tilt something it's
# hanging from - so tilt becomes the equilibrium angle she swings toward.
ANGULAR_G = 1500.0       # how hard she swings back toward "down"
DAMPING = 1.15           # how fast the swing settles
MAX_OMEGA = 6.0          # rad/s cap so a hard fling can't spin her wildly
TILT_INFLUENCE = 1.0     # how directly phone tilt shifts her equilibrium
STRING_SLACK = 26.0      # px the anchor sits above the visible top edge
FOLLOW_RATE = 20.0       # how snappily she tracks a dragging finger
CROSSFADE = 0.18

BLINK_MIN, BLINK_MAX = 2.5, 9.0
IDLE_ACT_MIN, IDLE_ACT_MAX = 30.0, 100.0     # slower, so acts don't crowd each other
SLEEPY_AFTER = 90.0
DIZZY_SHAKES = 4


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Spring:
    def __init__(self, value=0.0, k=180.0, c=14.0):
        self.value = self.target = value
        self.vel = 0.0
        self.k, self.c = k, c

    def update(self, dt):
        dt = min(dt, 1 / 30.0)
        self.vel += ((self.target - self.value) * self.k - self.vel * self.c) * dt
        self.value += self.vel * dt
        return self.value

    def nudge(self, amount):
        self.vel += amount


class Memory:
    """Persists how Poo has been treated, so she is a specific individual."""

    def __init__(self, directory="."):
        self.path = os.path.join(directory, MEMORY_FILE)
        self.data = {
            "pets": 0, "shakes": 0, "drops": 0, "sessions": 0,
            "seconds_together": 0.0, "last_seen": 0.0, "bond": 0.0,
        }
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                self.data.update(json.load(fh))
        except Exception:
            pass
        self.data["sessions"] = self.data.get("sessions", 0) + 1

    def save(self):
        try:
            self.data["last_seen"] = time.time()
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh)
        except Exception:
            pass

    def hours_away(self):
        last = self.data.get("last_seen", 0.0)
        if not last:
            return 0.0
        return max(0.0, (time.time() - last) / 3600.0)


class Drives:
    """Slow-moving internal state. Everything else reads these."""

    def __init__(self):
        self.happiness = 0.65
        self.energy = 0.8
        self.sleepiness = 0.15
        self.curiosity = 0.6
        self.affection = 0.4

    def decay(self, dt, idle_seconds):
        # sleepiness builds while ignored, faster if energy is low
        self.sleepiness = clamp(
            self.sleepiness + dt * (0.004 + 0.010 * (idle_seconds > SLEEPY_AFTER)) *
            (1.4 - self.energy), 0, 1)
        self.energy = clamp(self.energy - dt * 0.0025, 0.05, 1)
        self.curiosity = clamp(self.curiosity + dt * 0.006 * (1 - self.sleepiness), 0, 1)
        if idle_seconds > 40:
            self.happiness = clamp(self.happiness - dt * 0.004, 0.1, 1)

    def pet(self):
        self.happiness = clamp(self.happiness + 0.10, 0, 1)
        self.affection = clamp(self.affection + 0.04, 0, 1)
        self.sleepiness = clamp(self.sleepiness - 0.06, 0, 1)
        self.curiosity = clamp(self.curiosity + 0.05, 0, 1)

    def jostle(self):
        self.energy = clamp(self.energy - 0.05, 0, 1)
        self.happiness = clamp(self.happiness - 0.04, 0, 1)
        self.sleepiness = clamp(self.sleepiness - 0.15, 0, 1)


class Behaviour:
    """A short scripted act: a list of (pose, seconds, callback) beats."""

    def __init__(self, name, beats, interruptible=True):
        self.name = name
        self.beats = beats
        self.interruptible = interruptible
        self.i = 0
        self.t = 0.0

    def current(self):
        return self.beats[self.i]

    def advance(self, dt):
        self.t += dt
        pose, dur, _fn = self.beats[self.i]
        if self.t >= dur:
            self.t = 0.0
            self.i += 1
            return self.i >= len(self.beats)
        return False


class Poo:
    def __init__(self, width, height, memory_dir="."):
        self.W, self.H = float(width), float(height)
        self.memory = Memory(memory_dir)
        self.drives = Drives()

        self.t = 0.0
        self.body_h = 330.0        # the renderer overwrites this with her real size

        # pendulum state
        self.anchor_x = self.W * 0.5
        self.string_len = min(230.0, self.H * 0.32)
        self.theta = 0.02           # radians from straight-down
        self.omega = 0.0            # angular velocity
        self.tilt = 0.0             # device tilt, radians
        self.held = False
        self.x, self.y = self._pendulum_pos()

        self.squash = Spring(1.0, k=260, c=12)
        self.lean = Spring(0.0, k=110, c=9)      # body lag / secondary motion
        self.gaze_x = Spring(0.0, k=90, c=11)    # -1..1, where she is looking
        self.jiggle = Spring(0.0, k=320, c=7)
        # the rig: each piece lags the body by its own amount
        self.ear_l = Spring(0.0, k=90, c=5.5)
        self.ear_r = Spring(0.0, k=90, c=5.5)
        self.sprout = Spring(0.0, k=150, c=4.2)  # the tuft is light and whippy
        self.blush = Spring(0.0, k=60, c=9)

        self.pose = "neutral"
        self.prev_pose = "neutral"
        self.fade = 1.0
        self.fade_dur = CROSSFADE

        self.behaviour = None
        self.next_idle_at = self.t + random.uniform(6.0, 14.0)
        self.next_blink_at = self.t + random.uniform(BLINK_MIN, BLINK_MAX)
        self.blink_until = -1.0

        self.last_interaction = 0.0
        self.recent_taps = []
        self.shake_times = []
        self.dizzy_until = -1.0
        self.particles = []
        self.speech = ""
        self.speech_until = -1.0
        self._next_mutter = 40.0

        self._greet()

    # ------------------------------------------------------ pose control ----
    def set_pose(self, pose, fade=CROSSFADE):
        if pose == self.pose:
            return
        self.prev_pose = self.pose
        self.pose = pose
        self.fade = 0.0
        self.fade_dur = max(fade, 1 / 120.0)

    def say(self, text, seconds=1.8):
        self.speech = text
        self.speech_until = self.t + seconds

    # ------------------------------------------------------------ character --
    @property
    def stage(self):
        return pers.stage_for(self.memory.data.get("bond", 0.0))

    @property
    def stage_name(self):
        return pers.STAGE_NAMES[self.stage]

    def voice(self, kind, chance=1.0, seconds=2.0):
        """Say something in character, if she has anything to say."""
        text = pers.line(kind, self.stage, chance)
        if text:
            self.say(text, seconds)
        return text

    def _check_milestone(self):
        got = pers.due_milestone(self.memory.data)
        if got:
            _key, text = got
            self.say(text, 2.6)
            self.emit("heart", self.x, self.y, 8)
            return True
        return False

    def _greet(self):
        away = self.memory.hours_away()
        sessions = self.memory.data.get("sessions", 1)
        kind = pers.greeting_kind(away, sessions)
        self.voice(kind, seconds=2.4)

        # how warmly she greets you depends on how well she knows you
        st = self.stage
        if kind == "long_absence" and st >= pers.PLAYFUL:
            self.start_behaviour(self._b_missed_you())
        elif st >= pers.DEVOTED:
            self.start_behaviour(self._b_missed_you())
        elif st >= pers.WARMING:
            self.start_behaviour(self._b_wave())
        else:
            self.start_behaviour(self._b_shy())   # too shy to say much yet

    # ------------------------------------------------------- interactions ----
    def _mark(self):
        self.last_interaction = self.t

    def zone_of(self, y):
        """
        Where on her body a touch landed. self.y is her centre and Kivy's y
        axis points up, so her head is ABOVE centre and her belly below.
        """
        if y > self.y + self.body_h * 0.10:
            return "head"
        if y < self.y - self.body_h * 0.10:
            return "belly"
        return "side"

    def tap(self, x, y):
        self._mark()
        self.recent_taps = [t for t in self.recent_taps if self.t - t < 2.0]
        self.recent_taps.append(self.t)
        self.drives.pet()
        self.memory.data["pets"] += 1
        self.memory.data["bond"] = self.memory.data.get("bond", 0.0) + 0.02

        # a milestone colours what she says, but she still reacts to the touch
        self._check_milestone()

        side = 1.0 if x >= self.x else -1.0
        zone = self.zone_of(y)

        # Where she is touched decides what happens. Nothing here spins her:
        # being poked should never send her rotating.
        if zone == "head":
            self.drives.happiness = clamp(self.drives.happiness + 0.12, 0, 1)
            self.drives.affection = clamp(self.drives.affection + 0.05, 0, 1)
            self.squash.value = 0.88          # she settles down under the hand
            self.squash.nudge(1.6)
            self.ear_l.nudge(16); self.ear_r.nudge(-16); self.sprout.nudge(26)
            self.blush.target = min(1.0, self.blush.target + 0.45)
            self.gaze_x.target = 0.0          # looks up at you
            self.voice("petted", chance=0.30 + 0.15 * self.stage)
            self.start_behaviour(Behaviour("head_pat", [
                ("content", 0.32, None),
                ("happy", 1.05, lambda: self.emit("heart", x, y - 14, 7, 120)),
                ("content", 0.6, None)]), force=True)

        elif zone == "belly":
            # ticklish: a quick flinch away from the finger, then she enjoys it
            self.drives.happiness = clamp(self.drives.happiness + 0.07, 0, 1)
            self.squash.value = 1.06
            self.squash.nudge(-1.4)
            self.lean.nudge(-side * 16)
            self.ear_l.nudge(-30); self.ear_r.nudge(-30); self.jiggle.nudge(13)
            self.look_at(x)
            self.voice("tickled", chance=0.35)
            self.start_behaviour(Behaviour("ticklish", [
                ("surprised", 0.26, lambda: self.emit("spark", x, y, 4, 110)),
                ("happy", 0.75, lambda: self.lean.nudge(side * 11)),
                ("content", 0.45, None)]), force=True)

        else:
            self.drives.happiness = clamp(self.drives.happiness + 0.08, 0, 1)
            self.squash.value = 0.92
            self.squash.nudge(1.5)
            self.ear_l.nudge(-side * 20); self.ear_r.nudge(-side * 20)
            self.jiggle.nudge(8)
            self.blush.target = min(1.0, self.blush.target + 0.25)
            self.look_at(x)
            warm = self.drives.affection > 0.6
            self.voice("petted", chance=0.18 + 0.12 * self.stage)
            self.start_behaviour(Behaviour("loves_it" if warm else "pleased", [
                ("surprised", 0.22, None),
                ("happy", 0.85, lambda: self.emit(
                    "heart" if warm else "spark", x, y, 8 if warm else 6, 120)),
                ("content", 0.5, None)]), force=True)

        # her quirk - a woozy head-shake, not a full rotation
        if len(self.recent_taps) >= 3:
            self.voice("dizzy", chance=0.7)
            self.start_behaviour(Behaviour("woozy", [
                ("surprised", 0.45, lambda: self.lean.nudge(34)),
                ("surprised", 0.35, lambda: self.lean.nudge(-52)),
                ("happy", 0.6, lambda: (self.lean.nudge(26),
                                        self.emit("spark", x, y, 5))),
                ("content", 0.4, None)]), force=True)

    def pet_stroke(self, x, y):
        """Called while a finger slides across her - continuous petting."""
        self._mark()
        self.drives.pet()
        self.look_at(x)
        if random.random() < 0.10:
            self.emit("heart", x, y, 1, spread=70)

    def long_press(self, x, y):
        self._mark()
        self.drives.pet()
        self.voice("shy_moment", chance=0.6)
        self.start_behaviour(self._b_shy(), force=True)

    def tickled(self, x, y):
        self._mark()
        self.drives.happiness = clamp(self.drives.happiness + 0.2, 0, 1)
        self.drives.affection = clamp(self.drives.affection + 0.03, 0, 1)
        self.memory.data["bond"] = self.memory.data.get("bond", 0.0) + 0.03
        self.voice("tickled", chance=0.8)
        self.emit("spark", x, y, 7)
        self.start_behaviour(Behaviour("giggling", [
            ("happy", 0.5, lambda: self.lean.nudge(44)),
            ("excited", 0.6, lambda: self.lean.nudge(-44)),
            ("happy", 0.5, lambda: self.lean.nudge(30)),
            ("content", 0.4, None),
        ]), force=True)

    def shake(self):
        self._mark()
        self.shake_times = [t for t in self.shake_times if self.t - t < 8.0]
        self.shake_times.append(self.t)
        self.drives.jostle()
        self.memory.data["shakes"] += 1
        self.omega = clamp(self.omega + random.choice([-1, 1]) * random.uniform(2.6, 4.4),
                           -MAX_OMEGA, MAX_OMEGA)
        self.jiggle.nudge(22.0)
        self.ear_l.nudge(random.uniform(-30, 30))
        self.ear_r.nudge(random.uniform(-30, 30))

        if len(self.shake_times) >= DIZZY_SHAKES:
            self.dizzy_until = self.t + 5.0
            self.start_behaviour(self._b_dizzy(), force=True)
        else:
            self.start_behaviour(self._b_startled(), force=True)

    def grab(self, x, y):
        self._mark()
        self.held = True
        self.x, self.y = x, y
        self.set_pose("surprised", fade=0.08)
        self.behaviour = None

    def release(self, vx, vy):
        """
        Released mid-air, from wherever your finger let go. The anchor moves
        to sit directly above the release point and the string is whatever
        length reaches her from there, so she keeps swinging naturally from
        where you actually let go rather than snapping back to center.
        """
        self.held = False
        anchor_y = self.H + STRING_SLACK
        self.anchor_x = clamp(self.x, self.W * 0.08, self.W * 0.92)
        self.string_len = clamp(anchor_y - self.y, 50.0, self.H * 1.4)
        dx = self.x - self.anchor_x
        self.theta = math.atan2(dx, max(anchor_y - self.y, 1.0))
        # a fling imparts spin around the anchor, not a straight-line toss
        tangential = vx * math.cos(self.theta) - (-vy) * math.sin(self.theta)
        self.omega = clamp(tangential / max(self.string_len, 1.0), -MAX_OMEGA, MAX_OMEGA)
        if abs(vx) > 900 or abs(vy) > 900:
            self.memory.data["drops"] += 1
            self.start_behaviour(self._b_thrown(), force=True)

    def look_at(self, x):
        self.gaze_x.target = clamp((x - self.x) / (self.W * 0.5), -1, 1)

    def set_tilt(self, radians):
        self.tilt = clamp(radians, -1.2, 1.2)

    # --------------------------------------------------------- behaviours ----
    def start_behaviour(self, b, force=False):
        if self.behaviour and not self.behaviour.interruptible and not force:
            return
        self.behaviour = b
        self.behaviour.i = 0
        self.behaviour.t = 0.0

    def _b_pleased(self, x, y):
        def spark():
            self.emit("spark", x, y, 6)
        return Behaviour("pleased", [
            ("happy", 0.9, spark),
            ("content", 0.5, None),
        ])

    def _b_love(self, x, y):
        def hearts():
            self.emit("heart", x, y, 9)
        return Behaviour("love", [
            ("happy", 1.0, hearts),
            ("content", 0.6, None),
        ])

    def _b_shy(self):
        return Behaviour("shy", [
            ("shy", 1.6, lambda: self.emit("heart", self.x, self.y, 3, spread=80)),
            ("content", 0.5, None),
        ])

    def _b_startled(self):
        return Behaviour("startled", [
            ("surprised", 0.7, lambda: self.emit("spark", self.x, self.y, 8, spread=240)),
            ("curious", 0.5, None),
        ])

    def _b_dizzy(self):
        def wobble():
            self.lean.nudge(70.0)
        return Behaviour("dizzy", [
            ("surprised", 1.2, wobble),
            ("surprised", 1.4, lambda: self.lean.nudge(-50.0)),
            ("curious", 0.8, None),
        ], interruptible=False)

    def _b_pretend_dizzy(self):
        return Behaviour("pretend_dizzy", [
            ("surprised", 0.5, lambda: self.lean.nudge(45.0)),
            ("happy", 0.8, lambda: self.emit("spark", self.x, self.y, 5)),
        ])

    def _b_thrown(self):
        return Behaviour("thrown", [
            ("surprised", 0.6, None),
        ])

    def _b_wave(self):
        return Behaviour("wave", [
            ("curious", 0.35, lambda: self.lean.nudge(-22.0)),   # anticipation
            ("happy", 1.1, lambda: self.say("hi!", 1.4)),
            ("content", 0.5, None),
        ])

    def _b_missed_you(self):
        return Behaviour("missed_you", [
            ("lookup", 0.5, None),
            ("excited", 1.4, lambda: (self.emit("heart", self.x, self.y, 10),
                                      self.say("you're back!", 2.0))),
            ("happy", 0.8, None),
        ])

    def _b_stretch(self):
        def up():
            self.squash.value = 1.16
            self.squash.nudge(-2.0)
        return Behaviour("stretch", [
            ("content", 0.3, None),
            ("lookup", 0.8, up),
            ("neutral", 0.4, None),
        ])

    def _b_yawn(self):
        return Behaviour("yawn", [
            ("sleepy", 0.4, None),        # anticipation
            ("surprised", 0.7, lambda: self.say("~yawn~", 1.2)),
            ("sleepy", 0.8, None),
        ])

    def _b_look_around(self):
        def peek_l():
            self.gaze_x.target = -1.0
            self.lean.target = -7.0
        def peek_r():
            self.gaze_x.target = 1.0
            self.lean.target = 7.0
        def reset():
            self.gaze_x.target = 0.0
            self.lean.target = 0.0
        return Behaviour("look_around", [
            ("curious", 0.8, peek_l),
            ("curious", 0.9, peek_r),
            ("neutral", 0.5, reset),
        ])

    def _b_wiggle(self):
        def w():
            self.lean.nudge(38.0)
            self.jiggle.nudge(12.0)
        return Behaviour("wiggle", [
            ("happy", 0.9, w),
            ("content", 0.4, None),
        ])

    def _b_sniff(self):
        return Behaviour("sniff", [
            ("curious", 0.5, lambda: self.lean.nudge(10.0)),
            ("neutral", 0.4, None),
        ])

    def _b_hop(self):
        """A little kick to the swing, like she pushed off with her feet."""
        def kick():
            self.squash.value = 0.78
            self.squash.nudge(4.0)
            self.omega = clamp(self.omega + random.choice([-1, 1]) * 1.6,
                               -MAX_OMEGA, MAX_OMEGA)
        return Behaviour("hop", [
            ("curious", 0.22, None),
            ("excited", 0.5, kick),
        ])

    def _b_smile(self):
        return Behaviour("smile", [("content", 1.3, None)])

    def _pick_idle(self):
        """Mood sets the odds; personality stage then reweights them."""
        d = self.drives
        st = self.stage
        pool = [
            ("look",    self._b_look_around, 1.0 + d.curiosity * 2.2),
            ("smile",   self._b_smile,       0.8 + d.happiness * 1.2),
            ("wiggle",  self._b_wiggle,      0.4 + d.energy * 1.6),
            ("sniff",   self._b_sniff,       0.5 + d.curiosity * 1.0),
            ("stretch", self._b_stretch,     0.6 + (1 - d.energy) * 1.0),
            ("yawn",    self._b_yawn,        0.2 + d.sleepiness * 3.0),
            ("hop",     self._b_hop,         0.2 + d.energy * 1.4 * (1 - d.sleepiness)),
            ("wave",    self._b_wave,        0.2 + d.affection * 1.5),
            ("shy_hide", self._b_shy,        0.3),
            ("watch_you", self._b_watch_you, 0.3 + d.affection * 1.4),
        ]
        weighted = [(fn, w * pers.bias(st, name)) for name, fn, w in pool]
        total = sum(w for _f, w in weighted)
        if total <= 0:
            return self._b_smile()
        r = random.uniform(0, total)
        for fn, w in weighted:
            r -= w
            if r <= 0:
                return fn()
        return self._b_smile()

    def _b_watch_you(self):
        """Devoted Poo simply looks up at you for a while."""
        def gaze():
            self.gaze_x.target = 0.0
            if random.random() < 0.5:
                self.voice("happy", chance=0.5, seconds=1.6)
        return Behaviour("watch_you", [
            ("lookup", 1.6, gaze),
            ("content", 0.6, None),
        ])

    # ---------------------------------------------------------- particles ----
    def emit(self, kind, x, y, count, spread=170.0):
        for _ in range(count):
            a = random.uniform(0, math.tau)
            s = random.uniform(spread * 0.45, spread)
            self.particles.append({
                "kind": kind, "x": x, "y": y,
                "vx": math.cos(a) * s, "vy": abs(math.sin(a) * s) * 0.9 + 40,
                "life": 0.0, "ttl": random.uniform(0.6, 1.0),
                "size": random.uniform(16, 30),
            })

    def _step_particles(self, dt):
        out = []
        for p in self.particles:
            p["life"] += dt
            if p["life"] >= p["ttl"]:
                continue
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] -= 260 * dt
            p["vx"] *= 0.985
            out.append(p)
        self.particles = out

    # ------------------------------------------------------------ physics ----
    def _pendulum_pos(self, theta=None):
        theta = self.theta if theta is None else theta
        anchor_y = self.H + STRING_SLACK
        x = self.anchor_x + self.string_len * math.sin(theta)
        y = anchor_y - self.string_len * math.cos(theta)
        return x, y

    def _step_physics(self, dt):
        if self.held:
            return

        # Tilting the phone rotates gravity relative to the phone's frame, so
        # the pendulum's rest angle shifts toward the tilt - exactly what
        # happens to a real pendant on a string when you tip what it hangs
        # from.
        rest = self.tilt * TILT_INFLUENCE
        omega_dot = (-(ANGULAR_G / max(self.string_len, 1.0)) * math.sin(self.theta - rest)
                    - DAMPING * self.omega)
        self.omega = clamp(self.omega + omega_dot * dt, -MAX_OMEGA, MAX_OMEGA)
        self.theta += self.omega * dt

        prev_x = self.x
        self.x, self.y = self._pendulum_pos()

        # she nudges her own jiggle a little when swinging fast, so a hard
        # push still reads as physical even without a floor to land on
        speed = abs(self.x - prev_x) / max(dt, 1 / 240.0)
        if speed > 260:
            self.jiggle.nudge(min(speed * 0.01, 6.0))

    # --------------------------------------------------------------- tick ----
    def update(self, dt):
        dt = min(dt, 1 / 30.0)
        self.t += dt
        idle = self.t - self.last_interaction

        self.drives.decay(dt, idle)
        self.memory.data["seconds_together"] = self.memory.data.get("seconds_together", 0.0) + dt
        # simply being together counts for something, slowly
        self.memory.data["bond"] = self.memory.data.get("bond", 0.0) + dt * 0.0009

        # she speaks up now and then when she has been left alone a while
        if idle > 55 and self.t >= self._next_mutter:
            self._next_mutter = self.t + random.uniform(35, 90)
            self.voice("lonely" if self.drives.sleepiness < 0.7 else "sleepy",
                       chance=0.55, seconds=2.2)

        if self.fade < 1.0:
            self.fade = min(1.0, self.fade + dt / self.fade_dur)

        self._step_physics(dt)
        self._step_particles(dt)

        swinging_hard = abs(self.omega) > 3.0

        if self.behaviour is not None:
            pose, _dur, fn = self.behaviour.current()
            if self.behaviour.t == 0.0 and fn:
                fn()
            self.set_pose(pose)
            if self.behaviour.advance(dt):
                self.behaviour = None
        else:
            if self.held:
                self.set_pose("surprised")
            elif self.t < self.dizzy_until or swinging_hard:
                self.set_pose("surprised")
            elif idle > SLEEPY_AFTER or self.drives.sleepiness > 0.82:
                self.set_pose("sleepy")
            else:
                self._resting_pose()

            if self.t >= self.next_idle_at and not self.held and not swinging_hard:
                self.start_behaviour(self._pick_idle())
                gap = IDLE_ACT_MIN + (IDLE_ACT_MAX - IDLE_ACT_MIN) * (1 - self.drives.curiosity)
                self.next_idle_at = self.t + random.uniform(gap * 0.7, gap)

        self._step_blink(swinging_hard)

        if self.t > self.speech_until:
            self.speech = ""

        for spring in (self.squash, self.lean, self.gaze_x, self.jiggle,
                       self.ear_l, self.ear_r, self.sprout, self.blush):
            spring.update(dt)
        self.blush.target *= 0.995

        # gaze drifts back to centre when nothing is happening
        if idle > 3.0:
            self.gaze_x.target *= 0.985

    def _resting_pose(self):
        """Rest face reflects mood, and drifts so she is never frozen."""
        d = self.drives
        if d.sleepiness > 0.6:
            self.set_pose("sleepy")
        elif d.happiness > 0.75:
            self.set_pose("content")
        elif abs(self.gaze_x.value) > 0.45:
            self.set_pose("curious")
        else:
            self.set_pose("neutral")

    def _step_blink(self, swinging_hard):
        if self.blink_until > 0:
            if self.t >= self.blink_until:
                self.blink_until = -1.0
                self.next_blink_at = self.t + random.uniform(BLINK_MIN, BLINK_MAX)
                self._resting_pose()
            return
        if swinging_hard or self.held or self.behaviour is not None:
            return
        if self.t < self.next_blink_at:
            return
        if self.pose not in ("neutral", "curious", "content"):
            self.next_blink_at = self.t + 1.2
            return
        self.blink_until = self.t + 0.12
        self.set_pose("wink", fade=0.05)

    # -------------------------------------------------------------- output ----
    def visual(self):
        breath = math.sin(self.t * 1.35) * 0.016
        sq = self.squash.value
        scale_y = sq * (1.0 + breath)
        scale_x = (1.0 / max(sq, 0.35)) * (1.0 - breath * 0.55)

        # she banks INTO the swing, like she is hanging from the string, not
        # rotating freely on her own - the angle follows theta directly
        wobble = math.sin(self.t * 15.0) * self.jiggle.value * 0.16
        swing_deg = math.degrees(self.theta) if not self.held else 0.0
        rot = clamp(self.lean.value + wobble + swing_deg * 0.5, -40, 40)

        anchor_y = self.H + STRING_SLACK
        return {
            "x": self.x, "y": self.y,
            "anchor_x": self.anchor_x, "anchor_y": anchor_y,
            "scale_x": scale_x, "scale_y": scale_y,
            "rotation": rot,
            "pose": self.pose, "prev_pose": self.prev_pose, "fade": self.fade,
            "gaze": self.gaze_x.value,
            "particles": self.particles,
            "ear_l": self.ear_l.value,
            "ear_r": self.ear_r.value,
            "sprout": self.sprout.value,
            "blush": clamp(self.blush.value, 0.0, 1.0),
            "speech": self.speech,
            "stage": self.stage_name,
            "bond": self.memory.data.get("bond", 0.0),
            "drives": {
                "happiness": self.drives.happiness, "energy": self.drives.energy,
                "sleepiness": self.drives.sleepiness, "curiosity": self.drives.curiosity,
                "affection": self.drives.affection,
            },
            "behaviour": self.behaviour.name if self.behaviour else "",
        }
