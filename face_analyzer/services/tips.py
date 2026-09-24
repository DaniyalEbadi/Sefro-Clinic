"""Skin-care plan generation: rule-based (default) + optional LLM provider.

``generate_and_store_plan`` is the single persistence entry point: it
upserts the SkinCarePlan, replaces all SkinCareTip rows for the analysis and
resolves each tip's ``related_service_slug`` to a customers.Service FK.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from ..models import SkinCarePlan, SkinCareTip
from .analyzer import sanitize_structure, sanitize_text

PERIODS = ('morning', 'evening', 'weekly', 'lifestyle', 'professional')
VALID_PERIODS = frozenset(PERIODS)
VALID_PRIORITIES = frozenset({'low', 'medium', 'high'})
VALID_CATEGORIES = frozenset({
    'cleanser', 'toner', 'serum', 'moisturizer', 'sunscreen', 'exfoliant',
    'mask', 'eye_care', 'treatment', 'lifestyle', 'diet', 'in_clinic',
})
ACTIVE_CONCERNS = frozenset({'hyperpigmentation', 'acne', 'fine_lines', 'dullness', 'enlarged_pores'})


@dataclass
class SkinCarePlanDraft:
    summary: str
    skin_type: str                 # oily | dry | combination | normal
    primary_concerns: list[str]
    recommended_frequency: str
    tips: list[dict]               # period/sort_order/title/description/priority/category/ingredients/slug
    provider: str                  # "rule_based" | "llm"
    model_used: str


class SkinCareTipsProvider(ABC):
    """Interface every skin-care tips provider must implement."""

    @abstractmethod
    def generate(self, analysis) -> SkinCarePlanDraft:
        raise NotImplementedError


# Rule templates keyed by (concern, period). 'baseline' rows always run.
RULES: dict = {
    ('baseline', 'morning'): [
        {'title': 'Gentle morning cleanser', 'description': 'Wash with a mild sulfate-free cleanser to start the day without stripping the skin.', 'priority': 'high', 'category': 'cleanser', 'key_ingredients': ['glycerin'], 'avoid_ingredients': ['sulfates'], 'related_service_slug': ''},
        {'title': 'Broad-spectrum SPF 50', 'description': 'Apply SPF 50 as the last morning step; reapply every two hours when outdoors.', 'priority': 'high', 'category': 'sunscreen', 'key_ingredients': ['zinc oxide'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('baseline', 'evening'): [
        {'title': 'Double cleanse', 'description': 'Melt away sunscreen with an oil cleanser, then follow with a gentle water-based cleanser.', 'priority': 'high', 'category': 'cleanser', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': ''},
        {'title': 'Night moisturizer', 'description': 'Seal the evening routine with a moisturizer matched to your skin type.', 'priority': 'high', 'category': 'moisturizer', 'key_ingredients': ['ceramides'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('hyperpigmentation', 'morning'): [
        {'title': 'Vitamin C serum', 'description': 'Apply a vitamin C serum before sunscreen to brighten dark spots and block new pigment.', 'priority': 'high', 'category': 'serum', 'key_ingredients': ['vitamin C'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('hyperpigmentation', 'evening'): [
        {'title': 'Retinoid for dark spots', 'description': 'Use a pea-sized amount of retinoid at night, building up frequency gradually.', 'priority': 'high', 'category': 'treatment', 'key_ingredients': ['retinoid'], 'avoid_ingredients': [], 'related_service_slug': ''},
        {'title': 'Tranexamic acid treatment', 'description': 'A tranexamic-acid serum at night helps fade stubborn post-acne marks.', 'priority': 'medium', 'category': 'serum', 'key_ingredients': ['tranexamic acid'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('hyperpigmentation', 'professional'): [
        {'title': 'In-clinic IPL', 'description': 'Professional IPL sessions target deeper pigment that topical products cannot reach.', 'priority': 'medium', 'category': 'in_clinic', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': 'ipl'},
    ],
    ('acne', 'morning'): [
        {'title': 'Niacinamide serum', 'description': 'A 5-10% niacinamide serum in the morning regulates oil and calms breakout inflammation.', 'priority': 'high', 'category': 'serum', 'key_ingredients': ['niacinamide'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('acne', 'evening'): [
        {'title': 'Salicylic acid or benzoyl peroxide', 'description': 'Alternate a BHA cleanser with benzoyl peroxide at night to keep pores clear.', 'priority': 'high', 'category': 'treatment', 'key_ingredients': ['salicylic acid', 'benzoyl peroxide'], 'avoid_ingredients': ['comedogenic oils'], 'related_service_slug': ''},
    ],
    ('acne', 'weekly'): [
        {'title': 'Clay mask', 'description': 'Use a clay mask once a week on oily zones to absorb excess sebum.', 'priority': 'low', 'category': 'mask', 'key_ingredients': ['kaolin clay'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('acne', 'lifestyle'): [
        {'title': 'Low-glycemic meals', 'description': 'Reduce high-glycemic snacks and dairy-heavy meals, which can aggravate breakouts.', 'priority': 'medium', 'category': 'diet', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('acne', 'professional'): [
        {'title': 'In-clinic extraction', 'description': 'Have inflamed comedones professionally extracted to avoid scarring from at-home picking.', 'priority': 'medium', 'category': 'in_clinic', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': 'extraction'},
    ],
    ('redness', 'morning'): [
        {'title': 'Azelaic acid', 'description': 'Azelaic acid evens tone and reduces visible redness without irritation.', 'priority': 'medium', 'category': 'serum', 'key_ingredients': ['azelaic acid'], 'avoid_ingredients': ['fragrance'], 'related_service_slug': ''},
    ],
    ('redness', 'evening'): [
        {'title': 'Centella moisturizer', 'description': 'A centella asiatica cream soothes reactive skin overnight.', 'priority': 'medium', 'category': 'moisturizer', 'key_ingredients': ['centella asiatica'], 'avoid_ingredients': ['alcohol denat'], 'related_service_slug': ''},
    ],
    ('redness', 'lifestyle'): [
        {'title': 'Avoid fragrance and harsh scrubbing', 'description': 'Skip fragranced products and physical scrubs while the skin barrier is reactive.', 'priority': 'high', 'category': 'lifestyle', 'key_ingredients': [], 'avoid_ingredients': ['fragrance', 'physical scrubs'], 'related_service_slug': ''},
    ],
    ('dark_circles', 'morning'): [
        {'title': 'Caffeine eye cream', 'description': 'Tap a caffeine eye cream around the orbital bone each morning to depuff and brighten.', 'priority': 'medium', 'category': 'eye_care', 'key_ingredients': ['caffeine'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('dark_circles', 'lifestyle'): [
        {'title': 'Sleep hygiene', 'description': 'Aim for 7-8 hours of sleep and keep a consistent schedule to reduce shadowing.', 'priority': 'high', 'category': 'lifestyle', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('dark_circles', 'professional'): [
        {'title': 'In-clinic carboxy therapy', 'description': 'Carboxy therapy improves under-eye microcirculation for vascular dark circles.', 'priority': 'low', 'category': 'in_clinic', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': 'carboxy-therapy'},
    ],
    ('fine_lines', 'morning'): [
        {'title': 'Peptide serum', 'description': 'A peptide serum in the morning supports collagen and softens fine lines over time.', 'priority': 'medium', 'category': 'serum', 'key_ingredients': ['peptides'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('fine_lines', 'evening'): [
        {'title': 'Retinol at night', 'description': 'Start retinol twice weekly at night and increase as tolerated; always pair with SPF.', 'priority': 'high', 'category': 'treatment', 'key_ingredients': ['retinol'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('fine_lines', 'professional'): [
        {'title': 'In-clinic microneedling', 'description': 'Microneedling or RF microneedling stimulates collagen in the dermis for deeper lines.', 'priority': 'medium', 'category': 'in_clinic', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': 'microneedling'},
    ],
    ('dryness', 'morning'): [
        {'title': 'Hyaluronic acid serum', 'description': 'Apply hyaluronic acid to damp skin, then moisturize, to lock in hydration.', 'priority': 'high', 'category': 'serum', 'key_ingredients': ['hyaluronic acid'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('dryness', 'evening'): [
        {'title': 'Ceramide moisturizer', 'description': 'A ceramide-rich cream repairs the lipid barrier overnight.', 'priority': 'high', 'category': 'moisturizer', 'key_ingredients': ['ceramides'], 'avoid_ingredients': [], 'related_service_slug': ''},
        {'title': 'Occlusive layer', 'description': 'On very dry nights, seal everything with a thin occlusive layer such as petrolatum.', 'priority': 'medium', 'category': 'treatment', 'key_ingredients': ['petrolatum'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('dryness', 'lifestyle'): [
        {'title': 'Humidify and hydrate', 'description': 'Run a bedroom humidifier in dry seasons and drink water consistently through the day.', 'priority': 'medium', 'category': 'lifestyle', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('oiliness', 'morning'): [
        {'title': 'Niacinamide for sebum control', 'description': 'Morning niacinamide visibly reduces shine by regulating sebum production.', 'priority': 'medium', 'category': 'serum', 'key_ingredients': ['niacinamide'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('oiliness', 'evening'): [
        {'title': 'Oil-free moisturizer', 'description': 'Even oily skin needs moisture; choose a lightweight oil-free gel-cream.', 'priority': 'medium', 'category': 'moisturizer', 'key_ingredients': ['glycerin'], 'avoid_ingredients': ['coconut oil'], 'related_service_slug': ''},
    ],
    ('oiliness', 'weekly'): [
        {'title': 'Weekly clay mask', 'description': 'A clay mask once a week absorbs excess oil without over-drying.', 'priority': 'low', 'category': 'mask', 'key_ingredients': ['kaolin clay'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('oiliness', 'lifestyle'): [
        {'title': 'Blot, do not over-wash', 'description': 'Use blotting papers midday instead of washing more than twice daily.', 'priority': 'low', 'category': 'lifestyle', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('enlarged_pores', 'morning'): [
        {'title': 'Niacinamide toner', 'description': 'A niacinamide toner refines the appearance of pores throughout the day.', 'priority': 'medium', 'category': 'toner', 'key_ingredients': ['niacinamide'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('enlarged_pores', 'weekly'): [
        {'title': 'BHA exfoliant', 'description': 'A leave-on BHA twice weekly clears the inside of pores so they look smaller.', 'priority': 'high', 'category': 'exfoliant', 'key_ingredients': ['salicylic acid'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('enlarged_pores', 'professional'): [
        {'title': 'In-clinic hydrafacial', 'description': 'A professional hydrafacial deeply vacuums and hydrates congested pores.', 'priority': 'medium', 'category': 'in_clinic', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': 'hydrafacial'},
    ],
    ('dullness', 'morning'): [
        {'title': 'Vitamin C for glow', 'description': 'Morning vitamin C restores radiance and defends against oxidative dulling.', 'priority': 'medium', 'category': 'serum', 'key_ingredients': ['vitamin C'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('dullness', 'weekly'): [
        {'title': 'Weekly AHA polish', 'description': 'A glycolic or lactic acid weekly dissolves the dull surface cell layer.', 'priority': 'high', 'category': 'exfoliant', 'key_ingredients': ['glycolic acid', 'lactic acid'], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('dullness', 'lifestyle'): [
        {'title': 'Antioxidant-rich diet', 'description': 'Eat colorful fruit and vegetables daily; omega-3s support a lit-from-within glow.', 'priority': 'low', 'category': 'diet', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': ''},
    ],
    ('dullness', 'professional'): [
        {'title': 'In-clinic chemical peel', 'description': 'A light professional peel resurfaces dull skin with controlled exfoliation.', 'priority': 'medium', 'category': 'in_clinic', 'key_ingredients': [], 'avoid_ingredients': [], 'related_service_slug': 'chemical-peel'},
    ],
}


def derive_skin_type(concerns: list) -> str:
    """Derive skin type from oiliness/dryness concern flags."""
    oily = 'oiliness' in concerns
    dry = 'dryness' in concerns
    if oily and dry:
        return 'combination'
    if oily:
        return 'oily'
    if dry:
        return 'dry'
    return 'normal'


def recommended_frequency(concerns: list) -> str:
    """Derive actives frequency from how many active-treatment concerns are flagged."""
    actives = len([concern for concern in concerns if concern in ACTIVE_CONCERNS])
    if actives == 0:
        return 'Daily SPF with gentle hydration'
    if actives <= 2:
        return 'SPF daily, actives 2x weekly'
    return 'SPF daily, actives 3x weekly'


def build_summary(skin_type: str, primary_concerns: list, overall_score: float) -> str:
    """1-2 sentence narrative from skin type + top concerns + overall score band."""
    if overall_score >= 8.5:
        band = 'excellent'
    elif overall_score >= 7.0:
        band = 'good'
    elif overall_score >= 5.0:
        band = 'fair'
    else:
        band = 'needs attention'
    if primary_concerns:
        concerns_text = ', '.join(primary_concerns[:3])
        return (
            f'Your {skin_type} skin shows {concerns_text}. '
            f'Overall aesthetic score {overall_score:.1f}/10 ({band}).'
        )
    return (
        f'Your {skin_type} skin looks balanced with no major concerns. '
        f'Overall aesthetic score {overall_score:.1f}/10 ({band}).'
    )


class RuleBasedTipsProvider(SkinCareTipsProvider):
    """Deterministic rule engine: same analysis always yields the same draft."""

    def generate(self, analysis) -> SkinCarePlanDraft:
        attributes = analysis.detected_attributes if isinstance(analysis.detected_attributes, dict) else {}
        concerns = [str(item) for item in (attributes.get('concerns') or [])]
        skin_type = derive_skin_type(concerns)
        primary_concerns = concerns[:3]

        tips: list = []

        def emit(key):
            for template in RULES.get(key, ()):
                tips.append({**template, 'period': key[1], 'sort_order': len(tips) + 1})

        emit(('baseline', 'morning'))
        emit(('baseline', 'evening'))
        for concern in concerns:
            for period in PERIODS:
                emit((concern, period))

        return SkinCarePlanDraft(
            summary=build_summary(skin_type, primary_concerns, float(analysis.overall_score)),
            skin_type=skin_type,
            primary_concerns=primary_concerns,
            recommended_frequency=recommended_frequency(concerns),
            tips=tips,
            provider='rule_based',
            model_used='sefro-rules-v1',
        )


class LLMTipsProvider(SkinCareTipsProvider):
    """Optional LLM provider; any failure silently falls back to the rule engine."""

    def generate(self, analysis) -> SkinCarePlanDraft:
        try:
            raw = self._call_llm(analysis)
            draft = self._parse_draft(raw, analysis)
            draft.provider = 'llm'
            return draft
        except Exception:
            fallback = RuleBasedTipsProvider().generate(analysis)
            fallback.provider = 'rule_based'
            return fallback

    def _build_prompt(self, analysis) -> str:
        from customers.models import Service

        attributes = analysis.detected_attributes if isinstance(analysis.detected_attributes, dict) else {}
        scores = {
            'overall_score': analysis.overall_score,
            'symmetry_score': analysis.symmetry_score,
            'skin_clarity_score': analysis.skin_clarity_score,
            'youthfulness_score': analysis.youthfulness_score,
            'harmony_score': analysis.harmony_score,
        }
        services = list(
            Service.objects.filter(is_active=True).values('id', 'name', 'price_usd', 'category__name')
        )
        payload = {'attributes': attributes, 'scores': scores, 'services': services}
        schema = (
            '{"summary": str, "skin_type": "oily|dry|combination|normal", '
            '"primary_concerns": [str], "recommended_frequency": str, '
            '"tips": [{"period": "morning|evening|weekly|lifestyle|professional", '
            '"sort_order": int, "title": str, "description": str, '
            '"priority": "low|medium|high", '
            '"category": "cleanser|toner|serum|moisturizer|sunscreen|exfoliant|mask|eye_care|treatment|lifestyle|diet|in_clinic", '
            '"key_ingredients": [str], "avoid_ingredients": [str], "related_service_slug": str|null}]}'
        )
        return (
            'You are a clinic skincare expert. Return ONLY minified JSON matching this schema: '
            f'{schema}\n'
            'Work only from the derived attributes below; never mention or request the raw image. '
            f'Data: {json.dumps(payload, default=str)}'
        )

    def _call_llm(self, analysis) -> dict:
        provider = (getattr(settings, 'FACE_ANALYZER_LLM_PROVIDER', 'openai') or 'openai').strip().lower()
        if provider not in {'openai', 'anthropic'}:
            raise RuntimeError(f'Unsupported FACE_ANALYZER_LLM_PROVIDER {provider!r} (use openai | anthropic).')
        api_key = (getattr(settings, 'FACE_ANALYZER_LLM_API_KEY', '') or '').strip()
        if not api_key:
            raise RuntimeError('FACE_ANALYZER_LLM_API_KEY is not configured.')
        model = getattr(settings, 'FACE_ANALYZER_LLM_MODEL', 'gpt-4o-mini')
        timeout = int(getattr(settings, 'FACE_ANALYZER_LLM_TIMEOUT', 30) or 30)
        prompt = self._build_prompt(analysis)
        if provider == 'openai':
            import openai

            client = openai.OpenAI(api_key=api_key, timeout=timeout)
            response = client.chat.completions.create(
                model=model,
                messages=[{'role': 'user', 'content': prompt}],
                response_format={'type': 'json_object'},
            )
            return json.loads(response.choices[0].message.content)
        if provider == 'anthropic':
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{'role': 'user', 'content': prompt}],
            )
            return json.loads(response.content[0].text)
        raise RuntimeError(f'Unsupported FACE_ANALYZER_LLM_PROVIDER {provider!r} (use openai | anthropic).')

    def _parse_draft(self, raw, analysis) -> SkinCarePlanDraft:
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise ValueError('LLM response is not a JSON object.')
        tips = []
        if not isinstance(raw.get('tips'), list):
            raise ValueError('LLM response missing tips list.')
        for index, item in enumerate(raw['tips'], start=1):
            if not isinstance(item, dict):
                raise ValueError('LLM tip is not an object.')
            period = str(item.get('period') or 'lifestyle')
            if period not in VALID_PERIODS:
                period = 'lifestyle'
            priority = str(item.get('priority') or 'medium')
            if priority not in VALID_PRIORITIES:
                priority = 'medium'
            category = str(item.get('category') or 'lifestyle')
            if category not in VALID_CATEGORIES:
                category = 'lifestyle'
            title = str(item.get('title') or '').strip()
            description = str(item.get('description') or '').strip()
            if not title or not description:
                raise ValueError('LLM tip missing title/description.')
            slug = item.get('related_service_slug')
            tips.append({
                'period': period,
                'sort_order': int(item.get('sort_order') or index),
                'title': title,
                'description': description,
                'priority': priority,
                'category': category,
                'key_ingredients': [str(v) for v in (item.get('key_ingredients') or [])],
                'avoid_ingredients': [str(v) for v in (item.get('avoid_ingredients') or [])],
                'related_service_slug': str(slug) if slug else '',
            })
        skin_type = str(raw.get('skin_type') or 'normal')
        if skin_type not in {'oily', 'dry', 'combination', 'normal'}:
            skin_type = 'normal'
        concerns = raw.get('primary_concerns')
        if not isinstance(concerns, list):
            concerns = []
        return SkinCarePlanDraft(
            summary=str(raw.get('summary') or ''),
            skin_type=skin_type,
            primary_concerns=[str(c) for c in concerns],
            recommended_frequency=str(raw.get('recommended_frequency') or 'SPF daily'),
            tips=tips,
            provider='llm',
            model_used=str(getattr(settings, 'FACE_ANALYZER_LLM_MODEL', 'gpt-4o-mini'))[:64],
        )


_tips_provider_cache: dict = {}


def get_tips_provider() -> SkinCareTipsProvider:
    """Build (and cache) the tips provider selected by FACE_ANALYZER_TIPS_PROVIDER."""
    name = (getattr(settings, 'FACE_ANALYZER_TIPS_PROVIDER', 'rule_based') or 'rule_based').strip().lower()
    cached = _tips_provider_cache.get(name)
    if cached is not None:
        return cached
    provider = LLMTipsProvider() if name == 'llm' else RuleBasedTipsProvider()
    _tips_provider_cache[name] = provider
    return provider


def _sanitize_tip(tip: dict) -> dict:
    period = tip.get('period') if tip.get('period') in VALID_PERIODS else 'lifestyle'
    priority = tip.get('priority') if tip.get('priority') in VALID_PRIORITIES else 'medium'
    category = tip.get('category') if tip.get('category') in VALID_CATEGORIES else 'lifestyle'
    try:
        sort_order = int(tip.get('sort_order') or 0)
    except (TypeError, ValueError):
        sort_order = 0
    return {
        'period': period,
        'sort_order': max(0, sort_order),
        'title': sanitize_text(tip.get('title') or '')[:200],
        'description': sanitize_text(tip.get('description') or ''),
        'priority': priority,
        'category': category,
        'key_ingredients': sanitize_structure(list(tip.get('key_ingredients') or [])),
        'avoid_ingredients': sanitize_structure(list(tip.get('avoid_ingredients') or [])),
        'related_service_slug': sanitize_text(tip.get('related_service_slug') or '')[:100],
    }


def _resolve_services(slugs: set) -> dict:
    """Map each non-empty slug to an active Service (slug field or case-insensitive name)."""
    from customers.models import Service

    mapping = {}
    if not slugs:
        return mapping
    active = Service.objects.filter(is_active=True)
    has_slug_field = any(field.name == 'slug' for field in Service._meta.get_fields())
    for slug in slugs:
        if not slug:
            continue
        if has_slug_field:
            mapping[slug] = active.filter(slug=slug).first()
        else:
            spaced = slug.replace('-', ' ')
            mapping[slug] = active.filter(name__iexact=spaced).first() or active.filter(name__iexact=slug).first()
    return mapping


@transaction.atomic
def generate_and_store_plan(analysis) -> SkinCarePlan:
    """Generate a draft, upsert the plan, replace tips and resolve service FKs.

    Returns the plan with analysis + skin_tips prefetched.
    """
    draft = get_tips_provider().generate(analysis)
    plan, _created = SkinCarePlan.objects.update_or_create(
        analysis=analysis,
        defaults={
            'summary': sanitize_text(draft.summary),
            'skin_type': draft.skin_type,
            'primary_concerns': sanitize_structure(list(draft.primary_concerns)),
            'recommended_frequency': sanitize_text(draft.recommended_frequency)[:120],
            'provider': draft.provider if draft.provider in {'rule_based', 'llm'} else 'rule_based',
            'model_used': sanitize_text(draft.model_used)[:64],
        },
    )
    SkinCareTip.objects.filter(analysis=analysis).delete()
    tips = [_sanitize_tip(tip) for tip in draft.tips]
    service_map = _resolve_services({tip['related_service_slug'] for tip in tips})
    SkinCareTip.objects.bulk_create([
        SkinCareTip(
            analysis=analysis,
            plan=plan,
            period=tip['period'],
            sort_order=tip['sort_order'],
            title=tip['title'],
            description=tip['description'],
            priority=tip['priority'],
            category=tip['category'],
            key_ingredients=tip['key_ingredients'],
            avoid_ingredients=tip['avoid_ingredients'],
            related_service_slug=tip['related_service_slug'],
            related_service=service_map.get(tip['related_service_slug']),
        )
        for tip in tips
    ])
    return (
        SkinCarePlan.objects
        .select_related('analysis')
        .prefetch_related('analysis__skin_tips')
        .get(pk=plan.pk)
    )
