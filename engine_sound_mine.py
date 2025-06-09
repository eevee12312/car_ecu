# engine_sound.py
import numpy as np
import sounddevice as sd
import soundfile as sf
import threading
import time

class EngineSoundSimulator:
    def __init__(self, grain_path, sample_rate=44100):
        self.sample_rate = sample_rate

        # Load engine grain
        audio_data, sr = sf.read(grain_path)
        if sr != sample_rate:
            raise ValueError(f"Sample rate mismatch: expected {sample_rate}, got {sr}")
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)  # Convert stereo to mono

        self.grain_duration = 0.1  # 100 ms grain
        self.grain = audio_data[:int(self.grain_duration * sample_rate)]

        # Fade in/out (20 ms) to avoid clicks
        self.fade_samples = int(0.02 * sample_rate)
        window = np.hanning(self.fade_samples * 2)
        self.fade_in = window[self.fade_samples:]
        self.fade_out = window[:self.fade_samples]

        # RPM range and pitch settings
        self.RPM_IDLE = 900
        self.RPM_MAX = 8000
        self.min_pitch = 0.6
        self.max_pitch = 2.2

        self.prev_tail = np.zeros(self.fade_samples)
        self.current_rpm = self.RPM_IDLE
        self.running = False

        # Audio output stream
        self.stream = sd.OutputStream(samplerate=sample_rate, channels=1)
        self.stream.start()

        self.thread = threading.Thread(target=self._play_loop)
        self.thread.daemon = True

    def pitch_shift(self, grain, factor):
        if factor <= 0:
            return grain
        indices = np.arange(0, len(grain), 1 / factor)
        indices = indices[indices < len(grain)]
        return np.interp(indices, np.arange(len(grain)), grain)

    def update_rpm(self, rpm):
        self.current_rpm = np.clip(rpm, self.RPM_IDLE, self.RPM_MAX)

    def _play_loop(self):
        while self.running:
            rpm_norm = (self.current_rpm - self.RPM_IDLE) / (self.RPM_MAX - self.RPM_IDLE)
            pitch_factor = self.min_pitch * (self.max_pitch / self.min_pitch) ** (1 - rpm_norm)

            pitched = self.pitch_shift(self.grain, pitch_factor)
            if len(pitched) < 2 * self.fade_samples:
                continue  # Too short, skip this grain

            # Apply crossfade
            pitched[:self.fade_samples] *= self.fade_in
            pitched[-self.fade_samples:] *= self.fade_out

            output = np.copy(pitched)
            output[:self.fade_samples] += self.prev_tail * (1 - self.fade_in)
            self.prev_tail = pitched[-self.fade_samples:]

            self.stream.write(output.astype(np.float32).reshape(-1, 1))


            time.sleep(0.001)  # Control loop timing

    def start(self):
        if not self.running:
            self.running = True
            self.thread.start()

    def stop(self):
        self.running = False
        self.thread.join()
        self.stream.stop()
        self.stream.close()

def play_turbo(path):
    audio, sr = sf.read(path)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    sd.play(audio, sr)
    sd.wait()






import numpy as np
import sounddevice as sd
import soundfile as sf
import time
from scipy.signal import butter, lfilter

# Constants
SAMPLE_RATE = 44100
CHANNELS = 1
BUFFER_SIZE = 1024

FIRING_ORDER = [0, 3, 1, 4, 2, 5]
NUM_CYLINDERS = 6
MAX_RPM = 7000
MIN_RPM = 700
BURST_DURATION = 0.02

def bandpass_filter(data, lowcut, highcut, fs, order=2):
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype='band')
    y = lfilter(b, a, data)
    return y

def generate_combustion_burst(duration=BURST_DURATION, sample_rate=SAMPLE_RATE):
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    noise = np.random.randn(len(t))
    envelope = np.exp(-t * 40) * (1 - np.exp(-t * 200))
    burst = noise * envelope
    burst_filtered = bandpass_filter(burst, 1200, 1800, sample_rate)
    burst_filtered /= np.max(np.abs(burst_filtered))
    return burst_filtered

def generate_intake_exhaust(duration, sample_rate=SAMPLE_RATE, rpm=1000):
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    base_freq = rpm / 60 * 30
    sound = np.sin(2 * np.pi * base_freq * t)
    sound += 0.3 * np.sin(2 * np.pi * base_freq * 2 * t)
    sound *= (0.5 + 0.5 * np.sin(2 * np.pi * 2 * t))
    sound /= np.max(np.abs(sound))
    return sound * 0.2

def pitch_shift(signal, semitones):
    factor = 2 ** (semitones / 12)
    indices = np.arange(0, len(signal), factor)
    indices = indices[indices < len(signal)].astype(int)
    return signal[indices]

class OtherEngineSoundSimulator:
    def __init__(self):
        self.base_burst = generate_combustion_burst()
        self.rpm = 800
        self.target_rpm = 800
        self.rpm_step = 100
        self.last_firing_time = 0
        self.next_cylinder_index = 0

    def set_rpm(self, rpm):
        # Clamp RPM to range
        self.target_rpm = max(MIN_RPM, min(MAX_RPM, rpm))

    def firing_interval(self, rpm):
        return 60 / (rpm * (NUM_CYLINDERS / 2))

    def audio_callback(self, outdata, frames, time_info, status):
        samples = np.zeros(frames, dtype=np.float32)
        now = time.perf_counter()

        # Smooth RPM towards target RPM
        if self.rpm < self.target_rpm:
            self.rpm += self.rpm_step * frames / SAMPLE_RATE
            if self.rpm > self.target_rpm:
                self.rpm = self.target_rpm
        elif self.rpm > self.target_rpm:
            self.rpm -= self.rpm_step * frames / SAMPLE_RATE
            if self.rpm < self.target_rpm:
                self.rpm = self.target_rpm

        interval = self.firing_interval(self.rpm)
        dt = 1 / SAMPLE_RATE

        intake_sound = generate_intake_exhaust(frames / SAMPLE_RATE, rpm=self.rpm)
        samples += intake_sound

        t = self.last_firing_time
        for i in range(frames):
            if t <= now + i * dt:
                semitones = np.interp(self.rpm, [MIN_RPM, MAX_RPM], [0, 12])
                burst = pitch_shift(self.base_burst, semitones)
                burst_len = len(burst)
                end_idx = i + burst_len
                if end_idx > frames:
                    burst = burst[:frames - i]
                    end_idx = frames
                samples[i:end_idx] += burst * 0.4
                t += interval
                self.next_cylinder_index = (self.next_cylinder_index + 1) % NUM_CYLINDERS
            else:
                t += dt

        self.last_firing_time = t
        max_val = np.max(np.abs(samples))
        if max_val > 1.0:
            samples /= max_val

        outdata[:] = samples.reshape(-1, 1)

    def start(self):
        self.last_firing_time = time.perf_counter()
        self.next_cylinder_index = 0
        self.rpm = self.target_rpm

        self.stream = sd.OutputStream(
            channels=CHANNELS,
            callback=self.audio_callback,
            samplerate=SAMPLE_RATE,
            blocksize=BUFFER_SIZE
        )
        self.stream.start()

    def stop(self):
        self.stream.stop()
        self.stream.close()
