"""Evidence questionnaire v3. Project heuristics, not diagnostic cut-offs.

Source: donotstress_question_evidence.docx, 9 October 2026, section 2.
Every question uses one 1-5 scale except typical sleep, which stays a
0-14 hour slider (half-hour steps) and is converted to 1-5 only when
scoring. Items are adapted from their source instruments, so results are
NOT PSS-4, PSQI, IFDFW or MSPSS scores. Positively worded items
(reverse=True) are scored as 6 - answer, so a higher scored value always
means more stress. Never convert legacy /10 or evidence-v2 records onto
this scale.
"""
import math
import re

VERSION = "evidence-v3"
SCALE_MIN, SCALE_MAX = 1, 5
PSS_OPTIONS = ["Never", "Almost never", "Sometimes", "Fairly often", "Very often"]
SLEEP_OPTIONS = ["Very good", "Fairly good", "Okay", "Fairly bad", "Very bad"]
AGREE_OPTIONS = ["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"]
PAS_OPTIONS = AGREE_OPTIONS
SUPPORT_OPTIONS = AGREE_OPTIONS
FIN_OPTIONS = ["No stress at all", "A little stress", "Moderate stress", "High stress", "Overwhelming stress"]
CHECK_IN_FROM = 2.5    # average 2.5 to 3.5 (inclusive) -> 'Worth a check-in'
REACH_OUT_ABOVE = 3.5  # average above 3.5 -> 'Please reach out'
SUPPORT_KEYS = ('mspss_friends', 'mspss_family')

def question(key, label, prompt, minimum, maximum, options=None, **extra):
    return dict(key=key, label=label, prompt=prompt, min=minimum, max=maximum,
                step=extra.pop('step', 1), options=options, **extra)

QUESTIONS = [
    question('pss_1', 'Losing control', "In the past month, how often have you felt you couldn't control the important things in your life?", SCALE_MIN, SCALE_MAX, PSS_OPTIONS),
    question('pss_2', 'Handling personal problems', 'In the past month, how often have you felt confident handling your personal problems?', SCALE_MIN, SCALE_MAX, PSS_OPTIONS, reverse=True),
    question('pss_3', 'Things going your way', 'In the past month, how often have you felt things were going well for you?', SCALE_MIN, SCALE_MAX, PSS_OPTIONS, reverse=True),
    question('pss_4', 'Difficulties piling up', 'In the past month, how often have you felt problems were piling up too much to handle?', SCALE_MIN, SCALE_MAX, PSS_OPTIONS),
    question('sleep_hours_avg', 'Typical sleep · past week', 'On average, how many hours of sleep have you gotten each night this week?', 0, 14, step=0.5, kind='slider', default=7, low='0 hours', high='14 hours', unit='hours'),
    question('sleep_quality', 'Sleep quality · past week', 'During the past week, how would you rate your sleep quality overall?', SCALE_MIN, SCALE_MAX, SLEEP_OPTIONS),
    question('pas_workload', 'Study workload', 'I feel my coursework is too much to handle.', SCALE_MIN, SCALE_MAX, PAS_OPTIONS),
    question('pas_catchup', 'Catching up', 'When I fall behind on my work, I find it hard to catch up.', SCALE_MIN, SCALE_MAX, PAS_OPTIONS),
    question('fin_stress', 'Personal finances', 'How stressed do you feel about your personal finances in general?', SCALE_MIN, SCALE_MAX, FIN_OPTIONS, kind='slider', step=1, default=3, low='No stress at all', high='Overwhelming stress', unit='out of 5'),
    question('mspss_friends', 'Support from friends', 'I can count on my friends when things go wrong.', SCALE_MIN, SCALE_MAX, SUPPORT_OPTIONS, reverse=True),
    question('mspss_family', 'Support from family', 'I get the emotional help and support I need from my family.', SCALE_MIN, SCALE_MAX, SUPPORT_OPTIONS, reverse=True),
]
QUESTION_MAP = {q['key']: q for q in QUESTIONS}
# Positively worded items: a high answer means LESS stress, so they are scored as 6 - answer.
REVERSED_KEYS = tuple(q['key'] for q in QUESTIONS if q.get('reverse'))
SECTIONS = [
    dict(title='Your month', heading='Start with the bigger picture.', period='Think about the last month',
         intro='Notice how manageable life has felt, including moments when things went well. Choose how often each experience happened.',
         why='These four questions explore perceived stress: how unpredictable, difficult to control, or overwhelming life has felt. Together they give more context than one stress rating.',
         keys=['pss_1','pss_2','pss_3','pss_4']),
    dict(title='Rest & recovery', heading='How has your sleep been?', period='Think about the past week',
         intro='Now zoom in on your recent routine. Think about a typical night, rather than only last night.',
         why='Sleep and stress can affect one another. Hours and quality capture different parts of rest; either can help explain why daily demands feel harder to manage.',
         keys=['sleep_hours_avg','sleep_quality']),
    dict(title='Study demands', heading='Make room for your study load.', period='Your current study experience',
         intro='With your overall feelings and rest in mind, consider the demands of your coursework.',
         why='Feeling overloaded by assignments can add pressure and reduce time for recovery. This question identifies a possible source of strain, rather than judging your academic performance.',
         keys=['pas_workload','pas_catchup']),
    dict(title='Money pressures', heading='Life outside the timetable.', period='Your personal finances in general',
         intro='Everyday expenses can take up mental space too. You do not need to share amounts or financial details.',
         why='Financial worries may compete for attention alongside study demands. This question helps us suggest relevant support without assuming your income or circumstances.',
         keys=['fin_stress']),
    dict(title='Your support', heading='Who can you lean on?', period='The support available to you',
         intro='After looking at pressures, consider the people who help you face them. Friends and family may support you in different ways.',
         why='Support can make stressful experiences easier to navigate. These questions look at sources of support; they do not cancel out or invalidate the stress you reported.',
         keys=['mspss_friends','mspss_family']),
    dict(title='A moment to reflect', heading='Anything else on your mind?', period='Optional · not scored',
         intro='Numbers cannot capture everything. You can reflect here, or continue without writing anything.',
         why='Your reflection does not contribute to the stress score. A basic safety check can highlight support, but it cannot recognise every situation. You can contact support at any time.',
         keys=[]),
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

def sleep_hours_stress(hours):
    """Map typical nightly hours onto the 1-5 stress scale. Scoring only."""
    if hours >= 8:
        return 1
    if hours >= 7:
        return 2
    if hours >= 6:
        return 3
    if hours >= 5:
        return 4
    return 5

def scored_value(key, answer):
    """Stress-direction value. Sleep hours are converted here; positive items are 6 - answer."""
    if key == 'sleep_hours_avg':
        return sleep_hours_stress(answer)
    return (SCALE_MIN + SCALE_MAX) - answer if key in REVERSED_KEYS else answer

def score(record):
    """Score validated v3 inputs only; no AI or free-text sentiment scoring.

    stress_score = mean of all 11 required answers on a 1-5 stress scale (1.0-5.0).
    Sleep hours are converted in scored_value; the stored answer stays hours.
    Every question has equal weight.
    """
    items = [scored_value(q['key'], record[q['key']]) for q in QUESTIONS if record.get(q['key']) is not None]
    average = sum(items) / len(items)
    support = [record[k] for k in SUPPORT_KEYS if record.get(k) is not None]
    mean = sum(support) / len(support)
    flags = {
        'sleep': record['sleep_hours_avg'] < 6 or record['sleep_quality'] >= 4,  # under 6 h, or fairly/very bad
        'workload': record['pas_workload'] >= 4,
        'finances': record['fin_stress'] >= 4,  # high or overwhelming money stress
        'support': mean < 2.5,                  # raw agreement, mostly disagreeing
    }
    band = 2 if average > REACH_OUT_ABOVE else 1 if average >= CHECK_IN_FROM else 0
    if record.get('safety_flag') is True:
        band = 2
    return dict(stress_score=round(average, 2), scored_item_count=len(items),
                support_mean=round(mean, 2), support_item_count=len(support),
                context_flags=flags, risk_category=['Low','Moderate','High'][band],
                soft_label=["You're doing ok", 'Worth a check-in', 'Please reach out'][band],
                speak_prominence=['low','medium','high'][band])

def explanation(record, scores):
    stress = scores['stress_score']
    text = (f"Your {scores['scored_item_count']} answers give an average stress score of {stress:g} out of 5 "
            '(1 = least stress, 5 = most). Positively worded questions were reversed, so higher always means more stress.')
    if record.get('safety_flag'):
        text += ' Your reflection prompted us to highlight support. This does not change your stress score and is not a diagnosis.'
    elif scores['risk_category'] == 'High':
        text += ' The project uses averages above 3.5 to encourage reaching out to someone for support.'
    elif scores['risk_category'] == 'Moderate':
        text += ' The project uses averages from 2.5 to 3.5 to suggest a check-in with someone you trust.'
    else:
        text += ' Your answers fall in the lower project band (below 2.5). You can still ask for support whenever you need it.'
    return text + ' These bands are team heuristics, not clinical cut-offs.'

def factor_insights(record, scores):
    flags = scores['context_flags']
    return [
        dict(title='Rest & recovery', flagged=flags['sleep'], value=f"{record['sleep_hours_avg']:g} hours · {SLEEP_OPTIONS[record['sleep_quality']-1]} quality",
             text='Short or unsatisfying sleep can make daily demands harder to manage. Stress may also disrupt sleep. The project flags under 6 hours or fairly/very bad quality (answers of 4 or 5).'),
        dict(title='Study demands', flagged=flags['workload'], value=f"{record['pas_workload']}/5 · {PAS_OPTIONS[record['pas_workload']-1]}",
             text='Feeling overloaded may leave less room for rest. Agreeing that coursework is too much raises a workload flag. The catch-up answer counts in the stress score, not as a separate flag.'),
        dict(title='Money pressures', flagged=flags['finances'], value=f"{record['fin_stress']}/5 · {FIN_OPTIONS[record['fin_stress']-1]}",
             text='Money worries may add to study pressures. Answers of 4–5 (high or overwhelming stress) raise a financial flag and guide money-support suggestions; no amounts or income are inferred.'),
        dict(title='Support & connection', flagged=flags['support'], value=f"{scores['support_mean']:g}/5 agreement across {scores['support_item_count']} answers",
             text='Available support may help you cope with pressures. An average below 2.5 raises a support flag. In the overall stress score these answers are reversed (6 − answer). This is an indicator, not a validated MSPSS score.'),
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
    if scores['stress_score'] >= CHECK_IN_FROM:
        stressors.append('high_stress')
    if scores['speak_prominence'] == 'high':
        tips.insert(0, 'talk_to_someone')
    tips = list(dict.fromkeys(tips + record.get('tips', []) or ['short_breaks','keep_social_contact']))[:4]
    result = {**record, **scores, 'tips':tips, 'primary_stressors':stressors,
              'risk_score':round((scores['stress_score'] - SCALE_MIN) / (SCALE_MAX - SCALE_MIN), 4), # (avg-1)/4, NOT a probability
              'reasoning':explanation(record, scores), 'factor_insights':factor_insights(record, scores),
              'ok':True, 'ai_ok':True, 'source':'ai_logic', 'logic_rule':VERSION,
              'logic_rules':[VERSION], 'logic_clamp_notes':[]}
    result.pop('feelings_text', None)
    return result

def public_config():
    return dict(version=VERSION, questions=QUESTIONS, sections=SECTIONS, safetyPatterns=SAFETY_PATTERNS)
