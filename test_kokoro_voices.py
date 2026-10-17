"""Manual synthetic speech demo. Not part of offline automated tests."""
from pathlib import Path


def main():
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline
    output = Path("Assets/Voice/Samples")
    output.mkdir(parents=True, exist_ok=True)

    text = (
        "I am Seraphix, guardian of knowledge and imagination. "
        "Every universe begins with a spark, and together, "
        "we shall give yours life."
    )

    print("Loading Kokoro...")
    pipeline = KPipeline(lang_code="a")

    for voice in ["af_bella", "af_nicole", "af_heart"]:
        print(f"Generating {voice}...", flush=True)
        chunks = []

        for _, _, audio in pipeline(text, voice=voice, speed=0.9):
            chunks.append(audio.cpu().numpy())

        if chunks:
            filename = output / f"seraphix_{voice}.wav"
            sf.write(str(filename), np.concatenate(chunks), 24000)
            print(f"Saved: {filename}")

    print("Voice samples complete!")


if __name__ == "__main__":
    main()
