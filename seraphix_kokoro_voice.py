"""Seraphix v2.7.1 Kokoro af_nicole voice with delivery presets."""
import argparse
import sys
import numpy as np
import sounddevice as sd
from kokoro import KPipeline

VOICE = 'af_nicole'
SAMPLE_RATE = 24000
SPEEDS = {'Calm': 0.86, 'Warm': 0.93, 'Dramatic': 0.80}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--style', choices=tuple(SPEEDS), default='Warm')
    args = parser.parse_args()
    text = sys.stdin.read().strip()[:900]
    if not text:
        return
    pipeline = KPipeline(lang_code='a')
    for _, _, audio in pipeline(text, voice=VOICE, speed=SPEEDS[args.style]):
        samples = np.asarray(audio.cpu().numpy(), dtype=np.float32)
        if samples.size:
            sd.play(samples, samplerate=SAMPLE_RATE, blocking=True)
    sd.stop()


if __name__ == '__main__':
    main()
