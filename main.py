"""
Poo - a little companion that lives on your phone.

This file is only eyes and hands: it draws whatever the simulation in
poo_engine is currently doing, and forwards touches and sensors into it.
All personality lives in the engine.
"""
import math
import os

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import (Color, Ellipse, PopMatrix, PushMatrix, Rectangle,
                           Rotate, Scale, Translate)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

import poo_engine as pe

POO_HEIGHT = 330.0
LONG_PRESS = 0.55
TILT_SIGN = -1.0          # flip if she slides the wrong way on the device
SHAKE_JOLT = 24.0


def glyph(ch, color, size=44):
    lbl = CoreLabel(text=ch, font_size=size, color=color)
    lbl.refresh()
    return lbl.texture


RIG_DIR = os.path.join(pe.ASSET_DIR, "rig")
RIG_PARTS = ("ear_l", "ear_r", "body", "sprout")
# measured on the 620x700 sprite canvas, stored as fractions of it
PIVOTS = {"ear_l": (0.445, 0.438), "ear_r": (0.555, 0.438), "sprout": (0.5, 0.286)}


class PooView(Widget):
    def __init__(self, poo, **kw):
        super().__init__(**kw)
        self.poo = poo
        self.tex = {}
        self.rig = {}
        for name, path in pe.resolve_poses().items():
            try:
                self.tex[name] = CoreImage(path).texture
            except Exception as exc:
                print("load failed", path, exc)
            # if this pose was split into puppet layers, load those too
            parts = {}
            for part in RIG_PARTS:
                p = os.path.join(RIG_DIR, "%s_%s.png" % (name, part))
                if os.path.exists(p):
                    try:
                        parts[part] = CoreImage(p).texture
                    except Exception as exc:
                        print("rig load failed", p, exc)
            if len(parts) == len(RIG_PARTS):
                self.rig[name] = parts

        base = self.tex.get("neutral") or (next(iter(self.tex.values())) if self.tex else None)
        aspect = (base.width / float(base.height)) if base else 0.9
        self.h = POO_HEIGHT
        self.w = POO_HEIGHT * aspect

        self.ptex = {"heart": glyph("♥", (1, .42, .62, 1)),
                     "spark": glyph("✦", (1, .93, .55, 1))}

        with self.canvas:
            self._shadow_c = Color(0, 0, 0, 0)
            self._shadow = Ellipse(size=(0, 0))
            PushMatrix()
            self._tr = Translate(0, 0)
            self._rot = Rotate(angle=0, axis=(0, 0, 1))
            self._sc = Scale(1, 1, 1)
            # two full puppets: the outgoing pose and the incoming one, so an
            # expression can cross-fade while the rig keeps moving underneath
            self._puppet_prev = self._make_puppet()
            self._puppet_cur = self._make_puppet()
            self._blush_c = Color(1, 0.5, 0.69, 0)
            self._blush = [Ellipse(size=(0, 0)), Ellipse(size=(0, 0))]
            PopMatrix()
            self._extra = []

    def _make_puppet(self):
        """One set of layers, each able to rotate about its own pivot."""
        pup = {}
        for part in RIG_PARTS:
            PushMatrix()
            px, py = PIVOTS.get(part, (0.5, 0.5))
            # pivot expressed relative to her centre
            ox = (px - 0.5) * self.w
            oy = (0.5 - py) * self.h
            Translate(ox, oy)
            rot = Rotate(angle=0, axis=(0, 0, 1))
            Translate(-ox, -oy)
            col = Color(1, 1, 1, 1)
            rect = Rectangle(size=(self.w, self.h), pos=(-self.w / 2, -self.h / 2))
            PopMatrix()
            pup[part] = {"rot": rot, "col": col, "rect": rect}
        return pup

    def _apply_puppet(self, pup, pose, alpha, v):
        """Point one puppet at a pose and set its joint angles."""
        parts = self.rig.get(pose)
        flat = self.tex.get(pose)
        ang = {"ear_l": v["ear_l"], "ear_r": v["ear_r"], "sprout": v["sprout"],
               "body": 0.0}
        for part in RIG_PARTS:
            node = pup[part]
            if parts is not None:
                node["rect"].texture = parts[part]
                node["col"].a = alpha
                node["rot"].angle = ang[part]
            else:
                # falling / splat have no rig, so the body layer carries it all
                node["rect"].texture = flat if part == "body" else None
                node["col"].a = alpha if part == "body" else 0.0
                node["rot"].angle = 0.0

    def sync(self):
        v = self.poo.visual()

        self._apply_puppet(self._puppet_prev, v["prev_pose"], 1.0 - v["fade"], v)
        self._apply_puppet(self._puppet_cur, v["pose"], v["fade"], v)

        # blush is painted on, so it works on any pose
        b = v.get("blush", 0.0)
        if b > 0.03:
            self._blush_c.a = b * 0.5
            bw = self.w * 0.17
            for i, sgn in enumerate((-1, 1)):
                self._blush[i].size = (bw, bw * 0.62)
                self._blush[i].pos = (sgn * self.w * 0.19 - bw / 2,
                                      self.h * 0.06)
        else:
            self._blush_c.a = 0.0

        self._tr.x, self._tr.y = v["x"], v["y"]
        self._rot.angle = v["rotation"]
        self._sc.x, self._sc.y = v["scale_x"], v["scale_y"]

        # ground shadow shrinks and fades as she rises
        s = v["shadow"]
        if s > 0.02:
            sw = self.w * (0.30 + 0.24 * s)
            self._shadow_c.rgba = (0, 0, 0, 0.30 * s)
            self._shadow.size = (sw, sw * 0.2)
            self._shadow.pos = (v["x"] - sw / 2, self.poo.floor_y() - self.h * 0.44)
        else:
            self._shadow_c.a = 0.0

        for i in self._extra:
            self.canvas.remove(i)
        self._extra = []
        with self.canvas:
            for p in v["particles"]:
                life = p["life"] / p["ttl"]
                c = Color(1, 1, 1, max(0.0, 1.0 - life))
                sz = p["size"] * (1 + life * 0.4)
                r = Rectangle(texture=self.ptex[p["kind"]],
                              pos=(p["x"] - sz / 2, p["y"] - sz / 2), size=(sz, sz))
                self._extra += [c, r]

            if v["speech"]:
                t = glyph(v["speech"], (1, 1, 1, 1), size=34)
                c = Color(1, 1, 1, 0.95)
                r = Rectangle(texture=t, size=t.size,
                              pos=(v["x"] - t.width / 2,
                                   v["y"] + self.h * 0.42))
                self._extra += [c, r]

    def hit(self, x, y):
        v = self.poo.visual()
        return (abs(x - v["x"]) < self.w * 0.42 and
                abs(y - v["y"]) < self.h * 0.44)


class Root(FloatLayout):
    def __init__(self, **kw):
        super().__init__(**kw)
        store = os.environ.get("ANDROID_PRIVATE") or os.path.dirname(os.path.abspath(__file__))
        self.poo = pe.Poo(Window.width, Window.height, memory_dir=store)
        self.view = PooView(self.poo, size_hint=(1, 1))
        self.add_widget(self.view)

        self._press_t = 0.0
        self._press_xy = (0, 0)
        self._last = (0, 0, 0.0)
        self._long = False
        self._dragging = False

        self._ui()
        self._sensors()
        self.bind(size=self._resize)
        Clock.schedule_interval(self._tick, 1 / 60.0)
        Clock.schedule_interval(lambda *_a: self.poo.memory.save(), 20.0)

    def _resize(self, *_a):
        self.poo.W, self.poo.H = float(self.width), float(self.height)
        self.view.size = self.size

    def _ui(self):
        bar = BoxLayout(size_hint=(1, None), height=58, pos_hint={"x": 0, "top": 1},
                        padding=9, spacing=9)
        with bar.canvas.before:
            Color(0.14, 0.11, 0.2, 0.9)
            self._bg = Rectangle(pos=bar.pos, size=bar.size)
        bar.bind(pos=lambda *a: setattr(self._bg, "pos", bar.pos),
                 size=lambda *a: setattr(self._bg, "size", bar.size))
        b = Button(text="Let Poo out", background_normal="", bold=True,
                   background_color=(0.45, 0.56, 0.78, 1))
        b.bind(on_release=lambda *a: self.request_overlay())
        bar.add_widget(b)
        self.add_widget(bar)
        self.status = Label(text="", size_hint=(1, None), height=22,
                            pos_hint={"x": 0, "top": 0.93}, font_size=12,
                            color=(0.8, 0.76, 0.88, 1))
        self.add_widget(self.status)

    def _sensors(self):
        self._accel = None
        self._prev_a = None
        try:
            from plyer import accelerometer
            accelerometer.enable()
            self._accel = accelerometer
            Clock.schedule_interval(self._poll, 1 / 20.0)
        except Exception:
            pass

    def _poll(self, _dt):
        try:
            ax, ay, az = self._accel.acceleration[:3]
        except Exception:
            return
        if ax is None or ay is None:
            return
        self.poo.set_tilt(math.atan2(ax, max(abs(ay), 0.5)) * TILT_SIGN)
        if self._prev_a:
            lx, ly, lz = self._prev_a
            if (abs(ax - lx) + abs(ay - ly) + abs((az or 0) - lz)) > SHAKE_JOLT:
                self.poo.shake()
        self._prev_a = (ax, ay, az or 0)

    # ---- touch ----
    def on_touch_down(self, touch):
        if super().on_touch_down(touch):
            return True
        if not self.view.hit(*touch.pos):
            self.poo.look_at(touch.x)      # she glances at where you tapped
            return False
        self._press_t = Clock.get_time()
        self._press_xy = touch.pos
        self._last = (touch.x, touch.y, self._press_t)
        self._long = False
        self._dragging = False
        touch.grab(self)
        self.poo.tap(*touch.pos)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_move(touch)
        moved = math.hypot(touch.x - self._press_xy[0], touch.y - self._press_xy[1])
        if not self._dragging and moved > 14:
            self._dragging = True
            self.poo.grab(touch.x, touch.y)
        if self._dragging:
            self.poo.x, self.poo.y = touch.x, touch.y
            self.poo.look_at(touch.x)
            self.poo.lean.target = max(-16, min(16, -touch.dx * 0.7))
            self._last = (touch.x, touch.y, Clock.get_time())
        else:
            self.poo.pet_stroke(touch.x, touch.y)   # stroking without lifting
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        self.poo.lean.target = 0.0
        held = Clock.get_time() - self._press_t

        if self._dragging:
            lx, ly, lt = self._last
            dt = max(Clock.get_time() - lt, 1 / 60.0)
            self.poo.release((touch.x - lx) / dt, (touch.y - ly) / dt)
        elif held > LONG_PRESS:
            self.poo.long_press(*touch.pos)
        self._dragging = False
        return True

    def _tick(self, dt):
        self.poo.body_h = self.view.h      # so touch zones match what is drawn
        self.poo.update(dt)
        self.view.sync()

    def request_overlay(self):
        """
        Walk her through the two settings Android requires, one at a time,
        rather than dumping her into a settings screen with no explanation.
        """
        try:
            from jnius import autoclass
            S = autoclass("android.provider.Settings")
            Uri = autoclass("android.net.Uri")
            Intent = autoclass("android.content.Intent")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            ctx = act.getApplicationContext()
            pkg = ctx.getPackageName()

            # 1. permission to draw on top of other apps
            if not S.canDrawOverlays(ctx):
                self.status.text = ("Find Poo in the list, turn it ON, "
                                    "then come back and tap again")
                act.startActivity(Intent(S.ACTION_MANAGE_OVERLAY_PERMISSION,
                                         Uri.parse("package:" + pkg)))
                return

            # 2. Samsung kills background services hard; without this she stops
            #    listening for the shake after a while
            if not self._battery_ok(ctx, pkg):
                self.status.text = ("One more: set Poo's battery to "
                                    "Unrestricted so she can stay with you")
                try:
                    i = Intent(S.ACTION_APPLICATION_DETAILS_SETTINGS,
                               Uri.parse("package:" + pkg))
                    act.startActivity(i)
                except Exception:
                    pass
                self._battery_prompted = True
                return

            autoclass(pkg + ".ServiceFloatpoo").start(act, "")
            self.status.text = ("Poo is out. Swipe her off the edge to tuck her "
                                "away, shake to call her back")
        except Exception as exc:
            self.status.text = "That only works on the phone"
            print("overlay:", exc)

    def _battery_ok(self, ctx, pkg):
        """True once she is exempt from battery optimisation (or we already asked)."""
        if getattr(self, "_battery_prompted", False):
            return True          # only nag once; she may have chosen to skip it
        try:
            from jnius import autoclass
            Context = autoclass("android.content.Context")
            pm = ctx.getSystemService(Context.POWER_SERVICE)
            return bool(pm.isIgnoringBatteryOptimizations(pkg))
        except Exception:
            return True          # older Android, or unavailable - do not block


class PooApp(App):
    def build(self):
        Window.clearcolor = (0.07, 0.06, 0.11, 1)
        return Root()

    def on_pause(self):
        self.root.poo.memory.save()
        return True

    def on_stop(self):
        self.root.poo.memory.save()


if __name__ == "__main__":
    PooApp().run()
