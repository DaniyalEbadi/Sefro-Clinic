"""Face analysis backends.

Local backend: MediaPipe Face Mesh landmarks (468) drive geometry-based scoring,
OpenCV LAB skin classification, Canny fine-line probing and heuristic concern
detection. Zero faces, multiple faces and pipeline failures raise
``FaceAnalyzerError`` (HTTP 400, Persian default message).

External backend: HTTP POST to FACE_ANALYZER_EXTERNAL_API_URL (30s timeout).

All suggestion/attribute generation lives here so both backends share one
implementation (no duplicated advice tables or score assembly).
"""

import base64
import io
import json
import math
import re
import statistics
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from PIL import Image, ImageFilter, ImageStat

from Sefro_Clinic.validators import TEXT_SANITIZERS

from ..exceptions import AnalyzerError, FaceAnalyzerError

try:
    import cv2
except ImportError:  # pragma: no cover - optional (headless/contrib wheel conflicts)
    cv2 = None

try:
    import mediapipe as mp
except ImportError:  # pragma: no cover - no wheel for py3.13
    mp = None


# --- tunable constants -------------------------------------------------------
# overall = weighted mean of the four component scores (module-level, configurable).
OVERALL_WEIGHTS = {
    'symmetry': 0.35,
    'clarity': 0.30,
    'youth': 0.15,
    'harmony': 0.20,
}
HARMONY_WEIGHTS = {'symmetry': 0.50, 'thirds': 0.25, 'fifths': 0.25}
CLARITY_BASE = 9.5
CLARITY_TEXTURE_DIVISOR = 6.0
CLARITY_FLOOR = 4.0
EXTERNAL_TIMEOUT_SECONDS = 30
CONCERN_FLAG_THRESHOLD = 0.45
YOUTH_EDGE_WEIGHT = 0.6
YOUTH_FIRMNESS_WEIGHT = 0.4
YOUTH_EDGE_PENALTY = 6.0
MODEL_VERSION_PREFIX = 'sefro-local-v1'

# MediaPipe Face Mesh indices (468-landmark topology).
FOREHEAD_TOP, CHIN = 10, 152
GLABELLA, NOSE_BASE = 151, 2
CHEEK_LEFT, CHEEK_RIGHT = 234, 454
JAW_LEFT, JAW_RIGHT = 172, 397
FOREHEAD_LEFT, FOREHEAD_RIGHT = 54, 284
EYE_L_OUTER, EYE_L_INNER = 33, 133
EYE_R_INNER, EYE_R_OUTER = 362, 263
EYE_L_TOP, EYE_L_BOTTOM = 159, 145
EYE_R_TOP, EYE_R_BOTTOM = 386, 374
UPPER_LIP, LOWER_LIP = 13, 14
MOUTH_LEFT, MOUTH_RIGHT = 61, 291
CHEEK_SAMPLE_LEFT, CHEEK_SAMPLE_RIGHT = 50, 280

# Left/right landmark pairs used for symmetry measurement.
SYMMETRY_PAIRS = (
    (33, 263), (58, 288), (133, 362), (159, 386), (144, 373),
    (36, 246), (49, 279), (172, 397), (234, 454), (103, 332),
    (54, 284), (127, 356), (205, 425),
)

CONCERN_NAMES = (
    'acne', 'hyperpigmentation', 'redness', 'dark_circles', 'fine_lines',
    'dryness', 'oiliness', 'enlarged_pores', 'dullness',
)

FACE_SHAPE_ADVICE = {
    'oval': {
        'makeup': 'Soft contour along the cheekbones keeps your balanced proportions defined without heaviness.',
        'hairstyle': 'Layers starting at the jawline will complement your oval face shape.',
        'skincare': 'Even proportions respond well to basics: daily sunscreen and a gentle cleanser.',
    },
    'round': {
        'makeup': 'Apply contour beneath the cheekbones and along the jawline to add definition.',
        'hairstyle': 'Long layers with volume at the crown will elongate a round face.',
        'skincare': 'Focus on lightweight, non-comedogenic hydration to keep the T-zone clear.',
    },
    'square': {
        'makeup': 'Soften the jawline with contour angled from the ears toward the mouth corner.',
        'hairstyle': 'Side-swept or wispy bangs soften a strong square jawline.',
        'skincare': 'Use a gentle exfoliant two to three times a week to keep the forehead and jaw clear.',
    },
    'heart': {
        'makeup': 'Balance a wider forehead with contour at the temples and a touch of color on the chin.',
        'hairstyle': 'Chin-length bobs or deep side parts balance a heart face\u2019s wider forehead.',
        'skincare': 'Mattify the forehead with a niacinamide serum and keep the cheeks well hydrated.',
    },
    'oblong': {
        'makeup': 'Contour along the hairline and chin to shorten the look of a longer face.',
        'hairstyle': 'Chin-length waves or side parts add width and soften facial length.',
        'skincare': 'Prioritize barrier-supporting hydration; long faces often show dryness first.',
    },
    'diamond': {
        'makeup': 'Highlight the forehead and chin while softly contouring the cheekbones.',
        'hairstyle': 'Side-swept bangs or volume at the jawline flatter a diamond shape.',
        'skincare': 'Keep the cheeks calm with a soothing serum; treat the T-zone separately.',
    },
}

SKIN_CONCERN_ADVICE = {
    'acne': 'Add a salicylic-acid cleanser in the evening and niacinamide in the morning to keep pores clear.',
    'hyperpigmentation': 'Use a vitamin C serum each morning and a retinoid at night to fade dark spots evenly.',
    'redness': 'Switch to fragrance-free products with azelaic acid or centella to calm visible redness.',
    'dark_circles': 'A caffeine eye cream plus consistent sleep hygiene helps brighten under-eye shadows.',
    'fine_lines': 'Introduce retinol slowly at night and wear SPF daily to prevent lines from deepening.',
    'dryness': 'Layer a hyaluronic-acid serum under a ceramide moisturizer and seal with an occlusive at night.',
    'oiliness': 'A lightweight niacinamide serum regulates sebum without stripping the skin.',
    'enlarged_pores': 'A weekly BHA exfoliant plus niacinamide visibly refines pore texture.',
    'dullness': 'A weekly AHA polish and morning vitamin C restore glow to dull skin.',
}


@dataclass
class FaceAnalysisResult:
    overall_score: float
    symmetry_score: float
    skin_clarity_score: float
    youthfulness_score: float
    harmony_score: float
    detected_attributes: dict
    suggestions: list
    raw_output: dict
    model_version: str


class FaceAnalyzerBackend(ABC):
    """Interface every analysis provider must implement."""

    provider = 'local'

    @abstractmethod
    def analyze(self, image_bytes: bytes) -> FaceAnalysisResult:
        raise NotImplementedError


# --- shared helpers ----------------------------------------------------------
def clamp(value, low: float = 0.0, high: float = 10.0) -> float:
    """Clamp a score into [low, high] and round to one decimal."""
    return round(max(low, min(high, float(value))), 1)


def clamp01(value) -> float:
    """Clamp a severity/proportion into [0, 1]."""
    return max(0.0, min(1.0, float(value)))


def sanitize_text(value) -> str:
    """Run a string through TEXT_SANITIZERS, cleaning any offending characters."""
    text = str(value)
    for validator in TEXT_SANITIZERS:
        try:
            validator(text)
        except DjangoValidationError:
            text = text.replace('\x00', '')
            text = re.sub(r'[\ud800-\udfff]', '', text)
    return text


def sanitize_structure(value):
    """Recursively sanitize every string in a JSON-like structure.

    Also converts numpy scalars/arrays and non-finite floats so the result is
    safe for Django's JSONField on any backend.
    """
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {
            (sanitize_text(key) if isinstance(key, str) else key): sanitize_structure(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_structure(item) for item in value]
    if isinstance(value, np.ndarray):
        return sanitize_structure(value.tolist())
    if isinstance(value, np.generic):
        return sanitize_structure(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    return value


def symmetry_score_from_ratio(ratio: float) -> float:
    """Convert a normalized asymmetry ratio into a 0-10 score (0.125 ratio -> 0)."""
    return clamp(10.0 - max(0.0, float(ratio)) * 80.0)


def clarity_from_texture(texture: float) -> float:
    """Map a local texture standard deviation to a 0-10 skin clarity score."""
    return clamp(CLARITY_BASE - max(0.0, float(texture)) / CLARITY_TEXTURE_DIVISOR, CLARITY_FLOOR, CLARITY_BASE)


def assemble_scores(symmetry: float, clarity: float, youth: float, harmony: float) -> dict:
    """Derive the overall score from component scores via OVERALL_WEIGHTS."""
    components = {'symmetry': float(symmetry), 'clarity': float(clarity), 'youth': float(youth), 'harmony': float(harmony)}
    overall = sum(OVERALL_WEIGHTS[key] * components[key] for key in OVERALL_WEIGHTS)
    return {
        'overall': clamp(overall),
        'symmetry': components['symmetry'],
        'clarity': components['clarity'],
        'youth': components['youth'],
        'harmony': components['harmony'],
    }


def classify_face_shape(face_width: float, face_length: float, jaw_width: float, forehead_width: float) -> str:
    """Classify face shape: oval | round | square | heart | oblong | diamond."""
    if face_width <= 0 or face_length <= 0:
        return 'oval'
    ratio = face_length / face_width
    jaw_ratio = jaw_width / face_width
    forehead_ratio = forehead_width / face_width
    if ratio >= 1.45:
        if forehead_ratio - jaw_ratio >= 0.06:
            return 'heart'
        return 'oblong'
    narrow = jaw_ratio <= 0.82 and forehead_ratio <= 0.85
    if ratio < 1.25:
        if jaw_ratio >= 0.93 and forehead_ratio >= 0.90:
            return 'square'
        return 'diamond' if narrow else 'round'
    if jaw_ratio >= 0.95:
        return 'square'
    if forehead_ratio - jaw_ratio >= 0.06:
        return 'heart'
    return 'diamond' if narrow else 'oval'


def classify_eye_shape(aspect_ratio: float) -> str:
    """Classify eye shape from the eye height/width aspect ratio."""
    if aspect_ratio >= 0.48:
        return 'round'
    if aspect_ratio >= 0.33:
        return 'almond'
    return 'hooded'


def classify_lip_fullness(height_width_ratio: float) -> str:
    """Classify lip fullness from the mouth height/width ratio."""
    if height_width_ratio >= 0.42:
        return 'full'
    if height_width_ratio >= 0.30:
        return 'medium'
    return 'thin'


def classify_skin_tone(lightness) -> str:
    """Classify skin tone from OpenCV-scale L* (0-255): fair | light | medium | tan | deep."""
    l_value = float(lightness)
    if l_value >= 175:
        return 'fair'
    if l_value >= 145:
        return 'light'
    if l_value >= 115:
        return 'medium'
    if l_value >= 85:
        return 'tan'
    return 'deep'


def classify_undertone(a_channel, b_channel) -> str:
    """Classify undertone from OpenCV-scale a*/b* (centered at 128): cool | neutral | warm."""
    a_value, b_value = float(a_channel), float(b_channel)
    if b_value >= 155 and a_value >= 140:
        return 'warm'
    if b_value <= 130:
        return 'cool'
    return 'neutral'


def facial_thirds_score(points: list) -> float:
    """Proportionality of the vertical facial thirds (0-1, 1 = perfectly even)."""
    top = points[FOREHEAD_TOP][1]
    brow = points[GLABELLA][1]
    nose = points[NOSE_BASE][1]
    chin = points[CHIN][1]
    t1, t2, t3 = brow - top, nose - brow, chin - nose
    mean = (t1 + t2 + t3) / 3.0
    if mean <= 0:
        return 0.0
    deviation = (abs(t1 - mean) + abs(t2 - mean) + abs(t3 - mean)) / (3.0 * mean)
    return clamp01(1.0 - deviation * 1.5)


def facial_fifths_score(geometry: dict) -> float:
    """Eye-width vs face-width fifths ratio (0-1, 1 = ideal fifths)."""
    face_width = geometry.get('face_width', 0.0)
    eye_width = geometry.get('eye_width', 0.0)
    if face_width <= 0 or eye_width <= 0:
        return 0.0
    ratio = eye_width / (face_width / 5.0)
    return clamp01(1.0 - abs(ratio - 1.0))


def harmony_from_components(symmetry: float, thirds: float, fifths: float) -> float:
    """Weighted blend of symmetry (0-10) and thirds/fifths proportionality (0-1)."""
    value = (
        HARMONY_WEIGHTS['symmetry'] * float(symmetry)
        + HARMONY_WEIGHTS['thirds'] * float(thirds) * 10.0
        + HARMONY_WEIGHTS['fifths'] * float(fifths) * 10.0
    )
    return clamp(value)


def youthfulness_from_metrics(edge_density_value: float, firmness: float) -> float:
    """Blend periorbital/perioral edge density (fine-line proxy) with cheek firmness."""
    line_score = 10.0 - min(max(0.0, float(edge_density_value)), 1.0) * YOUTH_EDGE_PENALTY
    value = YOUTH_EDGE_WEIGHT * line_score + YOUTH_FIRMNESS_WEIGHT * (clamp01(firmness) * 10.0)
    return clamp(value)


def build_suggestions(attributes: dict) -> list:
    """Generate personalized skincare/makeup/hairstyle suggestions (single source)."""
    face_shape = str(attributes.get('face_shape') or 'oval').lower()
    advice = FACE_SHAPE_ADVICE.get(face_shape, FACE_SHAPE_ADVICE['oval'])
    concerns = [str(item) for item in (attributes.get('concerns') or [])]
    skincare_detail = advice['skincare']
    if concerns:
        concern_advice = SKIN_CONCERN_ADVICE.get(concerns[0])
        if concern_advice:
            skincare_detail = f'{skincare_detail} {concern_advice}'
    makeup_detail = advice['makeup']
    undertone = str(attributes.get('skin_undertone') or 'neutral').lower()
    if undertone in ('warm', 'cool'):
        makeup_detail = f'{makeup_detail} Choose {undertone}-undertone products to match your coloring.'
    return [
        {'category': 'skincare', 'title': 'Skincare routine', 'detail': sanitize_text(skincare_detail)},
        {'category': 'makeup', 'title': 'Cheekbone-focused makeup', 'detail': sanitize_text(makeup_detail)},
        {'category': 'hairstyle', 'title': 'Soft layered cut', 'detail': sanitize_text(advice['hairstyle'])},
    ]


def build_result(scores: dict, attributes: dict, suggestions: list, raw_output: dict, model_version: str) -> FaceAnalysisResult:
    """Assemble the dataclass result, sanitizing all text-bearing payloads."""
    return FaceAnalysisResult(
        overall_score=scores['overall'],
        symmetry_score=scores['symmetry'],
        skin_clarity_score=scores['clarity'],
        youthfulness_score=scores['youth'],
        harmony_score=scores['harmony'],
        detected_attributes=sanitize_structure(attributes),
        suggestions=sanitize_structure(suggestions),
        raw_output=sanitize_structure(raw_output),
        model_version=sanitize_text(model_version)[:64],
    )


# --- image utilities ---------------------------------------------------------
def load_image(image_bytes: bytes) -> Image.Image:
    """Decode and fully verify image bytes, returning an RGB Pillow image."""
    try:
        probe = Image.open(io.BytesIO(image_bytes))
        probe.verify()
        return Image.open(io.BytesIO(image_bytes)).convert('RGB')
    except Exception as exc:
        raise AnalyzerError(f'Unable to read image: {exc}') from exc


def rgb_to_lab(red: int, green: int, blue: int) -> tuple:
    """Convert an RGB triple to the OpenCV LAB scale, preferring OpenCV."""
    if cv2 is not None:
        pixel = np.array([[[red, green, blue]]], dtype=np.uint8)
        lab = cv2.cvtColor(pixel, cv2.COLOR_RGB2LAB)[0, 0]
        return float(lab[0]), float(lab[1]), float(lab[2])
    return _rgb_to_lab_pure(red, green, blue)


def _rgb_to_lab_pure(red: int, green: int, blue: int) -> tuple:
    """sRGB -> CIELAB (D65) on the OpenCV 0-255 scale, no OpenCV required."""
    def channel(value: float) -> float:
        c = value / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r_lin, g_lin, b_lin = channel(red), channel(green), channel(blue)
    x = r_lin * 0.4124 + g_lin * 0.3576 + b_lin * 0.1805
    y = r_lin * 0.2126 + g_lin * 0.7152 + b_lin * 0.0722
    z = r_lin * 0.0193 + g_lin * 0.1192 + b_lin * 0.9505

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / 0.95047), f(y / 1.0), f(z / 1.08883)
    return (116 * fy - 16) * 255 / 100, 500 * (fx - fy) + 128, 200 * (fy - fz) + 128


def box_around(x: float, y: float, radius: int, size: tuple) -> tuple | None:
    """Square crop box around a point, clipped to the image, or None if empty."""
    width, height = size
    left = max(0, int(x) - radius)
    top = max(0, int(y) - radius)
    right = min(width, int(x) + radius)
    bottom = min(height, int(y) + radius)
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def region_stats(image: Image.Image, boxes: list) -> tuple:
    """Mean RGB and mean luminance standard deviation over the given boxes."""
    valid = [box for box in boxes if box is not None]
    if not valid:
        return (0, 0, 0), 0.0
    reds, greens, blues, stds = [], [], [], []
    for box in valid:
        patch = image.crop(box)
        mean = ImageStat.Stat(patch).mean
        reds.append(mean[0])
        greens.append(mean[1] if len(mean) > 1 else mean[0])
        blues.append(mean[2] if len(mean) > 2 else mean[0])
        stds.append(ImageStat.Stat(patch.convert('L')).stddev[0])
    rgb = (int(round(sum(reds) / len(reds))), int(round(sum(greens) / len(greens))), int(round(sum(blues) / len(blues))))
    return rgb, sum(stds) / len(stds)


def edge_density(image: Image.Image, boxes: list) -> float:
    """Mean Canny edge response (0-1) over the given boxes; PIL fallback without OpenCV."""
    valid = [box for box in boxes if box is not None]
    if not valid:
        return 0.0
    values = []
    for box in valid:
        patch = image.crop(box).convert('L')
        if cv2 is not None:
            edges = cv2.Canny(np.asarray(patch, dtype=np.uint8), 80, 160)
            values.append(float(edges.mean()) / 255.0)
        else:
            edge_patch = patch.filter(ImageFilter.FIND_EDGES)
            values.append(float(np.asarray(edge_patch, dtype=np.float32).mean()) / 255.0)
    return sum(values) / len(values)


# --- landmark geometry -------------------------------------------------------
def to_pixel_points(landmarks, width: int, height: int) -> list:
    """Convert normalized landmarks to pixel (x, y) tuples."""
    return [(landmark.x * width, landmark.y * height) for landmark in landmarks]


def extract_face_geometry(points: list) -> dict:
    """Measure face/eye/mouth dimensions from pixel landmark points."""
    def point(index: int) -> tuple:
        return points[index]

    forehead_y = point(FOREHEAD_TOP)[1]
    chin_y = point(CHIN)[1]
    face_length = abs(chin_y - forehead_y)
    face_width = abs(point(CHEEK_LEFT)[0] - point(CHEEK_RIGHT)[0])
    jaw_width = abs(point(JAW_LEFT)[0] - point(JAW_RIGHT)[0])
    forehead_width = abs(point(FOREHEAD_LEFT)[0] - point(FOREHEAD_RIGHT)[0])
    mid_x = (point(CHEEK_LEFT)[0] + point(CHEEK_RIGHT)[0]) / 2.0
    eye_left_width = abs(point(EYE_L_OUTER)[0] - point(EYE_L_INNER)[0])
    eye_right_width = abs(point(EYE_R_OUTER)[0] - point(EYE_R_INNER)[0])
    eye_left_height = abs(point(EYE_L_TOP)[1] - point(EYE_L_BOTTOM)[1])
    eye_right_height = abs(point(EYE_R_TOP)[1] - point(EYE_R_BOTTOM)[1])
    mouth_width = abs(point(MOUTH_LEFT)[0] - point(MOUTH_RIGHT)[0])
    mouth_height = abs(point(UPPER_LIP)[1] - point(LOWER_LIP)[1])
    return {
        'face_length': face_length,
        'face_width': face_width,
        'jaw_width': jaw_width,
        'forehead_width': forehead_width,
        'mid_x': mid_x,
        'eye_width': (eye_left_width + eye_right_width) / 2.0,
        'eye_height': (eye_left_height + eye_right_height) / 2.0,
        'mouth_width': mouth_width,
        'mouth_height': mouth_height,
    }


def symmetry_ratio(points: list, mid_x: float, face_width: float) -> float:
    """Normalized asymmetry from paired landmark distances across the midline."""
    if face_width <= 0:
        return 0.0
    diffs = []
    for left_index, right_index in SYMMETRY_PAIRS:
        if left_index >= len(points) or right_index >= len(points):
            continue
        left_x = points[left_index][0]
        right_x = points[right_index][0]
        diffs.append(abs(left_x + right_x - 2.0 * mid_x))
    if not diffs:
        return 0.0
    return (sum(diffs) / len(diffs)) / face_width


def cheek_firmness(points: list) -> float:
    """Cheek-position proxy for firmness (0-1): aligned cheeks score higher."""
    forehead_y = points[FOREHEAD_TOP][1]
    chin_y = points[CHIN][1]
    ideal_y = (forehead_y + chin_y) / 2.0
    face_height = abs(chin_y - forehead_y)
    if face_height <= 0:
        return 0.0
    drop = (abs(points[CHEEK_LEFT][1] - ideal_y) + abs(points[CHEEK_RIGHT][1] - ideal_y)) / 2.0
    return clamp01(1.0 - (drop / face_height) * 3.0)


def detect_faces(image_bytes: bytes) -> list:
    """Return one landmark list per detected face ([] when no face). Raises when MediaPipe is unavailable."""
    if mp is None:
        raise FaceAnalyzerError()
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        with mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=5) as mesh:
            results = mesh.process(np.asarray(image))
        if not results.multi_face_landmarks:
            return []
        return [list(face.landmark) for face in results.multi_face_landmarks]
    except FaceAnalyzerError:
        raise
    except Exception as exc:  # pragma: no cover - defensive: any inference failure
        raise FaceAnalyzerError() from exc


# --- concern detection -------------------------------------------------------
def _region_lab(image: Image.Image, box) -> tuple | None:
    if box is None:
        return None
    rgb, _ = region_stats(image, [box])
    return rgb_to_lab(*rgb)


def _mean_or(values, default=0.0) -> float:
    clean = [value for value in values if value is not None]
    if not clean:
        return default
    return sum(clean) / len(clean)


def detect_concerns(image: Image.Image, points: list, geometry: dict, clarity: float) -> tuple:
    """Heuristic concern detection: returns (flagged names ordered by severity, score map)."""
    size = image.size
    mid_x = geometry['mid_x']
    cheek_boxes = [
        box_around(*points[CHEEK_SAMPLE_LEFT], 8, size),
        box_around(*points[CHEEK_SAMPLE_RIGHT], 8, size),
    ]
    forehead_box = box_around(points[FOREHEAD_TOP][0], points[FOREHEAD_TOP][1] + 28, 22, size)
    chin_box = box_around(points[CHIN][0], points[CHIN][1] - 18, 16, size)
    patch_labs = [lab for lab in (_region_lab(image, box) for box in cheek_boxes + [forehead_box, chin_box]) if lab]
    cheek_labs = [lab for lab in (_region_lab(image, box) for box in cheek_boxes) if lab]
    l_values = [lab[0] for lab in patch_labs]
    a_values = [lab[1] for lab in patch_labs]
    cheek_a_values = [lab[1] for lab in cheek_labs] or a_values or [128.0]
    cheek_l_values = [lab[0] for lab in cheek_labs] or l_values or [128.0]
    face_l = _mean_or(l_values, 128.0)
    cheek_a = _mean_or(cheek_a_values, 128.0)
    cheek_l = _mean_or(cheek_l_values, 128.0)

    eye_l_center = (
        (points[EYE_L_OUTER][0] + points[EYE_L_INNER][0]) / 2.0,
        (points[EYE_L_TOP][1] + points[EYE_L_BOTTOM][1]) / 2.0,
    )
    eye_r_center = (
        (points[EYE_R_OUTER][0] + points[EYE_R_INNER][0]) / 2.0,
        (points[EYE_R_TOP][1] + points[EYE_R_BOTTOM][1]) / 2.0,
    )
    under_eye_boxes = [
        box_around(eye_l_center[0], points[EYE_L_BOTTOM][1] + 8, 8, size),
        box_around(eye_r_center[0], points[EYE_R_BOTTOM][1] + 8, 8, size),
    ]
    under_labs = [lab for lab in (_region_lab(image, box) for box in under_eye_boxes) if lab]
    under_l = _mean_or([lab[0] for lab in under_labs], cheek_l)

    nose_center = (mid_x, (points[GLABELLA][1] + points[NOSE_BASE][1]) / 2.0)
    t_zone_boxes = [
        box_around(mid_x, points[FOREHEAD_TOP][1] + 28, 22, size),
        box_around(*nose_center, 12, size),
    ]
    t_rgb, t_texture = region_stats(image, t_zone_boxes)
    t_l = rgb_to_lab(*t_rgb)[0] if any(t_zone_boxes) else face_l

    eye_boxes = [
        box_around(*eye_l_center, 16, size),
        box_around(*eye_r_center, 16, size),
    ]
    mouth_center = ((points[MOUTH_LEFT][0] + points[MOUTH_RIGHT][0]) / 2.0, (points[UPPER_LIP][1] + points[LOWER_LIP][1]) / 2.0)
    perioral_boxes = [box_around(*mouth_center, 20, size)]
    fine_line_edges = edge_density(image, eye_boxes + perioral_boxes)

    l_std = statistics.pstdev(l_values) if len(l_values) > 1 else 0.0
    a_std = statistics.pstdev(a_values) if len(a_values) > 1 else 0.0

    scores = {
        'acne': clamp01((a_std - 5.0) / 12.0) if cheek_a >= 138 else clamp01((cheek_a - 150.0) / 40.0) * 0.5,
        'hyperpigmentation': clamp01((l_std - 7.0) / 14.0),
        'redness': clamp01((cheek_a - 140.0) / 30.0),
        'dark_circles': clamp01((cheek_l - under_l - 6.0) / 18.0),
        'fine_lines': clamp01((fine_line_edges - 0.04) / 0.12),
        'dryness': clamp01(((7.0 - clarity) / 4.0) * 0.7 + clamp01((120.0 - face_l) / 60.0) * 0.3),
        'oiliness': clamp01((t_l - cheek_l - 5.0) / 16.0),
        'enlarged_pores': clamp01((t_texture - 10.0) / 20.0),
        'dullness': clamp01(((7.5 - clarity) / 4.0) * 0.5 + clamp01((115.0 - face_l) / 55.0) * 0.5),
    }
    flagged = [name for name, score in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])) if score >= CONCERN_FLAG_THRESHOLD]
    return flagged, scores


# --- backends ----------------------------------------------------------------
class LocalFaceAnalyzerBackend(FaceAnalyzerBackend):
    """MediaPipe landmark pipeline; rejects zero/multiple faces and pipeline failures."""

    provider = 'local'

    def analyze(self, image_bytes: bytes) -> FaceAnalysisResult:
        try:
            image = load_image(image_bytes)
            faces = detect_faces(image_bytes)
            if not faces:
                raise FaceAnalyzerError('No face detected')
            if len(faces) > 1:
                raise FaceAnalyzerError('Multiple faces detected')
            points = to_pixel_points(faces[0], *image.size)
            return self._analyze_from_landmarks(image, points)
        except FaceAnalyzerError:
            raise
        except Exception as exc:
            raise FaceAnalyzerError() from exc

    def _analyze_from_landmarks(self, image: Image.Image, points: list) -> FaceAnalysisResult:
        geometry = extract_face_geometry(points)
        face_shape = classify_face_shape(
            geometry['face_width'], geometry['face_length'], geometry['jaw_width'], geometry['forehead_width']
        )
        ratio = symmetry_ratio(points, geometry['mid_x'], geometry['face_width'])
        symmetry = symmetry_score_from_ratio(ratio)
        skin_boxes = [
            box_around(*points[CHEEK_SAMPLE_LEFT], 8, image.size),
            box_around(*points[CHEEK_SAMPLE_RIGHT], 8, image.size),
        ]
        (red, green, blue), texture = region_stats(image, skin_boxes)
        lab = rgb_to_lab(red, green, blue)
        tone = classify_skin_tone(lab[0])
        undertone = classify_undertone(lab[1], lab[2])
        clarity = clarity_from_texture(texture)
        thirds = facial_thirds_score(points)
        fifths = facial_fifths_score(geometry)
        harmony = harmony_from_components(symmetry, thirds, fifths)
        eye_l_center = (
            (points[EYE_L_OUTER][0] + points[EYE_L_INNER][0]) / 2.0,
            (points[EYE_L_TOP][1] + points[EYE_L_BOTTOM][1]) / 2.0,
        )
        eye_r_center = (
            (points[EYE_R_OUTER][0] + points[EYE_R_INNER][0]) / 2.0,
            (points[EYE_R_TOP][1] + points[EYE_R_BOTTOM][1]) / 2.0,
        )
        mouth_center = (
            (points[MOUTH_LEFT][0] + points[MOUTH_RIGHT][0]) / 2.0,
            (points[UPPER_LIP][1] + points[LOWER_LIP][1]) / 2.0,
        )
        fine_edges = edge_density(image, [
            box_around(*eye_l_center, 16, image.size),
            box_around(*eye_r_center, 16, image.size),
            box_around(*mouth_center, 20, image.size),
        ])
        firmness = cheek_firmness(points)
        youth = youthfulness_from_metrics(fine_edges, firmness)
        scores = assemble_scores(symmetry, clarity, youth, harmony)
        concerns, concern_scores = detect_concerns(image, points, geometry, clarity)
        eye_width = geometry['eye_width'] or 1.0
        mouth_width = geometry['mouth_width'] or 1.0
        attributes = {
            'face_shape': face_shape,
            'skin_tone': tone,
            'skin_undertone': undertone,
            'eye_shape': classify_eye_shape(geometry['eye_height'] / eye_width),
            'lip_fullness': classify_lip_fullness(geometry['mouth_height'] / mouth_width),
            'concerns': concerns,
        }
        suggestions = build_suggestions(attributes)
        raw_output = {
            'method': 'mediapipe-landmarks',
            'landmark_count': len(points),
            'geometry': geometry,
            'skin_lab': list(lab),
            'symmetry_ratio': ratio,
            'thirds_score': thirds,
            'fifths_score': fifths,
            'edge_density': fine_edges,
            'cheek_firmness': firmness,
            'concern_scores': concern_scores,
        }
        version = f"mediapipe-{getattr(mp, '__version__', 'unavailable')}+{MODEL_VERSION_PREFIX}"
        return build_result(scores, attributes, suggestions, raw_output, version)


def parse_external_payload(payload) -> FaceAnalysisResult:
    """Normalize an external provider response into a FaceAnalysisResult."""
    if not isinstance(payload, dict):
        raise AnalyzerError('External analyzer returned an unexpected payload.')
    scores_source = payload.get('scores') if isinstance(payload.get('scores'), dict) else payload

    def read(key: str, default: float) -> float:
        try:
            return float(scores_source.get(key, default))
        except (TypeError, ValueError):
            return default

    symmetry = clamp(read('symmetry_score', 7.0))
    clarity = clamp(read('skin_clarity_score', 7.0))
    youth = clamp(read('youthfulness_score', 7.0))
    harmony = clamp(read('harmony_score', (symmetry + clarity + youth) / 3.0))
    scores = assemble_scores(symmetry, clarity, youth, harmony)
    if 'overall_score' in scores_source:
        scores['overall'] = clamp(read('overall_score', scores['overall']))
    attributes = payload.get('detected_attributes') if isinstance(payload.get('detected_attributes'), dict) else {}
    if not isinstance(attributes.get('concerns'), list):
        attributes = {**attributes, 'concerns': []}
    suggestions = normalize_suggestions(payload.get('suggestions'), attributes)
    model_version = str(payload.get('model_version') or 'external-v1')[:64]
    raw_output = {'method': 'external', 'payload': payload}
    return build_result(scores, attributes, suggestions, raw_output, model_version)


def normalize_suggestions(items, attributes: dict) -> list:
    """Coerce provider suggestions to {category, title, detail}, else generate."""
    normalized = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            category = str(item.get('category') or 'tips')
            title = str(item.get('title') or '').strip()
            detail = str(item.get('detail') or '').strip()
            if title and detail:
                normalized.append({'category': category, 'title': title, 'detail': detail})
    if not normalized:
        return build_suggestions(attributes)
    return normalized


class ExternalFaceAnalyzerBackend(FaceAnalyzerBackend):
    """HTTP provider: POSTs base64 image JSON to FACE_ANALYZER_EXTERNAL_API_URL."""

    provider = 'external'

    def analyze(self, image_bytes: bytes) -> FaceAnalysisResult:
        url = (getattr(settings, 'FACE_ANALYZER_EXTERNAL_API_URL', '') or '').strip()
        if not url:
            raise AnalyzerError('FACE_ANALYZER_EXTERNAL_API_URL is not configured.')
        payload = json.dumps({'image': base64.b64encode(image_bytes).decode('ascii')}).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        api_key = (getattr(settings, 'FACE_ANALYZER_EXTERNAL_API_KEY', '') or '').strip()
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        request = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=EXTERNAL_TIMEOUT_SECONDS) as response:  # nosec B310
                body = response.read()
        except Exception as exc:
            raise AnalyzerError(f'External analyzer request failed: {exc}') from exc
        try:
            data = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            raise AnalyzerError('External analyzer returned invalid JSON.') from exc
        return parse_external_payload(data)


_backend_cache: dict = {}


def get_backend() -> FaceAnalyzerBackend:
    """Build (and cache) the backend selected by FACE_ANALYZER_MODEL_PROVIDER."""
    provider = (getattr(settings, 'FACE_ANALYZER_MODEL_PROVIDER', 'local') or 'local').strip().lower()
    if provider == 'external' and not (getattr(settings, 'FACE_ANALYZER_EXTERNAL_API_URL', '') or '').strip():
        raise ImproperlyConfigured(
            "FACE_ANALYZER_EXTERNAL_API_URL must be set when FACE_ANALYZER_MODEL_PROVIDER='external'."
        )
    cached = _backend_cache.get(provider)
    if cached is not None:
        return cached
    if provider == 'local':
        backend = LocalFaceAnalyzerBackend()
    elif provider == 'external':
        backend = ExternalFaceAnalyzerBackend()
    else:
        raise AnalyzerError(f"Unknown FACE_ANALYZER_MODEL_PROVIDER '{provider}'. Use 'local' or 'external'.")
    _backend_cache[provider] = backend
    return backend
