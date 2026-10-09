"""Evidence questionnaire v2. Project heuristics, not diagnostic cut-offs.

Source: donotstress_question_evidence.docx, 9 October 2026, section 2.
Raw responses keep each instrument's direction. Never convert legacy /10
records into PSS scores. Optional PAS/MSPSS items are contextual indicators.
"""
import math
import re

VERSION = "evidence-v2"
PSS_OPTIONS = ["Never", "Almost Never", "Sometimes", "Fairly Often", "Very Often"]
SLEEP_OPTIONS = ["Very good", "Fairly good", "Fairly bad", "Very bad"]
PAS_OPTIONS = ["Strongly disagree", "Disagree", "Neither agree nor disagree", "Agree", "Strongly agree"]
SUPPORT_OPTIONS = ["Very Strongly Disagree", "Strongly Disagree", "Mildly Disagree", "Neutral", "Mildly Agree", "Strongly Agree", "Very Strongly Agree"]

def question(key, label, prompt, minimum, maximum, options=None, **extra):
    return dict(key=key, label=label, prompt=prompt, min=minimum, max=maximum,
                step=extra.pop('step', 1), options=options, **extra)

QUESTIONS = [
    question('pss_1', 'Feeling in control', 'In the last month, how often have you felt that you were unable to control the important things in your life?', 0, 4, PSS_OPTIONS),
    question('pss_2', 'Handling personal problems', 'In the last month, how often have you felt confident about your ability to handle your personal problems?', 0, 4, PSS_OPTIONS),
    question('pss_3', 'Things going your way', 'In the last month, how often have you felt that things were going your way?', 0, 4, PSS_OPTIONS),
    question('pss_4', 'Difficulties piling up', 'In the last month, how often have you felt difficulties were piling up so high that you could not overcome them?', 0, 4, PSS_OPTIONS),
    question('sleep_hours_avg', 'Typical sleep · past week', 'During the past week, how many hours of actual sleep did you get on a typical night? (This may be different than the number of hours you spend in bed.)', 0, 14, step=0.5, kind='slider', default=7, low='0 hours', high='14 hours', unit='hours'),
    question('sleep_quality', 'Sleep quality · past week', 'During the past week, how would you rate your sleep quality overall?', 0, 3, SLEEP_OPTIONS),
    question('pas_workload', 'Study workload', 'I believe that the amount of work assignment is too much', 1, 5, PAS_OPTIONS),
    question('pas_catchup', 'Catching up · optional', 'Am unable to catch up if getting behind the work', 1, 5, PAS_OPTIONS, optional=True),
    question('fin_stress', 'Personal finances', 'How stressed do you feel about your personal finances in general?', 1, 10, kind='slider', default=5, low='Overwhelming stress', high='No stress at all', unit='out of 10'),
    question('mspss_friends', 'Support from friends', 'I can count on my friends when things go wrong.', 1, 7, SUPPORT_OPTIONS),
    question('mspss_family', 'Support from family', 'I get the emotional help & support I need from my family.', 1, 7, SUPPORT_OPTIONS),
    question('mspss_so', 'A special person · optional', 'There is a special person who is around when I am in need.', 1, 7, SUPPORT_OPTIONS, optional=True),
]
QUESTION_MAP = {q['key']: q for q in QUESTIONS}
SECTIONS = [
    dict(title='Your month', heading='Start with the bigger picture.', period='Think about the last month',
         intro='Notice how manageable life has felt, including moments when things went well. Choose how often each experience happened.',
         why='These four questions explore perceived stress: how unpredictable, difficult to control, or overwhelming life has felt. Together they give more context than one stress rating.',
         source='PSS-4 · Cohen, Kamarck & Mermelstein (1983)', keys=['pss_1','pss_2','pss_3','pss_4']),
    dict(title='Rest & recovery', heading='How has your sleep been?', period='Think about the past week',
         intro='Now zoom in on your recent routine. Think about a typical night, rather than only last night.',
         why='Sleep and stress can affect one another. Hours and quality capture different parts of rest; either can help explain why daily demands feel harder to manage.',
         source='Two items adapted from PSQI · Buysse et al. (1989). This is not a full PSQI score.', keys=['sleep_hours_avg','sleep_quality']),
    dict(title='Study demands', heading='Make room for your study load.', period='Your current study experience',
         intro='With your overall feelings and rest in mind, consider the demands of your coursework.',
         why='Feeling overloaded by assignments can add pressure and reduce time for recovery. This question identifies a possible source of strain, rather than judging your academic performance.',
         source='Selected PAS items · Bedewy & Gabriel (2015), CC BY-NC 3.0. Response direction adapted.', keys=['pas_workload','pas_catchup']),
    dict(title='Money pressures', heading='Life outside the timetable.', period='Your personal finances in general',
         intro='Everyday expenses can take up mental space too. You do not need to share amounts or financial details.',
         why='Financial worries may compete for attention alongside study demands. This question helps us suggest relevant support without assuming your income or circumstances.',
         source='IFDFW item 8 · Prawitz et al. (2006). Higher numbers mean less financial distress.', keys=['fin_stress']),
    dict(title='Your support', heading='Who can you lean on?', period='The support available to you',
         intro='After looking at pressures, consider the people who help you face them. Friends and family may support you in different ways.',
         why='Support can make stressful experiences easier to navigate. These questions look at sources of support; they do not cancel out or invalidate the stress you reported.',
         source='Selected MSPSS items · Zimet et al. (1988). These items are not a validated short-form scale.', keys=['mspss_friends','mspss_family','mspss_so']),
    dict(title='A moment to reflect', heading='Anything else on your mind?', period='Optional · not scored',
         intro='Numbers cannot capture everything. You can reflect here, or continue without writing anything.',
         why='Your reflection does not contribute to the stress score. A basic safety check can highlight support, but it cannot recognise every situation. You can contact support at any time.',
         source='Optional reflection · team wording', keys=[]),
]

# Shared with the browser for an immediate, conservative support prompt.
# Keywords can give false positives/negatives; never claim to assess safety.
SAFETY_PATTERNS = [r"\bsuicid(?:e|al)\b", r"\bself[ -]?harm(?:ing)?\b",
    r"\b(?:kill|hurt|harm|cut)(?:ing)? myself\b", r"\b(?:end|take) my (?:own )?life\b",
    r"\b(?:want|wish|going|plan|planning) to die\b", r"\b(?:cannot|can't|dont|don't) (?:go on|keep myself safe|want to live)\b",
    r"\bbetter off dead\b", r"\b(?:took|taken|take) an overdose\b"]

def safety_check(text):
    text = str(text or '').lower().replace('’', "'")
    return any(re.search(pattern, text) for pattern in SAFETY_PATTERNS)

def validate_question(raw, q):
    if raw is None or str(raw).strip() == '':
        return (True, None) if q.get('optional') else (False, 'Please answer this question.')
    if isinstance(raw, (bool, list, dict)):
        return False, 'Choose one of the available answers.'
    try:
        value = float(raw)
    except (ValueError, TypeError, OverflowError):
        return False, 'Choose a number in the available range.'
    if not math.isfinite(value) or not q['min'] <= value <= q['max'] or not (value / q['step']).is_integer():
        return False, f"Choose {q['min']} to {q['max']} in steps of {q['step']}."
    return True, value if q['step'] == 0.5 else int(value)

def score(record):
    """Score validated v2 inputs only; no AI or free-text sentiment scoring."""
    total = record['pss_1'] + (4-record['pss_2']) + (4-record['pss_3']) + record['pss_4']
    support = [record[k] for k in ('mspss_friends','mspss_family','mspss_so') if record.get(k) is not None]
    mean = sum(support) / len(support)
    flags = {
        'sleep': record['sleep_hours_avg'] < 6 or record['sleep_quality'] >= 2,
        'workload': record['pas_workload'] >= 4,
        'finances': record['fin_stress'] <= 4,
        'support': mean < 3,
    }
    band = 2 if total >= 12 else 1 if total >= 8 else 0
    if sum(flags.values()) >= 2:
        band = max(band, 1)
    if record.get('safety_flag') is True:
        band = 2
    return dict(pss_total=total, support_mean=round(mean, 2), support_item_count=len(support),
                context_flags=flags, risk_category=['Low','Moderate','High'][band],
                soft_label=["You're doing ok", 'Worth a check-in', 'Please reach out'][band],
                speak_prominence=['low','medium','high'][band])

def explanation(record, scores):
    total = scores['pss_total']
    text = f'Your four answers about the last month give a perceived-stress score of {total} out of 16. Higher scores reflect more perceived stress.'
    if record.get('safety_flag'):
        text += ' Your reflection prompted us to highlight support. This does not change your PSS score and is not a diagnosis.'
    elif total >= 12:
        text += ' The project uses scores of 12 or above to encourage reaching out to someone for support.'
    elif total >= 8:
        text += ' The project uses scores from 8 to 11 to suggest a check-in with someone you trust.'
    elif sum(scores['context_flags'].values()) >= 2:
        text += ' Although your stress score is below 8, two or more contextual concerns suggest a conversation could help.'
    else:
        text += ' Your answers fall in the lower project band. You can still ask for support whenever you need it.'
    return text + ' These bands are team heuristics, not clinical cut-offs; PSS-4 has no official diagnostic thresholds.'

def factor_insights(record, scores):
    flags = scores['context_flags']
    return [
        dict(title='Rest & recovery', flagged=flags['sleep'], value=f"{record['sleep_hours_avg']:g} hours · {SLEEP_OPTIONS[record['sleep_quality']]}",
             text='Short or unsatisfying sleep can make daily demands harder to manage. Stress may also disrupt sleep. The project flags under 6 hours or fairly/very bad quality.'),
        dict(title='Study demands', flagged=flags['workload'], value=f"{record['pas_workload']}/5 · {PAS_OPTIONS[record['pas_workload']-1]}",
             text='Feeling overloaded may leave less room for rest. Agreeing that assignments are too much raises a workload flag. The optional catch-up answer adds context, not another flag.'),
        dict(title='Money pressures', flagged=flags['finances'], value=f"{record['fin_stress']}/10 · 1 means more distress, 10 means less",
             text='Money worries may add to study pressures. Responses of 1–4 raise a financial flag and guide money-support suggestions; no amounts or income are inferred.'),
        dict(title='Support & connection', flagged=flags['support'], value=f"{scores['support_mean']:g}/7 across {scores['support_item_count']} answers",
             text='Available support may help you cope with pressures. A mean below 3 raises a support flag. This selected-item average is an indicator, not a validated MSPSS short-form score.'),
    ]

def finalise(record):
    scores = score(record)
    flags = scores['context_flags']
    tips, stressors = [], []
    for flag, tip, stressor in [('sleep','sleep_routine','sleep_deprivation'), ('workload','workload_chunks','academic_overload'),
                              ('finances','money_worries','financial_pressure'), ('support','talk_to_someone','low_social_support')]:
        if flags[flag]:
            tips.append(tip)
            stressors.append(stressor)
    if scores['pss_total'] >= 8:
        stressors.append('high_stress')
    if scores['speak_prominence'] == 'high':
        tips.insert(0, 'talk_to_someone')
    tips = list(dict.fromkeys(tips + record.get('tips', []) or ['short_breaks','keep_social_contact']))[:4]
    result = {**record, **scores, 'tips':tips, 'primary_stressors':stressors,
              'risk_score':scores['pss_total']/16, # compatibility field, NOT a probability
              'reasoning':explanation(record, scores), 'factor_insights':factor_insights(record, scores),
              'ok':True, 'ai_ok':True, 'source':'ai_logic', 'logic_rule':VERSION,
              'logic_rules':[VERSION], 'logic_clamp_notes':[]}
    result.pop('feelings_text', None)
    return result

def public_config():
    return dict(version=VERSION, questions=QUESTIONS, sections=SECTIONS, safetyPatterns=SAFETY_PATTERNS)
