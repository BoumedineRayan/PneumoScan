import time
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForImageTextToText, BitsAndBytesConfig

MODEL_ID = "google/medgemma-4b-it"
IMAGE_PATH = "test.png"  # <-- mets ici le chemin d'une radio que tu as en local

# --- Chargement en 4-bit pour tenir dans 8 Go de VRAM ---
print("Chargement de MedGemma en 4-bit sur la 4060...")
t0 = time.time()
bnb = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_quant_type="nf4",
)
processor = AutoProcessor.from_pretrained(MODEL_ID)
model = AutoModelForImageTextToText.from_pretrained(
    MODEL_ID,
    quantization_config=bnb,
    device_map="auto",
).eval()
print(f"Modèle chargé en {time.time() - t0:.1f}s")
print(f"VRAM utilisée : {torch.cuda.memory_allocated()/1e9:.2f} Go")

PROMPT = """Analyze this frontal chest X-ray. Return only valid JSON:
{"image_quality":"good|limited|poor","predicted_class":"normal|suspected_opacity|uncertain","confidence":0.0,"justification":"short"}"""

def infer(path):
    image = Image.open(path).convert("RGB")
    messages = [
        {"role": "system", "content": [{"type": "text", "text": "You are a cautious educational radiology assistant."}]},
        {"role": "user", "content": [{"type": "text", "text": PROMPT}, {"type": "image", "image": image}]},
    ]
    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt"
    ).to(model.device)
    input_len = inputs["input_ids"].shape[-1]
    t = time.time()
    with torch.inference_mode():
        gen = model.generate(**inputs, max_new_tokens=200, do_sample=False)
    dt = time.time() - t
    out = processor.decode(gen[0][input_len:], skip_special_tokens=True)
    return out, dt

# Première inférence (inclut l'initialisation CUDA, souvent plus lente)
out1, dt1 = infer(IMAGE_PATH)
print(f"\n--- Inférence 1 : {dt1:.1f}s (inclut l'init CUDA) ---")
print(out1)

# Deuxième et troisième : la vraie latence en régime établi
_, dt2 = infer(IMAGE_PATH)
_, dt3 = infer(IMAGE_PATH)
print(f"\n--- Inférence 2 : {dt2:.1f}s ---")
print(f"--- Inférence 3 : {dt3:.1f}s ---")
print(f"\nLatence réelle (hors 1ère) : ~{(dt2+dt3)/2:.1f}s")