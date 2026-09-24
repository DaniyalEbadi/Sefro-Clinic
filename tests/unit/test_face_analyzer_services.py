"""Unit tests for the Face AI Analyzer service layer (pure helpers + backends + tips engine)."""
import io
import json
import math
import tempfile
from types import SimpleNamespace
from unittest import mock

import numpy as np
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from customers.models import Service
from face_analyzer.exceptions import (
    PERSIAN_ANALYZE_FAILURE,
    AnalyzerError,
    FaceAnalyzerError,
)
from face_analyzer.models import FaceAnalysis, SkinCareTip
from face_analyzer.serializers import FaceAttributesSerializer, sniff_image_format
from face_analyzer.services.analyzer import (
    CONCERN_NAMES,
    ExternalFaceAnalyzerBackend,
    FaceAnalyzerBackend,
    LocalFaceAnalyzerBackend,
    _backend_cache,
    _rgb_to_lab_pure,
    assemble_scores,
    box_around,
    build_suggestions,
    cheek_firmness,
    clamp,
    clamp01,
    clarity_from_texture,
    classify_eye_shape,
    classify_face_shape,
    classify_lip_fullness,
    classify_skin_tone,
    classify_undertone,
    detect_concerns,
    edge_density,
    extract_face_geometry,
    facial_fifths_score,
    facial_thirds_score,
    get_backend,
    harmony_from_components,
    load_image,
    normalize_suggestions,
    parse_external_payload,
    region_stats,
    rgb_to_lab,
    sanitize_structure,
    sanitize_text,
    symmetry_ratio,
    symmetry_score_from_ratio,
    to_pixel_points,
    youthfulness_from_metrics,
)
from face_analyzer.services.tips import (
    PERIODS,
    RULES,
    VALID_CATEGORIES,
    VALID_PERIODS,
    VALID_PRIORITIES,
    LLMTipsProvider,
    RuleBasedTipsProvider,
    _resolve_services,
    _sanitize_tip,
    build_summary,
    derive_skin_type,
    generate_and_store_plan,
    get_tips_provider,
    recommended_frequency,
)
from face_analyzer.views import FaceAnalyzerThrottle, _can_view_all

LANDMARK_COUNT = 468
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='face_analyzer_unit_media_')


def make_points(shift_eye=0.0):
    """Fabricate symmetric pixel-space landmarks for a 200x300 canvas."""
    points = [(100.0, 150.0)] * LANDMARK_COUNT

    def set_point(index, x, y):
        points[index] = (float(x), float(y))

    set_point(10, 100, 30)      # forehead top
    set_point(151, 100, 90)     # glabella
    set_point(2, 100, 170)      # nose base
    set_point(152, 100, 270)    # chin
    set_point(234, 30, 150)     # cheek left
    set_point(454, 170, 150)    # cheek right
    set_point(172, 45, 240)     # jaw left
    set_point(397, 155, 240)    # jaw right
    set_point(54, 45, 60)       # forehead left
    set_point(284, 155, 60)     # forehead right
    set_point(33, 60 + shift_eye, 120)   # eye L outer
    set_point(263, 140, 120)    # eye R outer
    set_point(133, 95, 120)     # eye L inner
    set_point(362, 105, 120)    # eye R inner
    set_point(159, 77, 112)     # eye L top
    set_point(386, 123, 112)    # eye R top
    set_point(145, 77, 128)     # eye L bottom
    set_point(374, 123, 128)    # eye R bottom
    set_point(61, 75, 218)      # mouth left
    set_point(291, 125, 218)    # mouth right
    set_point(13, 100, 210)     # upper lip
    set_point(14, 100, 226)     # lower lip
    set_point(50, 60, 170)      # cheek sample left
    set_point(280, 140, 170)    # cheek sample right
    set_point(103, 55, 45)
    set_point(332, 145, 45)
    set_point(127, 35, 190)
    set_point(356, 165, 190)
    set_point(205, 55, 145)
    set_point(425, 145, 145)
    set_point(58, 50, 255)
    set_point(288, 150, 255)
    set_point(49, 42, 230)
    set_point(279, 158, 230)
    set_point(36, 55, 115)
    set_point(246, 145, 115)
    set_point(144, 70, 133)
    set_point(373, 130, 133)
    return points


def png_bytes(size=(96, 96), color=(198, 152, 126)):
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, format='PNG')
    return buffer.getvalue()


def make_mock_analysis(concerns=None, overall_score=7.8):
    return SimpleNamespace(
        detected_attributes={
            'face_shape': 'oval',
            'skin_tone': 'medium',
            'skin_undertone': 'warm',
            'eye_shape': 'almond',
            'lip_fullness': 'medium',
            'concerns': list(concerns or []),
        },
        overall_score=overall_score,
        symmetry_score=8.0,
        skin_clarity_score=7.5,
        youthfulness_score=8.0,
        harmony_score=7.6,
    )


class GeometryHelperTests(SimpleTestCase):
    def test_classify_face_shape_all_six_labels(self):
        self.assertEqual(classify_face_shape(100, 150, 80, 92), 'heart')
        self.assertEqual(classify_face_shape(100, 150, 80, 84), 'oblong')
        self.assertEqual(classify_face_shape(100, 110, 95, 92), 'square')
        self.assertEqual(classify_face_shape(100, 110, 80, 78), 'diamond')
        self.assertEqual(classify_face_shape(100, 110, 90, 90), 'round')
        self.assertEqual(classify_face_shape(100, 135, 96, 96), 'square')
        self.assertEqual(classify_face_shape(100, 135, 85, 95), 'heart')
        self.assertEqual(classify_face_shape(100, 135, 80, 80), 'diamond')
        self.assertEqual(classify_face_shape(100, 135, 85, 88), 'oval')
        self.assertEqual(classify_face_shape(0, 0, 0, 0), 'oval')

    def test_classify_eye_shape_branches(self):
        self.assertEqual(classify_eye_shape(0.5), 'round')
        self.assertEqual(classify_eye_shape(0.4), 'almond')
        self.assertEqual(classify_eye_shape(0.33), 'almond')
        self.assertEqual(classify_eye_shape(0.2), 'hooded')

    def test_classify_lip_fullness_branches(self):
        self.assertEqual(classify_lip_fullness(0.5), 'full')
        self.assertEqual(classify_lip_fullness(0.35), 'medium')
        self.assertEqual(classify_lip_fullness(0.30), 'medium')
        self.assertEqual(classify_lip_fullness(0.2), 'thin')

    def test_classify_skin_tone_five_labels(self):
        self.assertEqual(classify_skin_tone(200), 'fair')
        self.assertEqual(classify_skin_tone(150), 'light')
        self.assertEqual(classify_skin_tone(120), 'medium')
        self.assertEqual(classify_skin_tone(90), 'tan')
        self.assertEqual(classify_skin_tone(50), 'deep')

    def test_classify_undertone_branches(self):
        self.assertEqual(classify_undertone(145, 160), 'warm')
        self.assertEqual(classify_undertone(120, 125), 'cool')
        self.assertEqual(classify_undertone(130, 145), 'neutral')

    def test_extract_face_geometry_from_fabricated_points(self):
        geometry = extract_face_geometry(make_points())
        self.assertEqual(geometry['face_length'], 240)
        self.assertEqual(geometry['face_width'], 140)
        self.assertEqual(geometry['jaw_width'], 110)
        self.assertEqual(geometry['forehead_width'], 110)
        self.assertEqual(geometry['mid_x'], 100)
        self.assertEqual(geometry['eye_width'], 35)
        self.assertEqual(geometry['eye_height'], 16)
        self.assertEqual(geometry['mouth_width'], 50)
        self.assertEqual(geometry['mouth_height'], 16)

    def test_symmetry_ratio_symmetric_is_zero(self):
        points = make_points()
        geometry = extract_face_geometry(points)
        self.assertEqual(symmetry_ratio(points, geometry['mid_x'], geometry['face_width']), 0.0)

    def test_symmetry_ratio_grows_with_asymmetry(self):
        symmetric = make_points()
        asymmetric = make_points(shift_eye=10)
        geometry = extract_face_geometry(asymmetric)
        ratio = symmetry_ratio(asymmetric, geometry['mid_x'], geometry['face_width'])
        self.assertGreater(ratio, 0.0)
        self.assertLess(ratio, 0.1)
        self.assertGreater(ratio, symmetry_ratio(symmetric, 100.0, 140.0))

    def test_symmetry_ratio_degenerate_inputs(self):
        self.assertEqual(symmetry_ratio([], 100.0, 0.0), 0.0)
        self.assertEqual(symmetry_ratio([(0.0, 0.0)] * 3, 100.0, 140.0), 0.0)

    def test_facial_thirds_score_symmetric_ish(self):
        score = facial_thirds_score(make_points())
        self.assertTrue(0.0 <= score <= 1.0)
        self.assertGreater(score, 0.5)

    def test_facial_thirds_score_nonpositive_mean_is_zero(self):
        points = [(100.0, 300.0)] * LANDMARK_COUNT
        points[10] = (100.0, 300.0)
        points[151] = (100.0, 200.0)
        points[2] = (100.0, 100.0)
        points[152] = (100.0, 0.0)
        self.assertEqual(facial_thirds_score(points), 0.0)

    def test_facial_fifths_score(self):
        geometry = {'face_width': 140.0, 'eye_width': 35.0}  # ratio 1.25 -> score 0.75
        self.assertAlmostEqual(facial_fifths_score(geometry), 0.75, places=5)
        geometry_ideal = {'face_width': 150.0, 'eye_width': 30.0}  # eye = width/5
        self.assertEqual(facial_fifths_score(geometry_ideal), 1.0)
        self.assertEqual(facial_fifths_score({'face_width': 0.0, 'eye_width': 10.0}), 0.0)
        self.assertEqual(facial_fifths_score({'face_width': 100.0, 'eye_width': 5.0}), 0.25)

    def test_cheek_firmness_aligned_cheeks_score_high(self):
        self.assertAlmostEqual(cheek_firmness(make_points()), 1.0, places=5)
        self.assertEqual(cheek_firmness([(0.0, 0.0)] * LANDMARK_COUNT), 0.0)

    def test_to_pixel_points_scales_normalized_coordinates(self):
        landmark = mock.Mock(x=0.5, y=0.25)
        self.assertEqual(to_pixel_points([landmark], 200, 400), [(100.0, 100.0)])


class ScoreHelperTests(SimpleTestCase):
    def test_clamp_and_clamp01(self):
        self.assertEqual(clamp(11), 10.0)
        self.assertEqual(clamp(-1), 0.0)
        self.assertEqual(clamp(7.26), 7.3)
        self.assertEqual(clamp01(1.5), 1.0)
        self.assertEqual(clamp01(-0.5), 0.0)

    def test_symmetry_score_from_ratio(self):
        self.assertEqual(symmetry_score_from_ratio(0.0), 10.0)
        self.assertEqual(symmetry_score_from_ratio(0.1), 2.0)
        self.assertEqual(symmetry_score_from_ratio(0.5), 0.0)
        self.assertEqual(symmetry_score_from_ratio(-1.0), 10.0)

    def test_clarity_from_texture(self):
        self.assertEqual(clarity_from_texture(0), 9.5)
        self.assertEqual(clarity_from_texture(6), 8.5)
        self.assertEqual(clarity_from_texture(1000), 4.0)

    def test_assemble_scores_applies_weighted_overall(self):
        scores = assemble_scores(8.0, 7.0, 9.0, 6.0)
        self.assertEqual(
            set(scores.keys()),
            {'overall', 'symmetry', 'clarity', 'youth', 'harmony'},
        )
        expected = 0.35 * 8.0 + 0.30 * 7.0 + 0.15 * 9.0 + 0.20 * 6.0
        self.assertAlmostEqual(scores['overall'], round(expected, 1), places=5)
        for value in scores.values():
            self.assertTrue(0 <= value <= 10)

    def test_harmony_from_components(self):
        self.assertEqual(harmony_from_components(10.0, 1.0, 1.0), 10.0)
        self.assertEqual(harmony_from_components(0.0, 0.0, 0.0), 0.0)
        self.assertAlmostEqual(harmony_from_components(10.0, 0.75, 0.75), 8.8, places=5)

    def test_youthfulness_from_metrics_bounds(self):
        self.assertEqual(youthfulness_from_metrics(0.0, 1.0), 10.0)
        self.assertAlmostEqual(youthfulness_from_metrics(1.0, 0.0), 2.4, places=5)
        self.assertTrue(0 <= youthfulness_from_metrics(0.5, 0.5) <= 10)


class SuggestionAndSanitizeTests(SimpleTestCase):
    def test_build_suggestions_for_all_known_shapes_and_unknown(self):
        for shape in ('oval', 'round', 'square', 'heart', 'oblong', 'diamond', 'unknown-shape'):
            suggestions = build_suggestions({'face_shape': shape, 'skin_undertone': 'neutral'})
            self.assertEqual([item['category'] for item in suggestions], ['skincare', 'makeup', 'hairstyle'])
            for item in suggestions:
                self.assertEqual(set(item.keys()), {'category', 'title', 'detail'})
                self.assertTrue(item['detail'])

    def test_build_suggestions_appends_primary_concern_advice(self):
        suggestions = build_suggestions({'face_shape': 'oval', 'concerns': ['hyperpigmentation', 'acne']})
        skincare = next(item for item in suggestions if item['category'] == 'skincare')
        self.assertIn('vitamin C serum', skincare['detail'])

    def test_build_suggestions_unknown_concern_keeps_shape_advice(self):
        suggestions = build_suggestions({'face_shape': 'round', 'concerns': ['not-a-concern']})
        skincare = next(item for item in suggestions if item['category'] == 'skincare')
        self.assertIn('non-comedogenic', skincare['detail'])

    def test_build_suggestions_appends_undertone_advice(self):
        suggestions = build_suggestions({'face_shape': 'oval', 'skin_undertone': 'warm'})
        makeup = next(item for item in suggestions if item['category'] == 'makeup')
        self.assertIn('warm-undertone', makeup['detail'])

    def test_sanitize_text_strips_null_bytes_and_surrogates(self):
        self.assertEqual(sanitize_text('abc\x00def'), 'abcdef')
        self.assertEqual(sanitize_text('ok\ud800text'), 'oktext')
        self.assertEqual(sanitize_text('unchanged'), 'unchanged')

    def test_sanitize_structure_recurses_and_json_safeifies(self):
        payload = {
            'nested': [{'title': 'a\x00b'}, 'plain'],
            'count': np.float64(1.5),
            'array': np.array([1, 2]),
            'bad_float': float('nan'),
            'int': 3,
            7: 'numeric-key',
        }
        cleaned = sanitize_structure(payload)
        self.assertEqual(cleaned['nested'][0]['title'], 'ab')
        self.assertEqual(cleaned['count'], 1.5)
        self.assertEqual(cleaned['array'], [1, 2])
        self.assertEqual(cleaned['bad_float'], 0.0)
        self.assertEqual(cleaned['int'], 3)
        self.assertEqual(cleaned[7], 'numeric-key')
        self.assertTrue(math.isfinite(cleaned['bad_float']))


class ImageHelperTests(SimpleTestCase):
    @staticmethod
    def solid_image(color=(198, 152, 126), size=(96, 96), mode='RGB'):
        buffer = io.BytesIO()
        Image.new(mode, size, color).save(buffer, format='PNG')
        return buffer.getvalue()

    def test_load_image_returns_rgb(self):
        png = self.solid_image(color=128, mode='L')
        image = load_image(png)
        self.assertEqual(image.mode, 'RGB')

    def test_load_image_rejects_garbage(self):
        with self.assertRaises(AnalyzerError):
            load_image(b'not an image at all')

    def test_rgb_to_lab_matches_pure_implementation(self):
        pure = _rgb_to_lab_pure(198, 152, 126)
        via_api = rgb_to_lab(198, 152, 126)
        for pure_value, api_value in zip(pure, via_api):
            self.assertAlmostEqual(pure_value, api_value, delta=3)

    def test_rgb_to_lab_falls_back_without_opencv(self):
        with mock.patch('face_analyzer.services.analyzer.cv2', None):
            via_fallback = rgb_to_lab(198, 152, 126)
        pure = _rgb_to_lab_pure(198, 152, 126)
        for fallback_value, pure_value in zip(via_fallback, pure):
            self.assertAlmostEqual(fallback_value, pure_value, places=6)

    def test_box_around_clips_and_detects_empty(self):
        self.assertEqual(box_around(5, 5, 10, (96, 96)), (0, 0, 15, 15))
        self.assertIsNone(box_around(0, 0, 0, (96, 96)))
        self.assertIsNone(box_around(200, 200, 10, (96, 96)))

    def test_region_stats_on_solid_color(self):
        image = Image.open(io.BytesIO(self.solid_image())).convert('RGB')
        rgb, texture = region_stats(image, [(0, 0, 96, 96)])
        self.assertEqual(rgb, (198, 152, 126))
        self.assertEqual(texture, 0.0)
        self.assertEqual(region_stats(image, [None]), ((0, 0, 0), 0.0))

    def test_edge_density_solid_is_near_zero(self):
        image = Image.open(io.BytesIO(self.solid_image())).convert('RGB')
        value = edge_density(image, [(10, 10, 60, 60)])
        self.assertTrue(0.0 <= value < 0.05)

    def test_edge_density_empty_boxes_is_zero(self):
        image = Image.open(io.BytesIO(self.solid_image())).convert('RGB')
        self.assertEqual(edge_density(image, [None]), 0.0)

    def test_edge_density_falls_back_without_opencv(self):
        image = Image.open(io.BytesIO(self.solid_image())).convert('RGB')
        with mock.patch('face_analyzer.services.analyzer.cv2', None):
            value = edge_density(image, [(10, 10, 60, 60)])
        self.assertIsInstance(value, float)
        self.assertTrue(0.0 <= value <= 1.0)

    def test_sniff_image_format_magic_bytes(self):
        self.assertEqual(sniff_image_format(b'\xff\xd8\xffrest'), 'image/jpeg')
        self.assertEqual(sniff_image_format(b'\x89PNG\r\n\x1a\nrest'), 'image/png')
        self.assertEqual(sniff_image_format(b'RIFF\x00\x00\x00\x00WEBP'), 'image/webp')
        self.assertIsNone(sniff_image_format(b'GIF89a....'))


class ConcernDetectionTests(SimpleTestCase):
    def test_detect_concerns_covers_all_names_ordered_by_severity(self):
        image = Image.open(io.BytesIO(png_bytes(size=(200, 300)))).convert('RGB')
        points = make_points()
        geometry = extract_face_geometry(points)
        flagged, scores = detect_concerns(image, points, geometry, clarity=7.0)

        self.assertEqual(set(scores.keys()), set(CONCERN_NAMES))
        for value in scores.values():
            self.assertTrue(0.0 <= value <= 1.0)
        self.assertEqual(len(flagged), len(set(flagged)))
        severities = [scores[name] for name in flagged]
        self.assertEqual(severities, sorted(severities, reverse=True))
        for name in flagged:
            self.assertGreaterEqual(scores[name], 0.45)


class LocalBackendTests(SimpleTestCase):
    def test_analyze_rejects_zero_faces_with_persian_aware_error(self):
        with mock.patch('face_analyzer.services.analyzer.detect_faces', return_value=[]):
            with self.assertRaises(FaceAnalyzerError) as ctx:
                LocalFaceAnalyzerBackend().analyze(png_bytes())
        self.assertEqual(str(ctx.exception.detail), 'No face detected')
        self.assertEqual(ctx.exception.status_code, 400)

    def test_analyze_rejects_multiple_faces(self):
        faces = [mock.Mock(), mock.Mock()]
        with mock.patch('face_analyzer.services.analyzer.detect_faces', return_value=faces):
            with self.assertRaises(FaceAnalyzerError) as ctx:
                LocalFaceAnalyzerBackend().analyze(png_bytes())
        self.assertEqual(str(ctx.exception.detail), 'Multiple faces detected')

    def test_detect_faces_raises_when_mediapipe_unavailable(self):
        from face_analyzer.services.analyzer import detect_faces

        with mock.patch('face_analyzer.services.analyzer.mp', None):
            with self.assertRaises(FaceAnalyzerError) as ctx:
                detect_faces(png_bytes())
        self.assertEqual(str(ctx.exception.detail), PERSIAN_ANALYZE_FAILURE)

    def test_pipeline_failure_maps_to_persian_default(self):
        with mock.patch(
            'face_analyzer.services.analyzer.detect_faces', side_effect=RuntimeError('boom')
        ):
            with self.assertRaises(FaceAnalyzerError) as ctx:
                LocalFaceAnalyzerBackend().analyze(png_bytes())
        self.assertEqual(str(ctx.exception.detail), PERSIAN_ANALYZE_FAILURE)

    def test_landmark_pipeline_with_fabricated_points(self):
        image = Image.open(io.BytesIO(png_bytes(size=(200, 300)))).convert('RGB')
        points = make_points()
        result = LocalFaceAnalyzerBackend()._analyze_from_landmarks(image, points)

        self.assertTrue(0 <= result.overall_score <= 10)
        self.assertEqual(result.detected_attributes['face_shape'], 'oblong')
        self.assertEqual(result.detected_attributes['eye_shape'], 'almond')
        self.assertEqual(result.detected_attributes['lip_fullness'], 'medium')
        self.assertEqual(result.raw_output['method'], 'mediapipe-landmarks')
        self.assertEqual(result.raw_output['symmetry_ratio'], 0.0)
        self.assertEqual(len(result.suggestions), 3)
        self.assertEqual(set(result.raw_output['concern_scores'].keys()), set(CONCERN_NAMES))
        self.assertNotIn('image', result.raw_output)

    def test_landmark_pipeline_detects_asymmetric_face(self):
        image = Image.open(io.BytesIO(png_bytes(size=(200, 300)))).convert('RGB')
        asymmetric = LocalFaceAnalyzerBackend()._analyze_from_landmarks(image, make_points(shift_eye=25))
        symmetric = LocalFaceAnalyzerBackend()._analyze_from_landmarks(image, make_points())
        self.assertLess(asymmetric.symmetry_score, symmetric.symmetry_score)

    def test_analyze_routes_through_detect_faces(self):
        width, height = 200, 300
        normalized = [mock.Mock(x=x / width, y=y / height) for (x, y) in make_points()]
        with mock.patch('face_analyzer.services.analyzer.detect_faces', return_value=[normalized]):
            result = LocalFaceAnalyzerBackend().analyze(png_bytes(size=(width, height)))
        self.assertEqual(result.raw_output['method'], 'mediapipe-landmarks')
        self.assertEqual(result.raw_output['landmark_count'], LANDMARK_COUNT)
        self.assertIn('+sefro-local-v1', result.model_version)
        self.assertLessEqual(len(result.model_version), 64)


class ExternalBackendTests(SimpleTestCase):
    @override_settings(
        FACE_ANALYZER_EXTERNAL_API_URL='https://provider.test/analyze',
        FACE_ANALYZER_EXTERNAL_API_KEY='secret-key',
    )
    def test_external_backend_posts_and_parses(self):
        payload = {
            'overall_score': 8.1,
            'symmetry_score': 8.4,
            'skin_clarity_score': 7.2,
            'youthfulness_score': 7.9,
            'harmony_score': 8.0,
            'detected_attributes': {'face_shape': 'heart', 'skin_tone': 'light'},
            'suggestions': [{'category': 'makeup', 'title': 'Soft glow', 'detail': 'Use peach blush.'}],
            'model_version': 'provider-v2',
        }

        class FakeResponse:
            def read(self):
                return json.dumps(payload).encode('utf-8')

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch(
            'face_analyzer.services.analyzer.urllib.request.urlopen', return_value=FakeResponse()
        ) as urlopen:
            result = ExternalFaceAnalyzerBackend().analyze(b'image-bytes')

        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://provider.test/analyze')
        self.assertEqual(request.get_header('Authorization'), 'Bearer secret-key')
        self.assertEqual(json.loads(request.data)['image'], 'aW1hZ2UtYnl0ZXM=')
        self.assertEqual(result.overall_score, 8.1)
        self.assertEqual(result.harmony_score, 8.0)
        self.assertEqual(result.detected_attributes['face_shape'], 'heart')
        self.assertEqual(result.suggestions[0]['category'], 'makeup')
        self.assertEqual(result.model_version, 'provider-v2')

    @override_settings(FACE_ANALYZER_EXTERNAL_API_URL='')
    def test_external_backend_requires_url(self):
        with self.assertRaises(AnalyzerError):
            ExternalFaceAnalyzerBackend().analyze(b'image-bytes')

    @override_settings(FACE_ANALYZER_EXTERNAL_API_URL='https://provider.test/analyze')
    def test_external_backend_wraps_network_errors(self):
        import urllib.error

        with mock.patch(
            'face_analyzer.services.analyzer.urllib.request.urlopen',
            side_effect=urllib.error.URLError('boom'),
        ):
            with self.assertRaises(AnalyzerError):
                ExternalFaceAnalyzerBackend().analyze(b'image-bytes')

    @override_settings(FACE_ANALYZER_EXTERNAL_API_URL='https://provider.test/analyze')
    def test_external_backend_rejects_invalid_json(self):
        class FakeResponse:
            def read(self):
                return b'not json'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch('face_analyzer.services.analyzer.urllib.request.urlopen', return_value=FakeResponse()):
            with self.assertRaises(AnalyzerError):
                ExternalFaceAnalyzerBackend().analyze(b'image-bytes')


class ParsePayloadTests(SimpleTestCase):
    def test_parse_external_payload_nested_scores(self):
        result = parse_external_payload({
            'scores': {'overall_score': 9.0, 'symmetry_score': 6.0, 'skin_clarity_score': 6.0},
            'detected_attributes': {'face_shape': 'square'},
        })
        self.assertEqual(result.overall_score, 9.0)
        self.assertEqual(result.detected_attributes['face_shape'], 'square')
        self.assertEqual(len(result.suggestions), 3)  # generated: provider sent none

    def test_parse_external_payload_tolerates_bad_types(self):
        result = parse_external_payload({
            'symmetry_score': 'not-a-number',
            'suggestions': ['junk', {'category': 'x'}],
        })
        self.assertTrue(0 <= result.symmetry_score <= 10)
        self.assertEqual(len(result.suggestions), 3)  # invalid items -> generated

    def test_parse_external_payload_rejects_non_dict(self):
        with self.assertRaises(AnalyzerError):
            parse_external_payload(['not', 'a', 'dict'])

    def test_parse_external_payload_defaults_and_uses_assembly(self):
        result = parse_external_payload({})
        self.assertTrue(0 <= result.overall_score <= 10)
        self.assertTrue(0 <= result.harmony_score <= 10)
        self.assertEqual(result.model_version, 'external-v1')

    def test_normalize_suggestions_keeps_valid_items(self):
        items = [
            {'category': 'makeup', 'title': ' T ', 'detail': 'D'},
            {'title': '', 'detail': 'missing title'},
            'not-a-dict',
        ]
        normalized = normalize_suggestions(items, {})
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]['title'], 'T')

    def test_normalize_suggestions_falls_back_to_generated(self):
        generated = normalize_suggestions(None, {'face_shape': 'square'})
        self.assertEqual([item['category'] for item in generated], ['skincare', 'makeup', 'hairstyle'])


class SerializerAndPermissionHelperTests(SimpleTestCase):
    def test_face_attributes_serializer_passes_extra_keys(self):
        data = FaceAttributesSerializer().to_representation({
            'face_shape': 'oval',
            'custom_key': 'custom-value',
        })
        self.assertEqual(data['face_shape'], 'oval')
        self.assertEqual(data['custom_key'], 'custom-value')

    def test_face_attributes_serializer_handles_non_dict_instance(self):
        class Attrs:
            face_shape = 'round'
            skin_tone = ''
            skin_undertone = ''
            eye_shape = ''
            lip_fullness = ''

        data = FaceAttributesSerializer().to_representation(Attrs())
        self.assertEqual(data['face_shape'], 'round')

    def test_can_view_all_by_role(self):
        self.assertFalse(_can_view_all(None))
        self.assertFalse(_can_view_all(mock.Mock(is_authenticated=False)))
        self.assertFalse(_can_view_all(mock.Mock(role='employee')))
        self.assertTrue(_can_view_all(mock.Mock(role='admin')))

    @override_settings(FACE_ANALYZER_THROTTLE_RATE='7/min')
    def test_face_analyzer_throttle_reads_live_rate(self):
        self.assertEqual(FaceAnalyzerThrottle().get_rate(), '7/min')


class FactoryAndExceptionTests(SimpleTestCase):
    def setUp(self):
        _backend_cache.clear()

    def tearDown(self):
        _backend_cache.clear()

    def test_backend_analyze_is_abstract(self):
        with self.assertRaises(NotImplementedError):
            FaceAnalyzerBackend.analyze(mock.Mock(), b'image-bytes')

    def test_get_backend_defaults_to_local_and_caches(self):
        backend = get_backend()
        self.assertIsInstance(backend, LocalFaceAnalyzerBackend)
        self.assertEqual(backend.provider, 'local')
        self.assertIs(get_backend(), backend)

    @override_settings(
        FACE_ANALYZER_MODEL_PROVIDER='external',
        FACE_ANALYZER_EXTERNAL_API_URL='https://provider.test/analyze',
    )
    def test_get_backend_external(self):
        backend = get_backend()
        self.assertIsInstance(backend, ExternalFaceAnalyzerBackend)
        self.assertEqual(backend.provider, 'external')

    @override_settings(FACE_ANALYZER_MODEL_PROVIDER='external', FACE_ANALYZER_EXTERNAL_API_URL='')
    def test_get_backend_external_without_url_is_improperly_configured(self):
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            get_backend()

    @override_settings(FACE_ANALYZER_MODEL_PROVIDER='bogus')
    def test_get_backend_unknown_provider(self):
        with self.assertRaises(AnalyzerError):
            get_backend()

    def test_exception_status_codes_and_persian_default(self):
        self.assertEqual(AnalyzerError().status_code, 500)
        self.assertEqual(FaceAnalyzerError().status_code, 400)
        self.assertEqual(str(FaceAnalyzerError().detail), PERSIAN_ANALYZE_FAILURE)


class TipsRuleTests(SimpleTestCase):
    def test_rules_keys_and_template_fields_are_valid(self):
        self.assertGreaterEqual(len(RULES), 30)
        for (concern, period), templates in RULES.items():
            self.assertIn(period, VALID_PERIODS)
            self.assertIn(concern, ('baseline',) + tuple(CONCERN_NAMES))
            self.assertIsInstance(templates, list)
            self.assertGreaterEqual(len(templates), 1)
            for template in templates:
                self.assertIn(template['priority'], VALID_PRIORITIES)
                self.assertIn(template['category'], VALID_CATEGORIES)
                self.assertTrue(template['title'])
                self.assertTrue(template['description'])
                self.assertIsInstance(template['key_ingredients'], list)
                self.assertIsInstance(template['avoid_ingredients'], list)

    def test_in_clinic_rules_carry_related_service_slugs(self):
        slugs = {
            template['related_service_slug']
            for (_concern, period), templates in RULES.items()
            if period == 'professional'
            for template in templates
        }
        self.assertEqual(
            slugs,
            {'ipl', 'extraction', 'carboxy-therapy', 'microneedling', 'hydrafacial', 'chemical-peel'},
        )

    def test_derive_skin_type(self):
        self.assertEqual(derive_skin_type(['oiliness', 'dryness']), 'combination')
        self.assertEqual(derive_skin_type(['oiliness']), 'oily')
        self.assertEqual(derive_skin_type(['dryness']), 'dry')
        self.assertEqual(derive_skin_type(['redness']), 'normal')

    def test_recommended_frequency_bands(self):
        self.assertEqual(recommended_frequency([]), 'Daily SPF with gentle hydration')
        self.assertEqual(recommended_frequency(['dullness']), 'SPF daily, actives 2x weekly')
        self.assertEqual(
            recommended_frequency(['hyperpigmentation', 'dullness', 'enlarged_pores']),
            'SPF daily, actives 3x weekly',
        )

    def test_build_summary_bands_and_concerns(self):
        self.assertIn('excellent', build_summary('normal', [], 9.0))
        self.assertIn('good', build_summary('normal', [], 7.5))
        self.assertIn('fair', build_summary('normal', [], 5.5))
        self.assertIn('needs attention', build_summary('normal', [], 3.0))
        summary = build_summary('oily', ['acne', 'oiliness', 'dullness', 'extra'], 7.8)
        self.assertIn('oily', summary)
        self.assertIn('acne, oiliness, dullness', summary)  # capped at 3
        self.assertIn('no major concerns', build_summary('dry', [], 8.0))

    def test_sanitize_tip_coerces_invalid_enums(self):
        tip = _sanitize_tip({
            'period': 'nope',
            'priority': 'urgent',
            'category': 'rocket',
            'sort_order': 'bad',
            'title': 'T',
            'description': 'D',
            'related_service_slug': '',
        })
        self.assertEqual(tip['period'], 'lifestyle')
        self.assertEqual(tip['priority'], 'medium')
        self.assertEqual(tip['category'], 'lifestyle')
        self.assertEqual(tip['sort_order'], 0)

    def test_sanitize_tip_truncates_title(self):
        tip = _sanitize_tip({'title': 'x' * 500, 'description': 'D', 'sort_order': 3})
        self.assertEqual(len(tip['title']), 200)
        self.assertEqual(tip['sort_order'], 3)


class TipsProviderTests(SimpleTestCase):
    def test_rule_based_provider_is_deterministic(self):
        analysis = make_mock_analysis(concerns=['hyperpigmentation', 'dullness'])
        first = RuleBasedTipsProvider().generate(analysis)
        second = RuleBasedTipsProvider().generate(analysis)

        self.assertEqual(first.tips, second.tips)
        self.assertEqual(first.provider, 'rule_based')
        self.assertEqual(first.model_used, 'sefro-rules-v1')
        self.assertEqual(first.skin_type, 'normal')
        orders = [tip['sort_order'] for tip in first.tips]
        self.assertEqual(orders, list(range(1, len(first.tips) + 1)))
        for tip in first.tips:
            self.assertIn(tip['period'], PERIODS)

    def test_rule_based_provider_derives_oily_type(self):
        analysis = make_mock_analysis(concerns=['oiliness'])
        draft = RuleBasedTipsProvider().generate(analysis)
        self.assertEqual(draft.skin_type, 'oily')
        self.assertEqual(draft.primary_concerns, ['oiliness'])

    @override_settings(FACE_ANALYZER_TIPS_PROVIDER='rule_based')
    def test_get_tips_provider_defaults_and_caches(self):
        provider = get_tips_provider()
        self.assertIsInstance(provider, RuleBasedTipsProvider)
        self.assertIs(get_tips_provider(), provider)

    @override_settings(FACE_ANALYZER_TIPS_PROVIDER='llm')
    def test_get_tips_provider_llm(self):
        provider = get_tips_provider()
        self.assertIsInstance(provider, LLMTipsProvider)

    @override_settings(FACE_ANALYZER_TIPS_PROVIDER='llm')
    def test_llm_provider_falls_back_on_call_failure(self):
        analysis = make_mock_analysis(concerns=['acne'])
        with mock.patch(
            'face_analyzer.services.tips.LLMTipsProvider._call_llm', side_effect=RuntimeError('down')
        ):
            draft = LLMTipsProvider().generate(analysis)
        self.assertEqual(draft.provider, 'rule_based')
        self.assertGreaterEqual(len(draft.tips), 8)

    def test_parse_draft_accepts_valid_payload(self):
        raw = {
            'summary': 'Plan summary.',
            'skin_type': 'oily',
            'primary_concerns': ['acne'],
            'recommended_frequency': 'SPF daily',
            'tips': [{
                'period': 'morning',
                'sort_order': 1,
                'title': 'Cleanse',
                'description': 'Use a gentle cleanser.',
                'priority': 'high',
                'category': 'cleanser',
                'key_ingredients': ['glycerin'],
                'avoid_ingredients': [],
                'related_service_slug': None,
            }],
        }
        draft = LLMTipsProvider()._parse_draft(raw, make_mock_analysis())
        self.assertEqual(draft.provider, 'llm')
        self.assertEqual(draft.skin_type, 'oily')
        self.assertEqual(draft.tips[0]['related_service_slug'], '')

    def test_parse_draft_accepts_json_string_and_coerces_enums(self):
        raw = json.dumps({
            'summary': 'S',
            'skin_type': 'wrong-type',
            'tips': [{'title': 'T', 'description': 'D', 'period': 'never', 'priority': 'asap', 'category': 'zzz'}],
        })
        draft = LLMTipsProvider()._parse_draft(raw, make_mock_analysis())
        self.assertEqual(draft.skin_type, 'normal')
        self.assertEqual(draft.tips[0]['period'], 'lifestyle')
        self.assertEqual(draft.tips[0]['priority'], 'medium')
        self.assertEqual(draft.tips[0]['category'], 'lifestyle')
        self.assertEqual(draft.tips[0]['sort_order'], 1)

    def test_parse_draft_rejects_missing_tips(self):
        with self.assertRaises(ValueError):
            LLMTipsProvider()._parse_draft({'summary': 'no tips key'}, make_mock_analysis())
        with self.assertRaises(ValueError):
            LLMTipsProvider()._parse_draft({'tips': 'not-a-list'}, make_mock_analysis())
        with self.assertRaises(ValueError):
            LLMTipsProvider()._parse_draft({'tips': [{'period': 'morning'}]}, make_mock_analysis())
        with self.assertRaises(ValueError):
            LLMTipsProvider()._parse_draft(['not', 'dict'], make_mock_analysis())

    @override_settings(FACE_ANALYZER_LLM_API_KEY='')
    def test_call_llm_requires_api_key(self):
        with self.assertRaises(RuntimeError):
            LLMTipsProvider()._call_llm(make_mock_analysis())

    @override_settings(FACE_ANALYZER_LLM_API_KEY='k', FACE_ANALYZER_LLM_PROVIDER='bogus')
    def test_call_llm_rejects_unknown_provider(self):
        with self.assertRaises(RuntimeError) as ctx:
            LLMTipsProvider()._call_llm(make_mock_analysis())
        self.assertIn('bogus', str(ctx.exception))


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class TipsPersistenceTests(TestCase):
    def setUp(self):
        self.analysis = self.create_analysis()

    @staticmethod
    def create_analysis(concerns=None):
        return FaceAnalysis.objects.create(
            image=_analysis_image(),
            overall_score=7.8,
            symmetry_score=8.2,
            skin_clarity_score=7.5,
            youthfulness_score=8.0,
            harmony_score=7.6,
            detected_attributes={
                'face_shape': 'oval',
                'skin_tone': 'medium',
                'skin_undertone': 'warm',
                'eye_shape': 'almond',
                'lip_fullness': 'medium',
                'concerns': list(concerns or ['enlarged_pores', 'dullness']),
            },
            suggestions=[{'category': 'skincare', 'title': 'Routine', 'detail': 'Keep it consistent.'}],
            raw_model_output={'method': 'test'},
            provider='local',
            model_version='test-v1',
        )

    def test_generate_and_store_plan_creates_and_replaces_tips(self):
        plan = generate_and_store_plan(self.analysis)
        count = SkinCareTip.objects.filter(analysis=self.analysis).count()
        self.assertGreater(count, 0)
        self.assertEqual(plan.analysis.pk, self.analysis.pk)
        self.assertGreater(len(list(plan.analysis.skin_tips.all())), 0)

        again = generate_and_store_plan(self.analysis)
        self.assertEqual(again.pk, plan.pk)
        self.assertEqual(SkinCareTip.objects.filter(analysis=self.analysis).count(), count)

    def test_generate_and_store_plan_resolves_service_names(self):
        service = Service.objects.create(name='Hydrafacial', price_usd=120, is_active=True)
        inactive = Service.objects.create(name='Chemical Peel', price_usd=90, is_active=False)

        plan = generate_and_store_plan(self.analysis)
        hydra_tip = SkinCareTip.objects.get(analysis=self.analysis, related_service_slug='hydrafacial')
        self.assertEqual(hydra_tip.related_service, service)

        peel_tip = SkinCareTip.objects.get(analysis=self.analysis, related_service_slug='chemical-peel')
        self.assertIsNone(peel_tip.related_service)  # inactive services are skipped
        self.assertEqual(inactive.is_active, False)

        payload = SkinCarePlanSerializer_data(plan)
        self.assertEqual(payload['provider'], 'rule_based')
        self.assertTrue(payload['primary_concerns'])
        self.assertIn(payload['skin_type'], {'oily', 'dry', 'combination', 'normal'})

    def test_resolve_services_maps_slugs(self):
        service = Service.objects.create(name='IPL', price_usd=200, is_active=True)
        mapping = _resolve_services({'ipl', 'nope', ''})
        self.assertEqual(mapping['ipl'], service)
        self.assertIsNone(mapping['nope'])
        self.assertNotIn('', mapping)
        self.assertEqual(_resolve_services(set()), {})

    def test_build_prompt_uses_derived_data_only(self):
        prompt = LLMTipsProvider()._build_prompt(self.analysis)
        self.assertIn('"scores"', prompt)
        self.assertIn('"attributes"', prompt)
        self.assertIn('never mention or request the raw image', prompt)
        self.assertIn('Return ONLY minified JSON', prompt)
        self.assertNotIn('base64', prompt)

        Service.objects.create(name='Microneedling', price_usd=150, is_active=True)
        prompt_with_services = LLMTipsProvider()._build_prompt(self.analysis)
        self.assertIn('Microneedling', prompt_with_services)


def _analysis_image():
    from django.core.files.uploadedfile import SimpleUploadedFile

    buffer = io.BytesIO()
    Image.new('RGB', (96, 96), (198, 152, 126)).save(buffer, format='PNG')
    return SimpleUploadedFile('analysis.png', buffer.getvalue(), content_type='image/png')


def SkinCarePlanSerializer_data(plan):
    from face_analyzer.serializers import SkinCarePlanSerializer

    return SkinCarePlanSerializer(plan).data
