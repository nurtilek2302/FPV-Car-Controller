# Файл конфигурации для Buildozer
[app]

# (string) Title of your application
title = FPV Car Controller (Single Screen)
# (string) Package name
package.name = fpvcontroller_standard
# (string) Package domain (used to enforce unique app ID)
package.domain = com.nurtilek
# (list) Application requirements
requirements = python3,kivy==2.3.0,pillow,paho-mqtt
# (string) Main script used for execution (Адаптировано под ваш файл!)
source.main = fpvcarvideo.py 

# --- Настройки Android ---
# (int) Android SDK target version
android.api = 33
# (string) Minimum Android SDK version
android.minapi = 21
# (list) Permissions (Важно для FPV)
android.permissions = INTERNET, WAKE_LOCK, ACCESS_NETWORK_STATE
# (bool) Enable/disable internet access
android.allow_internet = True

# (list) Supported orientations (Portrait - для обычного телефона)
orientation = portrait

[buildozer]
log_level = 2
