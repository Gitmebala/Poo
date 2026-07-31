[app]
title = Poo
package.name = poo
package.domain = org.michael.poo

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 0.1

requirements = python3,kivy,plyer,pyjnius

orientation = portrait
fullscreen = 1

icon.filename = %(source.dir)s/assets/icon.png

android.permissions = VIBRATE,SYSTEM_ALERT_WINDOW

# :sticky asks Android to restart the service if it gets killed, which is what
# keeps her listening for a shake after she has been tucked away
android.services = floatpoo:service/floatpoo.py:sticky

android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
