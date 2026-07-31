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

# Restarting after Android kills the service is handled in code, by calling
# setAutoRestartService(True) in service/floatpoo.py. Do not add a :sticky
# suffix here - older python-for-android splits this on the first colon only
# and would treat "service/floatpoo.py:sticky" as the filename.
android.services = floatpoo:service/floatpoo.py

android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
