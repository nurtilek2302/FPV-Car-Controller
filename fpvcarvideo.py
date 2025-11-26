# FPV Kivy Controller and Video Receiver
# Требуется: pip install kivy Pillow paho-mqtt
# Этот файл содержит: Управление MQTT, Прием UDP-видео и UI.

import sys
import socket
import threading
import time
import io 
import json
from PIL import Image 
import paho.mqtt.client as mqtt 

import kivy
from kivy.app import App
from kivy.uix.widget import Widget
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.graphics import Color, Ellipse, Rectangle
from kivy.core.window import Window
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.uix.image import Image as KivyImage 
from kivy.graphics.texture import Texture
from kivy.properties import NumericProperty
from kivy.metrics import dp
from kivy.logger import Logger 

kivy.require('2.0.0')

# --- Настройки Сети и MQTT ---
STREAM_PORT = 12345 
BUFFER_SIZE = 65536 * 2 
MQTT_BROKER = "broker.hivemq.com"
TOPIC_THROTTLE = "nurtilek_car/throttle"
TOPIC_STEERING = "nurtilek_car/steering"
TOPIC_CONFIG = "nurtilek_car/config_stream" 
HEARTBEAT_INTERVAL = 0.15 

# --- ПРОФИЛИ КАЧЕСТВА ---
QUALITY_PROFILES = {
    'HIGH': {'text': '1. ЛУЧШЕЕ', 'width': 800, 'height': 600, 'framerate': 25, 'quality': 50},
    'GOOD': {'text': '2. СРЕДНЕЕ', 'width': 640, 'height': 480, 'framerate': 20, 'quality': 40},
    'MEDIUM': {'text': '3. ЗАТВОРКА', 'width': 480, 'height': 280, 'framerate': 10, 'quality': 20},
    'LOW': {'text': '4. ЭКСТРЕННОЕ', 'width': 220, 'height': 120, 'framerate': 10, 'quality': 20}
}


# --- Настройка MQTT ---
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
try:
    mqtt_client.connect(MQTT_BROKER, 1883, 60)
    mqtt_client.loop_start()
    Logger.info("[MQTT] Connected.")
except Exception as e:
    Logger.error(f"[MQTT] Ошибка подключения: {e}")
    mqtt_client = None


class FPVVideoReceiver:
    """Класс для прослушивания UDP-сокетов и декодирования JPEG-кадров."""
    def __init__(self, video_widget):
        self.video_widget = video_widget
        self.udp_socket = None
        self.running = True
        self.frame_data = b''
        
        self.setup_udp()
        if self.running:
            self.udp_thread = threading.Thread(target=self._udp_listener, daemon=True)
            self.udp_thread.start()
            Clock.schedule_once(self._update_texture, 0)
        
    def setup_udp(self):
        """Настройка UDP-сокета для приема видео."""
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp_socket.bind(('', STREAM_PORT)) 
            self.udp_socket.settimeout(0.5) 
            Logger.info(f"[UDP] Сокет открыт на порту {STREAM_PORT}")
        except Exception as e:
            Logger.error(f"[UDP] Ошибка настройки сокета: {e}")
            self.running = False
            
    def _udp_listener(self):
        """Поток для непрерывного приема данных."""
        if not self.udp_socket: return
        JPEG_START_MARKER = b'\xff\xd8'
        JPEG_END_MARKER = b'\xff\xd9'
        
        while self.running:
            try:
                data, addr = self.udp_socket.recvfrom(BUFFER_SIZE)
                
                if data.startswith(JPEG_START_MARKER) and data.endswith(JPEG_END_MARKER):
                    self.frame_data = data
            except socket.timeout:
                continue
            except Exception as e:
                if self.running: Logger.error(f"[UDP] Ошибка прослушивания: {e}")
                break

    def _update_texture(self, dt):
        """Обновляет Kivy-текстуру (должен вызываться в главном потоке Kivy)."""
        if self.frame_data:
            try:
                image = Image.open(io.BytesIO(self.frame_data))
                frame = image.convert('RGB') 
                width, height = frame.size
                data = frame.tobytes()
                
                texture = Texture.create(size=(width, height), colorfmt='rgb')
                texture.blit_buffer(data, colorfmt='rgb', bufferfmt='ubyte')
                texture.flip_vertical() 
                self.video_widget.texture = texture
                
                self.frame_data = b''
            except Exception as e:
                Logger.error(f"[Texture] Ошибка обработки кадра: {e}")
                self.frame_data = b'' 

        Clock.schedule_once(self._update_texture, 1.0 / 30.0) 

    def on_stop(self):
        """Корректное завершение потока и сокета."""
        self.running = False
        if hasattr(self, 'udp_thread') and self.udp_thread.is_alive(): 
            self.udp_thread.join(0.5) 
        if self.udp_socket: 
            self.udp_socket.close()
        Clock.unschedule(self._update_texture)


class OneAxisJoystick(Widget):
    """Кастомный виджет джойстика с одной осью (X или Y)."""
    value = NumericProperty(0.0) 

    def __init__(self, axis='y', callback=None, **kwargs):
        self.axis = axis
        self.callback = callback
        self.touch_id = None
        super().__init__(**kwargs)
        self.bind(size=self.on_size)

    def on_size(self, *args):
        self.pad_size = min(self.width, self.height)
        self.knob_size = self.pad_size * 0.4
        self.draw_knob(self.value)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.touch_id = touch.uid
            self.update_knob(touch)
            return True
        return False

    def on_touch_move(self, touch):
        if touch.uid == self.touch_id:
            self.update_knob(touch)
            return True
        return False

    def on_touch_up(self, touch):
        if touch.uid == self.touch_id:
            self.touch_id = None
            self.value = 0.0 
            self.draw_knob(0)
            if self.callback:
                self.callback(0.0) 
            return True
        return False

    def update_knob(self, touch):
        cx, cy = self.center_x, self.center_y
        range_limit = (min(self.width, self.height) - self.knob_size) / 2
        
        if self.axis == 'y':
            dy = touch.y - cy
            value = max(min(dy / range_limit, 1.0), -1.0)
        elif self.axis == 'x':
            dx = touch.x - cx
            value = max(min(dx / range_limit, 1.0), -1.0)
        else:
            value = 0.0
            
        self.value = value
        self.draw_knob(self.value)
        if self.callback:
            self.callback(self.value)

    def draw_knob(self, value):
        if not self.canvas: return
        self.canvas.clear()
        
        pad_size = min(self.width, self.height)
        range_limit = (pad_size - self.knob_size) / 2
        knob_half_size = self.knob_size / 2

        with self.canvas:
            Color(0.2, 0.2, 0.2, 0.3)
            Ellipse(pos=self.pos, size=(pad_size, pad_size))
            
            Color(1, 0, 0, 0.7)
            
            if self.axis == 'y':
                cx = self.center_x - knob_half_size
                cy = self.center_y + value * range_limit - knob_half_size
            elif self.axis == 'x':
                cx = self.center_x + value * range_limit - knob_half_size
                cy = self.center_y - knob_half_size
            else:
                cx = self.center_x - knob_half_size
                cy = self.center_y - knob_half_size
                
            Ellipse(pos=(cx, cy), size=(self.knob_size, self.knob_size))


class FPVControllerApp(App):
    
    def build(self):
        Window.clearcolor = (0.1, 0.1, 0.1, 1)
        self.root_layout = FloatLayout()
        
        # --- ВИДЕО ДИСПЛЕЙ ---
        self.video_display = KivyImage(
            source='https://placehold.co/800x600/000000/FFFFFF?text=FPV+Stream+Waiting', 
            fit_mode='fill', 
            size_hint=(1, 1), 
            pos_hint={'center_x': 0.5, 'center_y': 0.5}
        )
        self.root_layout.add_widget(self.video_display)
        self.video_receiver = FPVVideoReceiver(self.video_display)
        
        # --- ВЕРХНЯЯ ПАНЕЛЬ УПРАВЛЕНИЯ (ТОЛЬКО СЛАЙДЕР ГАЗА) ---
        top_bar = BoxLayout(
            orientation='vertical', 
            size_hint=(0.8, 0.1), # Уменьшенная высота и ширина
            pos_hint={'top': 1, 'center_x': 0.5}, 
            padding=dp(5), 
            spacing=dp(5)
        )
        with top_bar.canvas.before:
            Color(0, 0, 0, 0.7); self.top_rect = Rectangle(size=top_bar.size, pos=top_bar.pos)
        top_bar.bind(size=lambda i, v: setattr(self.top_rect, 'size', v), pos=lambda i, v: setattr(self.top_rect, 'pos', v))

        # Слайдер Макс. Мощности
        power_row = BoxLayout(spacing=dp(10))
        power_row.add_widget(Label(text="МАКС. ГАЗ", size_hint_x=None, width=dp(80), color=(1,1,1,1), font_size='12sp'))
        self.power_slider = Slider(min=0, max=100, value=50, step=5, value_track=True, value_track_color=(0.7, 0.7, 0.7, 1))
        power_row.add_widget(self.power_slider)
        top_bar.add_widget(power_row)
        
        self.root_layout.add_widget(top_bar)
        
        # --- ДЖОЙСТИКИ ---
        screen_w, screen_h = Window.size
        self.pad_size = screen_h * 0.4 
        margin_x = screen_w * 0.05
        # Размещаем джойстики под верхней панелью
        joystick_y = dp(70) 

        self.throttle = OneAxisJoystick(axis='y', callback=self.on_throttle_move, size_hint=(None, None), size=(self.pad_size, self.pad_size), pos=(margin_x, joystick_y))
        self.steering = OneAxisJoystick(axis='x', callback=self.on_steering_move, size_hint=(None, None), size=(self.pad_size, self.pad_size), pos=(screen_w - self.pad_size - margin_x, joystick_y))
        self.root_layout.add_widget(self.throttle)
        self.root_layout.add_widget(self.steering)
        self.last_raw_steering_value = 0.0
        
        # --- Кнопки-переключатели (Нижняя часть) ---
        
        # Кнопка НАСТРОЙКИ (объединяет Триммер и Масштаб Видео)
        self.settings_toggle_btn = Button(
            text="НАСТРОЙКИ", # Переименовано
            size_hint=(0.4, 0.08),
            pos_hint={'x': 0.05, 'y': 0.01},
            background_normal='',
            background_color=(0.1, 0.5, 0.1, 1),
            on_press=self.toggle_settings_ui
        )
        self.root_layout.add_widget(self.settings_toggle_btn)
        
        # Кнопка FPV Quality
        self.quality_toggle_btn = Button(
            text="FPV QUALITY",
            size_hint=(0.4, 0.08),
            pos_hint={'x': 0.55, 'y': 0.01},
            background_normal='',
            background_color=(0.1, 0.1, 0.5, 1),
            on_press=self.toggle_quality_ui
        )
        self.root_layout.add_widget(self.quality_toggle_btn)
        
        # --- КОНТЕЙНЕР НАСТРОЙКИ (Триммер + Масштаб Видео) ---
        self.trimmer_slider = Slider(min=-50, max=50, value=0, step=5, value_track=True, value_track_color=(0.0, 0.5, 0.5, 1))
        self.trimmer_slider.bind(value=self.on_trimmer_change)
        
        self.scale_slider = Slider(min=0.5, max=1.0, value=1.0, step=0.01, value_track=True, value_track_color=(0.5, 0.7, 0.5, 1))
        self.scale_slider.bind(value=self.on_video_scale_change)
        
        self.settings_container = BoxLayout(
            orientation='vertical', 
            size_hint=(0.7, 0.25), 
            pos_hint={'center_x': 0.5, 'center_y': 0.5}, 
            padding=dp(10), 
            spacing=dp(5)
        )
        self.settings_container.add_widget(Label(text="НАСТРОЙКИ УПРАВЛЕНИЯ", color=(1,1,1,1), font_size='16sp'))
        
        # Слайдер Триммера
        trimmer_row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(10))
        trimmer_row.add_widget(Label(text="Триммер Руля:", size_hint_x=None, width=dp(100), color=(1,1,1,1), font_size='12sp'))
        trimmer_row.add_widget(self.trimmer_slider)
        self.settings_container.add_widget(trimmer_row)
        
        # Слайдер Масштаба Видео (ПЕРЕМЕЩЕН СЮДА)
        scale_row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(10))
        scale_row.add_widget(Label(text="Масштаб Видео:", size_hint_x=None, width=dp(100), color=(1,1,1,1), font_size='12sp'))
        scale_row.add_widget(self.scale_slider)
        self.settings_container.add_widget(scale_row)
        
        with self.settings_container.canvas.before:
            Color(0.2, 0.2, 0.2, 0.9); self.settings_rect = Rectangle(size=self.settings_container.size, pos=self.settings_container.pos)
        self.settings_container.bind(size=lambda i, v: setattr(self.settings_rect, 'size', v), pos=lambda i, v: setattr(self.settings_rect, 'pos', v))
        self.settings_visible = False
        
        # --- КОНТЕЙНЕР НАСТРОЕК КАЧЕСТВА ---
        self.quality_container = BoxLayout(orientation='vertical', size_hint=(0.7, 0.2), pos_hint={'center_x': 0.5, 'center_y': 0.5}, padding=dp(10), spacing=dp(5))
        with self.quality_container.canvas.before:
            Color(0.2, 0.2, 0.2, 0.95); self.quality_rect = Rectangle(size=self.quality_container.size, pos=self.quality_container.pos)
        self.quality_container.bind(size=lambda i, v: setattr(self.quality_rect, 'size', v), pos=lambda i, v: setattr(self.quality_rect, 'pos', v))
        
        self.quality_container.add_widget(Label(text="Выбор Качества FPV", size_hint_y=None, height=dp(30), color=(1,1,1,1), font_size='16sp'))
        quality_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(5))
        for key, profile in QUALITY_PROFILES.items():
            btn = Button(
                text=profile['text'], 
                font_size='12sp',
                background_normal='',
                background_color=(0.0, 0.4, 0.7, 1) if key != 'MEDIUM' else (0.7, 0.4, 0.0, 1),
                on_press=lambda instance, k=key: self.send_config_command(k)
            )
            quality_row.add_widget(btn)

        self.quality_container.add_widget(quality_row)
        self.quality_visible = False
        
        if mqtt_client and mqtt_client.is_connected():
            Clock.schedule_interval(self.send_heartbeat, HEARTBEAT_INTERVAL)
        
        return self.root_layout
    
    # --- ЛОГИКА УПРАВЛЕНИЯ И UI ---
    
    def on_video_scale_change(self, instance, value):
        """Обрабатывает изменение слайдера масштаба видео."""
        scaled_value = round(value, 2) 
        self.video_display.size_hint = (value, value)
        Logger.info(f"[UI] Video Scale: {scaled_value}x")
        
    def toggle_quality_ui(self, instance):
        """Показывает/скрывает контейнер настроек качества."""
        if self.quality_visible:
            self.root_layout.remove_widget(self.quality_container)
            instance.background_color = (0.1, 0.1, 0.5, 1)
        else:
            # Убедимся, что контейнер Настроек закрыт
            if self.settings_visible:
                 self.toggle_settings_ui(self.settings_toggle_btn)
            self.root_layout.add_widget(self.quality_container)
            instance.background_color = (0.5, 0.1, 0.5, 1)
            
        self.quality_visible = not self.quality_visible
        
    def toggle_settings_ui(self, instance):
        """Показывает/скрывает контейнер настроек (Триммер + Масштаб)."""
        if self.settings_visible:
            self.root_layout.remove_widget(self.settings_container)
            instance.background_color = (0.1, 0.5, 0.1, 1)
        else:
            # Убедимся, что контейнер Качества FPV закрыт
            if self.quality_visible:
                 self.toggle_quality_ui(self.quality_toggle_btn)
            self.root_layout.add_widget(self.settings_container)
            instance.background_color = (0.5, 0.1, 0.1, 1)
            
        self.settings_visible = not self.settings_visible
    
    def send_config_command(self, profile_key):
        """Отправляет команду на Pi для переключения разрешения/качества и закрывает контейнер."""
        global mqtt_client
        if not mqtt_client or not mqtt_client.is_connected():
            Logger.error(f"MQTT: Failed to send config command: {profile_key}")
            self.toggle_quality_ui(self.quality_toggle_btn)
            return

        profile = QUALITY_PROFILES.get(profile_key)
        if not profile: return
            
        config_payload = json.dumps({
            'width': profile['width'],
            'height': profile['height'],
            'framerate': profile['framerate'],
            'quality': profile['quality']
        })
        
        try:
            mqtt_client.publish(TOPIC_CONFIG, config_payload, qos=1)
            Logger.info(f"[CONFIG] Sent profile: {profile_key}")
            self.toggle_quality_ui(self.quality_toggle_btn) # Закрыть контейнер
        except Exception as e:
            Logger.error(f"Ошибка публикации TOPIC_CONFIG: {e}")

    # --- ЛОГИКА MQTT ОТПРАВКИ (Теперь только логирует, без обновления меток UI) ---

    def send_heartbeat(self, dt):
        """Отправляет текущее состояние газа и руля по MQTT."""
        if not mqtt_client or not mqtt_client.is_connected(): return

        self.on_throttle_move(self.throttle.value)
        self._publish_steering(self.last_raw_steering_value)
        
    def on_trimmer_change(self, instance, value):
        self._publish_steering(self.last_raw_steering_value)

    def _publish_steering(self, raw_value):
        global mqtt_client
        if not mqtt_client or not mqtt_client.is_connected(): return
        
        inverted_value = -raw_value 
        scaled_raw = inverted_value * 100
        trim_value = self.trimmer_slider.value
        inverted_trim = -trim_value 
        final_scaled = int(scaled_raw + inverted_trim)
        final_scaled = max(-100, min(100, final_scaled)) 
        
        # Убрано обновление label_steering
        mqtt_client.publish(TOPIC_STEERING, str(final_scaled))

    def on_throttle_move(self, value):
        global mqtt_client
        if not mqtt_client or not mqtt_client.is_connected(): return
           
        max_power_factor = self.power_slider.value / 100
        scaled = int(value * 100 * max_power_factor)
        
        # Убрано обновление label_throttle
        mqtt_client.publish(TOPIC_THROTTLE, str(scaled))

    def on_steering_move(self, value):
        self.last_raw_steering_value = value
        self._publish_steering(value)

    def on_stop(self):
        """Корректное завершение работы."""
        global mqtt_client
        Clock.unschedule(self.send_heartbeat) 
        self.video_receiver.on_stop() 
        
        if mqtt_client:
            mqtt_client.publish(TOPIC_THROTTLE, "0", qos=1)
            mqtt_client.publish(TOPIC_STEERING, "0", qos=1)
            time.sleep(0.5) 
            mqtt_client.loop_stop()
            mqtt_client.disconnect()

if __name__ == '__main__':
    try:
        FPVControllerApp().run()
    except Exception as e:
        Logger.critical(f"Критическая ошибка запуска приложения: {e}")
        sys.exit(1)