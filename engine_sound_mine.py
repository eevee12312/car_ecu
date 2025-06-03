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