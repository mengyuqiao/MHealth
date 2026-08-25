"""
VLM Service — Qwen2.5-VL-7B-Instruct
Loaded once at startup on the configured GPU.
Exposes two functions:
  analyze_food(image_path)      -> {"calories": int, "description": str}
  analyze_medication(image_path) -> {"med_name": str, "dosage": str}

De-identification approach follows HHS HIPAA guidance:
https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html
Only medication name and strength are extracted. All other PHI is discarded.
"""

import os
import torch
import logging
from PIL import Image
from config import Config

logger = logging.getLogger(__name__)

_model = None
_processor = None


def _load_model():
    global _model, _processor
    if _model is not None:
        return

    from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
    from qwen_vl_utils import process_vision_info

    gpu_id = Config.VLM_GPU_ID
    model_id = Config.VLM_MODEL

    logger.info(f"Loading {model_id} on GPU {gpu_id} ...")

    _processor = AutoProcessor.from_pretrained(model_id)
    _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_id,
        torch_dtype=torch.float16,
        device_map=f"cuda:{gpu_id}",
    )
    _model.eval()
    logger.info("VLM loaded and ready.")


def _run_inference(image_path: str, prompt: str) -> str:
    """Send one image + prompt through the model, return text response."""
    from qwen_vl_utils import process_vision_info

    _load_model()

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": f"file://{os.path.abspath(image_path)}"},
                {"type": "text",  "text": prompt},
            ],
        }
    ]

    text_input = _processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)

    inputs = _processor(
        text=[text_input],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )
    inputs = inputs.to(f"cuda:{Config.VLM_GPU_ID}")

    with torch.no_grad():
        output_ids = _model.generate(
            **inputs,
            max_new_tokens=64,  # short output — we only need name + strength
            do_sample=False,
        )

    trimmed = [
        out[len(inp):] for inp, out in zip(inputs.input_ids, output_ids)
    ]
    response = _processor.batch_decode(
        trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )[0]
    return response.strip()


def analyze_food(image_path: str) -> dict:
    """
    Estimate calories and describe food from a photo.
    Returns: {"calories": int, "description": str, "error": str|None}
    """
    prompt = (
        "Look at this food photo. Identify what food or drink is shown and estimate "
        "the total caloric content for the portion visible. "
        "Respond in this exact format (no extra text):\n"
        "CALORIES: <number>\n"
        "FOOD: <short description of what you see>\n"
        "If you cannot identify the food, respond:\n"
        "CALORIES: 0\n"
        "FOOD: Unable to identify"
    )

    try:
        raw = _run_inference(image_path, prompt)
        lines = {line.split(":")[0].strip(): ":".join(line.split(":")[1:]).strip()
                 for line in raw.splitlines() if ":" in line}
        calories = int(''.join(filter(str.isdigit, lines.get("CALORIES", "0"))) or 0)
        description = lines.get("FOOD", "Food item")
        return {"calories": calories, "description": description, "error": None}
    except Exception as e:
        logger.error(f"Food analysis failed: {e}")
        return {"calories": 0, "description": "Could not analyze image", "error": str(e)}


def analyze_medication(image_path: str) -> dict:
    """
    Extract ONLY medication name and strength from a bottle/package photo.
    All other information (patient name, address, prescriber, pharmacy,
    prescription number, dates, barcodes, QR codes) is intentionally
    ignored and never stored, per HHS HIPAA de-identification guidance:
    https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html

    Returns: {"med_name": str, "dosage": str, "error": str|None}
    """
    prompt = (
        "You are reading a medication label for a medical tracking app. "
        "Your task is to extract ONLY two pieces of information:\n"
        "1. The medication name (drug name only, e.g. Oxycodone, Tylenol, Metformin)\n"
        "2. The strength (e.g. 5 mg, 500 mg, 10 mg/5 mL)\n\n"
        "Do NOT extract or output any of the following — ignore them completely:\n"
        "- Patient name, address, date of birth\n"
        "- Prescriber name or address\n"
        "- Pharmacy name, address, or phone number\n"
        "- Prescription number or refill information\n"
        "- Dispensing date or expiration date\n"
        "- Barcode, QR code, or lot number\n"
        "- Dosing instructions or warnings\n\n"
        "Respond in this exact format (no extra text):\n"
        "MED_NAME: <medication name only>\n"
        "STRENGTH: <strength only>\n\n"
        "If you cannot read the label clearly, respond:\n"
        "MED_NAME: Unknown\n"
        "STRENGTH: Unknown"
    )

    try:
        raw = _run_inference(image_path, prompt)
        lines = {line.split(":")[0].strip(): ":".join(line.split(":")[1:]).strip()
                 for line in raw.splitlines() if ":" in line}
        med_name = lines.get("MED_NAME", "Unknown").strip()
        dosage   = lines.get("STRENGTH", "").strip()

        # Safety check: if output looks like it contains PHI (name-like patterns,
        # numbers that look like phone/rx numbers), fall back to Unknown
        import re
        phi_patterns = [
            r'\b\d{10}\b',           # phone numbers
            r'\bRx\s*#?\s*\d+\b',   # prescription numbers
            r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',  # dates
        ]
        combined = f"{med_name} {dosage}"
        for pattern in phi_patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                logger.warning(f"PHI pattern detected in VLM output, redacting: {combined}")
                med_name = "Unknown"
                dosage = ""
                break

        return {
            "med_name": med_name,
            "dosage":   dosage,
            "instructions": "",   # intentionally empty — not collected per de-id policy
            "error": None,
        }
    except Exception as e:
        logger.error(f"Medication analysis failed: {e}")
        return {"med_name": "Unknown", "dosage": "", "instructions": "", "error": str(e)}


def warmup():
    """Pre-load the model at app startup so first request isn't slow."""
    try:
        _load_model()
    except Exception as e:
        logger.error(f"VLM warmup failed: {e}")