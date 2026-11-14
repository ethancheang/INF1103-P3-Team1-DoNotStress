"""Evidence questionnaire v3: the wording, chapters and safety patterns.

Source: donotstress_question_evidence.docx, 9 October 2026, section 2.
Every question uses one 1-5 scale except typical sleep, which stays a
0-14 hour slider (half-hour steps) and is converted to 1-5 only when
scoring. logic_manager owns scoring, context flags and tiers. Items are
adapted from their source instruments, so results are NOT PSS-4, PSQI,
IFDFW or MSPSS scores. Positively worded items (reverse=True) are scored
as 6 - answer, so a higher scored value always means more stress. Never
convert legacy /10 or evidence-v2 records onto this scale.

This module holds content only: VERSION, QUESTIONS, SECTIONS and
SAFETY_PATTERNS. Questionnaire.from_survey() builds a Questionnaire from
that data. App creates one instance and passes it to I/O and AI.
There is no module-level questionnaire instance, and this file has no
module-level functions.
"""

VERSION = "evidence-v3"
SCALE_MIN, SCALE_MAX = 1, 5

PSS_OPTIONS = ("Never", "Almost never", "Sometimes", "Fairly often",
               "Very often")
SLEEP_OPTIONS = ("Very good", "Fairly good", "Okay", "Fairly bad",
                 "Very bad")
AGREE_OPTIONS = ("Strongly disagree", "Disagree", "Neutral", "Agree",
                 "Strongly agree")
FIN_OPTIONS = ("No stress at all", "A little stress", "Moderate stress",
               "High stress", "Overwhelming stress")

# Shared with the browser for an immediate, conservative support prompt.
# Keywords can give false positives/negatives; never claim to assess safety.
SAFETY_PATTERNS = (
    r"\bsuicid(?:e|al)\b",
    r"\bself[ -]?harm(?:ing)?\b",
    r"\b(?:kill|hurt|harm|cut)(?:ing)? myself\b",
    r"\b(?:end|take) my (?:own )?life\b",
    r"\b(?:want|wish|going|plan|planning) to die\b",
    r"\b(?:cannot|can't|dont|don't) "
    r"(?:go on|keep myself safe|want to live)\b",
    r"\bbetter off dead\b",
    r"\b(?:took|taken|take) an overdose\b",
)


QUESTIONS = [
            {
                "key": "pss_1", "label": "Losing control",
                "prompt": ("In the past month, how often have you felt you "
                           "couldn't control the important things in your "
                           "life?"),
                "min": SCALE_MIN, "max": SCALE_MAX, "step": 1,
                "options": PSS_OPTIONS, "reverse": False, "kind": "choice",
                "default": None, "low": "", "high": "", "unit": "",
            },
            {
                "key": "pss_2", "label": "Handling personal problems",
                "prompt": ("In the past month, how often have you felt "
                           "confident handling your personal problems?"),
                "min": SCALE_MIN, "max": SCALE_MAX, "step": 1,
                "options": PSS_OPTIONS, "reverse": True, "kind": "choice",
                "default": None, "low": "", "high": "", "unit": "",
            },
            {
                "key": "pss_3", "label": "Things going your way",
                "prompt": ("In the past month, how often have you felt "
                           "things were going well for you?"),
                "min": SCALE_MIN, "max": SCALE_MAX, "step": 1,
                "options": PSS_OPTIONS, "reverse": True, "kind": "choice",
                "default": None, "low": "", "high": "", "unit": "",
            },
            {
                "key": "pss_4", "label": "Difficulties piling up",
                "prompt": ("In the past month, how often have you felt "
                           "problems were piling up too much to handle?"),
                "min": SCALE_MIN, "max": SCALE_MAX, "step": 1,
                "options": PSS_OPTIONS, "reverse": False, "kind": "choice",
                "default": None, "low": "", "high": "", "unit": "",
            },
            {
                "key": "sleep_hours_avg", "label": "Typical sleep · past week",
                "prompt": ("On average, how many hours of sleep have you "
                           "gotten each night this week?"),
                "min": 0, "max": 14, "step": 0.5, "options": (),
                "reverse": False, "kind": "slider", "default": 7,
                "low": "0 hours", "high": "14 hours", "unit": "hours",
            },
            {
                "key": "sleep_quality", "label": "Sleep quality · past week",
                "prompt": ("During the past week, how would you rate your "
                           "sleep quality overall?"),
                "min": SCALE_MIN, "max": SCALE_MAX, "step": 1,
                "options": SLEEP_OPTIONS, "reverse": False, "kind": "choice",
                "default": None, "low": "", "high": "", "unit": "",
            },
            {
                "key": "pas_workload", "label": "Study workload",
                "prompt": "I feel my coursework is too much to handle.",
                "min": SCALE_MIN, "max": SCALE_MAX, "step": 1,
                "options": AGREE_OPTIONS, "reverse": False, "kind": "choice",
                "default": None, "low": "", "high": "", "unit": "",
            },
            {
                "key": "pas_catchup", "label": "Catching up",
                "prompt": ("When I fall behind on my work, I find it hard "
                           "to catch up."),
                "min": SCALE_MIN, "max": SCALE_MAX, "step": 1,
                "options": AGREE_OPTIONS, "reverse": False, "kind": "choice",
                "default": None, "low": "", "high": "", "unit": "",
            },
            {
                "key": "fin_stress", "label": "Personal finances",
                "prompt": ("How stressed do you feel about your personal "
                           "finances in general?"),
                "min": SCALE_MIN, "max": SCALE_MAX, "step": 1,
                "options": FIN_OPTIONS, "reverse": False, "kind": "slider",
                "default": 3, "low": "No stress at all",
                "high": "Overwhelming stress", "unit": "out of 5",
            },
            {
                "key": "mspss_friends", "label": "Support from friends",
                "prompt": ("I can count on my friends when things go "
                           "wrong."),
                "min": SCALE_MIN, "max": SCALE_MAX, "step": 1,
                "options": AGREE_OPTIONS, "reverse": True, "kind": "choice",
                "default": None, "low": "", "high": "", "unit": "",
            },
            {
                "key": "mspss_family", "label": "Support from family",
                "prompt": ("I get the emotional help and support I need "
                           "from my family."),
                "min": SCALE_MIN, "max": SCALE_MAX, "step": 1,
                "options": AGREE_OPTIONS, "reverse": True, "kind": "choice",
                "default": None, "low": "", "high": "", "unit": "",
            },
]

SECTIONS = [
            {
                "title": "Your month",
                "heading": "Start with the bigger picture.",
                "period": "Think about the last month",
                "intro": ("Notice how manageable life has felt, including "
                          "moments when things went well. Choose how often "
                          "each experience happened."),
                "why": ("These four questions explore perceived stress: how "
                        "unpredictable, difficult to control, or "
                        "overwhelming life has felt. Together they give "
                        "more context than one stress rating."),
                "keys": ("pss_1", "pss_2", "pss_3", "pss_4"),
            },
            {
                "title": "Rest & recovery",
                "heading": "How has your sleep been?",
                "period": "Think about the past week",
                "intro": ("Now zoom in on your recent routine. Think about "
                          "a typical night, rather than only last night."),
                "why": ("Sleep and stress can affect one another. Hours and "
                        "quality capture different parts of rest; either "
                        "can help explain why daily demands feel harder "
                        "to manage."),
                "keys": ("sleep_hours_avg", "sleep_quality"),
            },
            {
                "title": "Study demands",
                "heading": "Make room for your study load.",
                "period": "Your current study experience",
                "intro": ("With your overall feelings and rest in mind, "
                          "consider the demands of your coursework."),
                "why": ("Feeling overloaded by assignments can add pressure "
                        "and reduce time for recovery. This question "
                        "identifies a possible source of strain, rather "
                        "than judging your academic performance."),
                "keys": ("pas_workload", "pas_catchup"),
            },
            {
                "title": "Money pressures",
                "heading": "Life outside the timetable.",
                "period": "Your personal finances in general",
                "intro": ("Everyday expenses can take up mental space too. "
                          "You do not need to share amounts or financial "
                          "details."),
                "why": ("Financial worries may compete for attention "
                        "alongside study demands. This question helps us "
                        "suggest relevant support without assuming your "
                        "income or circumstances."),
                "keys": ("fin_stress",),
            },
            {
                "title": "Your support",
                "heading": "Who can you lean on?",
                "period": "The support available to you",
                "intro": ("After looking at pressures, consider the people "
                          "who help you face them. Friends and family may "
                          "support you in different ways."),
                "why": ("Support can make stressful experiences easier to "
                        "navigate. These questions look at sources of "
                        "support; they do not cancel out or invalidate the "
                        "stress you reported."),
                "keys": ("mspss_friends", "mspss_family"),
            },
            {
                "title": "A moment to reflect",
                "heading": "Anything else on your mind?",
                "period": "Optional · not scored",
                "intro": ("Numbers cannot capture everything. You can "
                          "reflect here, or continue without writing "
                          "anything."),
                "why": ("Your reflection does not contribute to the stress "
                        "score. A basic safety check can highlight support, "
                        "but it cannot recognise every situation. You can "
                        "contact support at any time."),
                "keys": (),
            },
]


