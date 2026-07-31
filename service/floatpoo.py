"""
Poo's floating bubble - a python-for-android Service that draws her over
other apps using raw Android views through pyjnius.

Summoning model (chosen deliberately):
  * fling her off a screen edge  -> she HIDES, the service keeps running
  * shake the phone              -> she comes back, from anywhere

That means the service must survive in the background, which is the hard part
on modern Android. Two things help: the service is sticky (Android restarts it
if it is killed), and the overlay window is kept registered. On Samsung the
user may still need to exempt Poo from battery optimisation for her to last.

Everything here is best-effort: any failure stops the service cleanly rather
than taking the main app down with it.
"""
import math
import os
import threading
import time

from jnius import PythonJavaClass, autoclass, cast, java_method

ASSET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "assets", "poo", "p_neutral.png")

SWIPE_DISMISS_VELOCITY = 1700.0
EDGE_MARGIN = 0.16
SHAKE_THRESHOLD = 24.0        # summed |delta| across axes
SHAKE_COOLDOWN = 1.2

PythonService = autoclass("org.kivy.android.PythonService")
Context = autoclass("android.content.Context")
LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
WindowManagerCls = autoclass("android.view.WindowManager")
ImageView = autoclass("android.widget.ImageView")
PixelFormat = autoclass("android.graphics.PixelFormat")
Gravity = autoclass("android.view.Gravity")
BitmapFactory = autoclass("android.graphics.BitmapFactory")
BuildVersion = autoclass("android.os.Build$VERSION")
Looper = autoclass("android.os.Looper")
Handler = autoclass("android.os.Handler")
DisplayMetrics = autoclass("android.util.DisplayMetrics")
SensorManager = autoclass("android.hardware.SensorManager")
Sensor = autoclass("android.hardware.Sensor")


class Runnable(PythonJavaClass):
    __javainterfaces__ = ["java/lang/Runnable"]
    __javacontext__ = "app"

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    @java_method("()V")
    def run(self):
        try:
            self.fn()
        except Exception as exc:
            print("poo runnable:", exc)


class TouchListener(PythonJavaClass):
    __javainterfaces__ = ["android/view/View$OnTouchListener"]
    __javacontext__ = "app"

    def __init__(self, bubble):
        super().__init__()
        self.bubble = bubble

    @java_method("(Landroid/view/View;Landroid/view/MotionEvent;)Z")
    def onTouch(self, view, event):
        try:
            self.bubble.on_touch(event)
        except Exception as exc:
            print("poo touch:", exc)
        return True


class ShakeListener(PythonJavaClass):
    """Watches the accelerometer so she can be summoned while hidden."""
    __javainterfaces__ = ["android/hardware/SensorEventListener"]
    __javacontext__ = "app"

    def __init__(self, bubble):
        super().__init__()
        self.bubble = bubble
        self.prev = None
        self.last_fire = 0.0

    @java_method("(Landroid/hardware/SensorEvent;)V")
    def onSensorChanged(self, event):
        try:
            vals = event.values
            x, y, z = vals[0], vals[1], vals[2]
            if self.prev is not None:
                px, py, pz = self.prev
                jolt = abs(x - px) + abs(y - py) + abs(z - pz)
                now = time.time()
                if jolt > SHAKE_THRESHOLD and now - self.last_fire > SHAKE_COOLDOWN:
                    self.last_fire = now
                    self.bubble.on_shake()
            self.prev = (x, y, z)
        except Exception as exc:
            print("poo shake:", exc)

    @java_method("(Landroid/hardware/Sensor;I)V")
    def onAccuracyChanged(self, sensor, accuracy):
        pass


class PooBubble:
    ACTION_DOWN, ACTION_UP, ACTION_MOVE = 0, 1, 2

    def __init__(self, service):
        self.service = service
        self.handler = Handler(Looper.getMainLooper())
        self.wm = cast(WindowManagerCls, service.getSystemService(Context.WINDOW_SERVICE))

        metrics = DisplayMetrics()
        self.wm.getDefaultDisplay().getMetrics(metrics)
        self.sw, self.sh = metrics.widthPixels, metrics.heightPixels

        self.view = ImageView(service)
        bmp = BitmapFactory.decodeFile(ASSET)
        if bmp is not None:
            self.view.setImageBitmap(bmp)

        overlay = (LayoutParams.TYPE_APPLICATION_OVERLAY
                   if BuildVersion.SDK_INT >= 26 else LayoutParams.TYPE_PHONE)
        self.params = LayoutParams(
            int(self.sw * 0.34), int(self.sw * 0.34 / 0.886),
            overlay,
            LayoutParams.FLAG_NOT_FOCUSABLE | LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT)
        self.params.gravity = Gravity.TOP | Gravity.LEFT
        self.params.x = int(self.sw * 0.62)
        self.params.y = int(self.sh * 0.30)
        self.base_y = self.params.y

        self.view.setOnTouchListener(TouchListener(self))
        self.wm.addView(self.view, self.params)

        self.visible = True
        self.alive = True
        self.dragging = False
        self._down = (0, 0)
        self._down_params = (0, 0)
        self._last_move = (0, 0, 0.0)
        self._phase = 0.0

        self._init_sensor()
        self._start_idle()

    # ---------------------------------------------------------------- sensor
    def _init_sensor(self):
        try:
            self.sm = cast(SensorManager,
                           self.service.getSystemService(Context.SENSOR_SERVICE))
            accel = self.sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
            self.shake = ShakeListener(self)
            self.sm.registerListener(self.shake, accel,
                                     SensorManager.SENSOR_DELAY_UI)
        except Exception as exc:
            print("poo sensor unavailable:", exc)
            self.sm = None

    def on_shake(self):
        if not self.alive:
            return
        if not self.visible:
            self._post(self.show)
        else:
            self._post(lambda: self._hop(26))

    # ------------------------------------------------------------ show/hide
    def _post(self, fn):
        self.handler.post(Runnable(fn))

    def show(self):
        if self.visible or not self.alive:
            return
        self.params.x = int(self.sw * 0.62)
        self.params.y = int(self.sh * 0.30)
        self.base_y = self.params.y
        try:
            self.wm.addView(self.view, self.params)
            self.visible = True
        except Exception as exc:
            print("poo show:", exc)

    def hide(self):
        """She is tucked away but the service keeps listening for a shake."""
        if not self.visible:
            return
        try:
            self.wm.removeView(self.view)
        except Exception as exc:
            print("poo hide:", exc)
        self.visible = False

    def _hop(self, px):
        self.params.y = self.base_y - px
        self._apply()
        threading.Timer(0.12, lambda: self._post(self._settle)).start()

    def _settle(self):
        self.params.y = self.base_y
        self._apply()

    def _apply(self):
        if not self.visible:
            return
        try:
            self.wm.updateViewLayout(self.view, self.params)
        except Exception:
            pass

    # ---------------------------------------------------------------- touch
    def on_touch(self, event):
        action = event.getAction()
        rx, ry = event.getRawX(), event.getRawY()

        if action == self.ACTION_DOWN:
            self._down = (rx, ry)
            self._down_params = (self.params.x, self.params.y)
            self._last_move = (rx, ry, time.time())
            self.dragging = False

        elif action == self.ACTION_MOVE:
            dx, dy = rx - self._down[0], ry - self._down[1]
            if abs(dx) > 10 or abs(dy) > 10:
                self.dragging = True
            self.params.x = int(self._down_params[0] + dx)
            self.params.y = int(self._down_params[1] + dy)
            self.base_y = self.params.y
            self._last_move = (rx, ry, time.time())
            self._post(self._apply)

        elif action == self.ACTION_UP:
            lx, _ly, lt = self._last_move
            dt = max(time.time() - lt, 1 / 60.0)
            vx = (rx - lx) / dt
            w = max(self.view.getWidth(), 1)
            off_l = self.params.x < -w * EDGE_MARGIN
            off_r = self.params.x > self.sw - w * (1 - EDGE_MARGIN)
            if self.dragging and (off_l or off_r or abs(vx) > SWIPE_DISMISS_VELOCITY):
                self._post(self.hide)
            elif not self.dragging:
                self._post(lambda: self._hop(30))

    # ----------------------------------------------------------- idle motion
    def _start_idle(self):
        def loop():
            while self.alive:
                time.sleep(1 / 30.0)
                if not self.visible or self.dragging:
                    continue
                self._phase += 1 / 30.0
                self.params.y = int(self.base_y + math.sin(self._phase * 1.6) * 7)
                self._post(self._apply)
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self.alive = False
        try:
            if self.sm is not None:
                self.sm.unregisterListener(self.shake)
        except Exception:
            pass
        self.hide()


def main():
    try:
        service = PythonService.mService
    except Exception as exc:
        print("poo: no service context:", exc)
        return

    try:
        service.setAutoRestartService(True)     # come back if Android kills us
    except Exception:
        pass

    try:
        bubble = PooBubble(service)
    except Exception as exc:
        print("Poo floating bubble failed to start:", exc)
        try:
            service.stopSelf()
        except Exception:
            pass
        return

    while bubble.alive:
        time.sleep(1)


if __name__ == "__main__":
    main()
