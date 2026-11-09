"""DoNotStress desktop app (advanced feature: GUI with a background worker thread).

A calm, multi-step check-in that reuses the same four managers as the web app.
Run it with:

    python gui.py

GEMINI_API_KEY must be set (for example in .env): every check-in is analysed
by the live AI. Without a key the app says the assessment service is not
configured and keeps the answers as a pending record.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from dotenv import load_dotenv

from ai_manager import GeminiAIManager, GeminiTextGenerator
from checkin_pipeline import CheckinPipeline
from checkin_worker import CheckinWorker
from data_manager import DataStoreError, JsonRecordRepository, RecordStatus
from desktop_palette import DesktopPalette
from io_manager import StudentIO
from logic_manager import AIScoreVerifier, LogicManager, ScoreCalculator
from survey import Questionnaire


class DoNotStressApp(tk.Tk):
    """The desktop check-in window (advanced feature: GUI with a background worker thread).

    It reuses the same four managers as the web app:
      StudentIO -> GeminiAIManager -> LogicManager -> JsonRecordRepository
    The AI call runs on a CheckinWorker thread, so the window never freezes
    while Gemini is working; the window polls the worker from the main thread.
    Every check-in needs the live AI: without GEMINI_API_KEY the app explains
    that the assessment service is not configured and saves the answers as
    pending, exactly like the web app. It never invents a result.
    """

    POLL_MS = 100

    def __init__(self) -> None:
        super().__init__()
        self._palette = DesktopPalette("light")
        self.title("DoNotStress · Campus check-in")
        self.geometry("980x720")
        self.minsize(820, 600)
        self.configure(bg=self._palette.bg)

        # Institutional accent bar, in the spirit of a hospital site header.
        accent = tk.Frame(self, bg=self._palette.accent, height=4)
        accent.pack(fill="x")

        calculator = ScoreCalculator()
        self.io = StudentIO()
        self.store = JsonRecordRepository(os.environ.get("DONOTSTRESS_DATA_PATH"))
        self.generator = GeminiTextGenerator()
        self.ai = GeminiAIManager(AIScoreVerifier(calculator), self.generator, questions=Questionnaire.QUESTIONS)
        self.logic = LogicManager(calculator=calculator)
        self.worker = CheckinWorker(CheckinPipeline(self.ai, self.logic), self.store)

        self.answers: dict = {}
        self.step = 0
        self.result_record: dict | None = None

        self._build_chrome()
        self.show_home()

    # -- chrome -------------------------------------------------------------

    def _build_chrome(self) -> None:
        header = tk.Frame(self, bg=self._palette.panel, highlightbackground=self._palette.line, highlightthickness=1)
        header.pack(fill="x")
        tk.Label(
            header, text="+  DoNotStress", font=("Segoe UI", 16, "bold"),
            bg=self._palette.panel, fg=self._palette.ink,
        ).pack(side="left", padx=18, pady=12)
        mode = "AI-assisted check-in" if self.generator.is_configured() else "AI not configured · set GEMINI_API_KEY"
        tk.Label(header, text=mode, font=("Segoe UI", 10), bg=self._palette.panel, fg=self._palette.sub).pack(side="left", padx=8)
        tk.Button(
            header, text="Home", command=self.show_home,
            bg=self._palette.panel, fg=self._palette.ink, relief="flat", padx=12, pady=6, font=("Segoe UI", 10),
        ).pack(side="right", padx=8, pady=10)
        tk.Button(
            header, text="Records", command=self.show_records,
            bg=self._palette.panel, fg=self._palette.ink, relief="flat", padx=12, pady=6, font=("Segoe UI", 10),
        ).pack(side="right", padx=4, pady=10)
        self.theme_btn = tk.Button(
            header, text="Light" if self._palette.name == "dark" else "Dark", command=self.toggle_theme,
            bg=self._palette.panel, fg=self._palette.ink, relief="flat", padx=12, pady=6, font=("Segoe UI", 10),
        )
        self.theme_btn.pack(side="right", padx=4, pady=10)

        self.body = tk.Frame(self, bg=self._palette.bg)
        self.body.pack(fill="both", expand=True, padx=18, pady=12)

        footer = tk.Frame(self, bg=self._palette.panel)
        footer.pack(fill="x")
        tk.Label(
            footer,
            text=(
                f"Need to talk?  SIT Counselling {StudentIO.ADVISOR_CONTACTS['helpline']}  ·  "
                f"{StudentIO.ADVISOR_CONTACTS['email']}  ·  SOS {StudentIO.ADVISOR_CONTACTS['sos']}  ·  "
                f"mindline {StudentIO.ADVISOR_CONTACTS['mindline']}"
            ),
            font=("Segoe UI", 9), bg=self._palette.panel, fg=self._palette.sub,
        ).pack(pady=8)

    def toggle_theme(self) -> None:
        self._palette = self._palette.toggled()
        # Rebuild chrome and the current view so the new palette applies.
        for child in self.winfo_children():
            child.destroy()
        self.configure(bg=self._palette.bg)
        accent = tk.Frame(self, bg=self._palette.accent, height=4)
        accent.pack(fill="x")
        self._build_chrome()
        if self.result_record:
            self.show_result(self.result_record)
        elif self.answers:
            self.show_step()
        else:
            self.show_home()

    def _clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

    # -- home ---------------------------------------------------------------

    def show_home(self) -> None:
        self._clear()
        self.answers = {}
        self.step = 0
        self.result_record = None

        card = tk.Frame(self.body, bg=self._palette.panel, highlightbackground=self._palette.line, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=20, pady=12)

        # Hero video section
        video_frame = tk.Frame(card, bg="#000", height=200)
        video_frame.pack(fill="x", padx=20, pady=(12, 8))
        video_frame.pack_propagate(False)
        try:
            from tkinter import PhotoImage
            poster = PhotoImage(file="static/video/poster.png")
            poster = poster.subsample(2, 2)
            self._poster = poster
            tk.Label(video_frame, image=poster, bg="#000").pack(fill="both", expand=True)
        except Exception:
            tk.Label(video_frame, text="A calm moment for your wellbeing", font=("Segoe UI", 14), bg="#000", fg="#fff").pack(expand=True)
        tk.Label(card, text="A private check-in, grounded in research.", font=("Segoe UI", 10), bg=self._palette.panel, fg=self._palette.sub).pack(anchor="w", padx=28, pady=(0, 8))

        top = tk.Frame(card, bg=self._palette.panel)
        top.pack(fill="x", padx=20, pady=(20, 8))

        left = tk.Frame(top, bg=self._palette.panel)
        left.pack(side="left", fill="both", expand=True, padx=(8, 16))
        tk.Label(left, text="STUDENT WELLBEING", font=("Segoe UI", 9, "bold"), bg=self._palette.panel, fg=self._palette.accent).pack(anchor="w")
        tk.Label(left, text="A private stress check-in\nfor SIT students.", font=("Segoe UI", 22, "bold"), bg=self._palette.panel, fg=self._palette.ink, justify="left").pack(anchor="w", pady=(4, 10))
        tk.Label(left, text="Notice how stress, sleep, study load and support are affecting you. Get a structured summary and a few practical next steps. Not a diagnosis.", font=("Segoe UI", 11), bg=self._palette.panel, fg=self._palette.sub, wraplength=380, justify="left").pack(anchor="w")
        actions = tk.Frame(left, bg=self._palette.panel)
        actions.pack(anchor="w", pady=(14, 4))
        tk.Button(actions, text="Start check-in", command=self.start_checkin, bg=self._palette.accent, fg="white", relief="flat", font=("Segoe UI", 11, "bold"), padx=16, pady=8).pack(side="left", padx=(0, 8))
        tk.Label(actions, text="11 questions · about 3 minutes", font=("Segoe UI", 9), bg=self._palette.panel, fg=self._palette.sub).pack(side="left")

        right = tk.Frame(top, bg=self._palette.soft, width=280)
        right.pack(side="right", fill="y", padx=(8, 8))
        right.pack_propagate(False)
        tk.Label(right, text="What you can expect", font=("Segoe UI", 12, "bold"), bg=self._palette.soft, fg=self._palette.ink).pack(anchor="w", padx=12, pady=(12, 8))
        for title, body in (
            ("Private answers", "Research-based questions on stress, rest, study, finances and support."),
            ("Clear summary", "A structured score, tier and suggestions. Wellbeing guidance only."),
            ("Support nearby", "SIT Counselling and national helplines are always one tap away."),
        ):
            tk.Label(right, text=title, font=("Segoe UI", 10, "bold"), bg=self._palette.soft, fg=self._palette.ink).pack(anchor="w", padx=12, pady=(6, 0))
            tk.Label(right, text=body, font=("Segoe UI", 9), bg=self._palette.soft, fg=self._palette.sub, wraplength=240, justify="left").pack(anchor="w", padx=12, pady=(0, 4))

        features = tk.Frame(card, bg=self._palette.panel)
        features.pack(fill="x", padx=20, pady=(8, 8))
        for title, body in (
            ("01  Early check-in", "Spot building stress before it affects studies, sleep or wellbeing."),
            ("02  Research-based", "Questions adapted from PSS-4, PSQI, PAS, IFDFW and MSPSS."),
            ("03  Privacy first", "Your ID stays with SIT staff. It is never sent to the AI."),
        ):
            box = tk.Frame(features, bg=self._palette.soft)
            box.pack(side="left", fill="both", expand=True, padx=4)
            tk.Label(box, text=title, font=("Segoe UI", 10, "bold"), bg=self._palette.soft, fg=self._palette.ink).pack(anchor="w", padx=12, pady=(10, 2))
            tk.Label(box, text=body, font=("Segoe UI", 9), bg=self._palette.soft, fg=self._palette.sub, wraplength=200, justify="left").pack(anchor="w", padx=12, pady=(0, 10))

        note = tk.Frame(card, bg=self._palette.soft)
        note.pack(fill="x", padx=28, pady=(4, 16))
        tk.Label(note, text="Wellbeing guidance only. Not a medical diagnosis. Student IDs are never sent to the AI.", font=("Segoe UI", 10), bg=self._palette.soft, fg=self._palette.ink).pack(anchor="w", padx=14, pady=10)

    # -- check-in -----------------------------------------------------------

    def start_checkin(self) -> None:
        self.answers = {"student_id": "", "feelings_text": ""}
        for q in Questionnaire.QUESTIONS:
            self.answers[q["key"]] = None
        self.step = 0
        self.show_step()

    def show_step(self) -> None:
        self._clear()
        review = self.step >= len(Questionnaire.SECTIONS)
        if review:
            self._show_review()
            return

        section = Questionnaire.SECTIONS[self.step]
        outer = tk.Frame(self.body, bg=self._palette.bg)
        outer.pack(fill="both", expand=True)

        rail = tk.Frame(outer, bg=self._palette.panel, width=200, highlightbackground=self._palette.line, highlightthickness=1)
        rail.pack(side="left", fill="y", padx=(0, 12))
        rail.pack_propagate(False)
        tk.Label(
            rail, text="CHAPTERS", font=("Segoe UI", 9, "bold"), bg=self._palette.panel, fg=self._palette.accent,
        ).pack(anchor="w", padx=12, pady=(14, 8))
        for i, sec in enumerate(Questionnaire.SECTIONS):
            mark = "✓" if i < self.step else str(i + 1)
            color = self._palette.accent if i == self.step else (self._palette.ink if i < self.step else self._palette.sub)
            weight = "bold" if i == self.step else "normal"
            tk.Label(
                rail, text=f"  {mark}   {sec['title']}",
                font=("Segoe UI", 10, weight),
                bg=self._palette.panel, fg=color, anchor="w",
            ).pack(fill="x", padx=8, pady=4)
        progress = tk.Frame(rail, bg=self._palette.panel)
        progress.pack(fill="x", padx=12, pady=(20, 8))
        tk.Frame(progress, bg=self._palette.line, height=1).pack(fill="x", pady=(0, 8))
        pct = int(self.step / len(Questionnaire.SECTIONS) * 100)
        tk.Label(progress, text=f"{pct}%", font=("Segoe UI", 18, "bold"), bg=self._palette.panel, fg=self._palette.accent).pack(anchor="w")
        tk.Label(progress, text="complete", font=("Segoe UI", 9), bg=self._palette.panel, fg=self._palette.sub).pack(anchor="w")

        form = tk.Frame(outer, bg=self._palette.panel, highlightbackground=self._palette.line, highlightthickness=1)
        form.pack(side="left", fill="both", expand=True)

        canvas = tk.Canvas(form, bg=self._palette.panel, highlightthickness=0)
        scroll = ttk.Scrollbar(form, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=self._palette.panel)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        tk.Label(inner, text=section["period"], font=("Segoe UI", 10), bg=self._palette.soft, fg=self._palette.ink).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(inner, text=section["heading"], font=("Segoe UI", 18, "bold"), bg=self._palette.panel, fg=self._palette.ink).pack(anchor="w", padx=20, pady=(4, 6))
        tk.Label(inner, text=section["intro"], font=("Segoe UI", 11), bg=self._palette.panel, fg=self._palette.sub, wraplength=560, justify="left").pack(anchor="w", padx=20, pady=(0, 8))

        if self.step == 0:
            self._student_id_field(inner)

        self._widgets: dict[str, tk.Variable] = {}
        for key in section["keys"]:
            self._question_field(inner, Questionnaire.QUESTION_MAP[key])

        if self.step == 5:
            self._reflection_field(inner)

        self._error = tk.Label(inner, text="", font=("Segoe UI", 10), bg=self._palette.panel, fg="#ac342c")
        self._error.pack(anchor="w", padx=20, pady=(4, 0))

        nav = tk.Frame(inner, bg=self._palette.panel)
        nav.pack(fill="x", padx=20, pady=16)
        back_label = "← Home" if self.step == 0 else "← Back"
        tk.Button(nav, text=back_label, command=self._back, bg=self._palette.soft, fg=self._palette.ink, relief="flat", padx=12, pady=8).pack(side="left")
        next_label = "Review my check-in →" if self.step == len(Questionnaire.SECTIONS) - 1 else "Continue →"
        tk.Button(nav, text=next_label, command=self._next, bg=self._palette.accent, fg="white", relief="flat", padx=14, pady=8).pack(side="right")

    def _student_id_field(self, parent: tk.Frame) -> None:
        box = tk.Frame(parent, bg=self._palette.panel)
        box.pack(fill="x", padx=20, pady=8)
        tk.Label(box, text="Student ID", font=("Segoe UI", 11, "bold"), bg=self._palette.panel, fg=self._palette.ink).pack(anchor="w")
        entry = tk.Entry(box, font=("Segoe UI", 12), width=20)
        entry.insert(0, self.answers.get("student_id", ""))
        entry.pack(anchor="w", pady=4)
        tk.Label(box, text="7 digits starting with 2. Never sent to the AI.", font=("Segoe UI", 9), bg=self._palette.panel, fg=self._palette.sub).pack(anchor="w")
        self._id_entry = entry

    def _question_field(self, parent: tk.Frame, q: dict) -> None:
        card = tk.Frame(parent, bg=self._palette.panel, highlightbackground=self._palette.line, highlightthickness=1)
        card.pack(fill="x", padx=20, pady=8)
        tk.Label(card, text=q["prompt"], font=("Segoe UI", 11, "bold"), bg=self._palette.panel, fg=self._palette.ink, wraplength=540, justify="left").pack(anchor="w", padx=12, pady=(10, 6))

        if q.get("kind") == "slider":
            value = self.answers.get(q["key"])
            if value is None:
                value = q.get("default", q["min"])
            var = tk.DoubleVar(value=float(value))
            shown = tk.Label(card, text=self._slider_text(q, var.get()), font=("Segoe UI", 16), bg=self._palette.panel, fg=self._palette.ink)
            shown.pack(anchor="w", padx=12)
            scale = tk.Scale(
                card, from_=q["min"], to=q["max"], resolution=q.get("step", 1),
                orient="horizontal", variable=var, showvalue=False, length=420,
                bg=self._palette.panel, highlightthickness=0, troughcolor=self._palette.soft,
                command=lambda v, qq=q, lab=shown: lab.config(text=self._slider_text(qq, float(v))),  # type: ignore[misc]
            )
            scale.pack(anchor="w", padx=12, pady=(0, 6))
            ends = tk.Frame(card, bg=self._palette.panel)
            ends.pack(fill="x", padx=12, pady=(0, 10))
            tk.Label(ends, text=f"{q['min']} · {q.get('low', '')}", font=("Segoe UI", 9), bg=self._palette.panel, fg=self._palette.sub).pack(side="left")
            tk.Label(ends, text=f"{q['max']} · {q.get('high', '')}", font=("Segoe UI", 9), bg=self._palette.panel, fg=self._palette.sub).pack(side="right")
            self._widgets[q["key"]] = var
        else:
            choice = tk.IntVar(value=self.answers.get(q["key"]) or 0)
            row = tk.Frame(card, bg=self._palette.panel)
            row.pack(fill="x", padx=8, pady=(0, 10))
            for i, label in enumerate(q["options"]):
                value = i + q["min"]
                rb = tk.Radiobutton(
                    row, text=f"{value}\n{label}", value=value, variable=choice,
                    bg=self._palette.panel, fg=self._palette.ink, selectcolor=self._palette.soft, indicatoron=False,
                    font=("Segoe UI", 9), width=12, pady=6, relief="flat",
                )
                rb.pack(side="left", padx=3)
            self._widgets[q["key"]] = choice

    def _slider_text(self, q: dict, value: float) -> str:
        unit = q.get("unit", "")
        shown = int(value) if float(value).is_integer() else value
        return f"{shown} {unit}".strip()

    def _reflection_field(self, parent: tk.Frame) -> None:
        box = tk.Frame(parent, bg=self._palette.panel)
        box.pack(fill="x", padx=20, pady=8)
        tk.Label(box, text="Anything on your mind? (optional)", font=("Segoe UI", 11, "bold"), bg=self._palette.panel, fg=self._palette.ink).pack(anchor="w")
        text = tk.Text(box, height=4, width=60, font=("Segoe UI", 11), wrap="word")
        text.insert("1.0", self.answers.get("feelings_text", ""))
        text.pack(anchor="w", pady=4)
        tk.Label(
            box,
            text="This space is just for you. It isn't scored or saved. A basic word check can show support contacts.",
            font=("Segoe UI", 9), bg=self._palette.panel, fg=self._palette.sub, wraplength=540, justify="left",
        ).pack(anchor="w")
        self._reflection = text

    def _collect_step(self) -> str:
        if self.step == 0 and hasattr(self, "_id_entry"):
            self.answers["student_id"] = self._id_entry.get().strip()
        if self.step == 5 and hasattr(self, "_reflection"):
            self.answers["feelings_text"] = self._reflection.get("1.0", "end").strip()
        section = Questionnaire.SECTIONS[self.step]
        for key in section["keys"]:
            widget = self._widgets.get(key)
            if widget is None:
                continue
            value = widget.get()
            if isinstance(value, float) and value.is_integer() and Questionnaire.QUESTION_MAP[key].get("kind") != "slider":
                value = int(value)
            if Questionnaire.QUESTION_MAP[key].get("kind") != "slider" and value == 0:
                return f"Please answer “{Questionnaire.QUESTION_MAP[key]['label']}”."
            self.answers[key] = value
        return ""

    def _back(self) -> None:
        if self.step == 0:
            self.show_home()
            return
        self._collect_step()
        self.step -= 1
        self.show_step()

    def _next(self) -> None:
        problem = self._collect_step()
        if problem:
            self._error.config(text=problem)
            return
        if self.step == 0:
            ok, message = self.io.validate_student_id(self.answers["student_id"])
            if not ok:
                self._error.config(text=message)
                return
        self.step += 1
        self.show_step()

    def _show_review(self) -> None:
        outer = tk.Frame(self.body, bg=self._palette.panel, highlightbackground=self._palette.line, highlightthickness=1)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="A moment to look back.", font=("Segoe UI", 18, "bold"), bg=self._palette.panel, fg=self._palette.ink).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(
            outer,
            text="Check your answers. After you submit, we'll look at them and share a few suggestions. Your ID is never sent to the AI. Reflection text is not stored.",
            font=("Segoe UI", 11), bg=self._palette.panel, fg=self._palette.sub, wraplength=700, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 10))
        tk.Label(outer, text=f"Student ID: {self.answers.get('student_id', '')}", font=("Segoe UI", 11, "bold"), bg=self._palette.panel, fg=self._palette.ink).pack(anchor="w", padx=20)

        canvas = tk.Canvas(outer, bg=self._palette.panel, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=self._palette.panel)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True, padx=12)
        scroll.pack(side="right", fill="y")

        for section in Questionnaire.SECTIONS:
            tk.Label(inner, text=section["title"], font=("Segoe UI", 12, "bold"), bg=self._palette.panel, fg=self._palette.ink).pack(anchor="w", pady=(10, 2))
            for key in section["keys"]:
                q = Questionnaire.QUESTION_MAP[key]
                value = self.answers.get(key)
                shown = value if value is not None else "—"
                tk.Label(inner, text=f"{q['label']}:  {shown}", font=("Segoe UI", 10), bg=self._palette.panel, fg=self._palette.sub).pack(anchor="w")

        nav = tk.Frame(self.body, bg=self._palette.bg)
        nav.pack(fill="x", pady=8)
        tk.Button(nav, text="← Back", command=lambda: self._go_step(len(Questionnaire.SECTIONS) - 1), bg=self._palette.soft, fg=self._palette.ink, relief="flat", padx=12, pady=8).pack(side="left", padx=8)
        tk.Button(nav, text="Get my check-in →", command=self.submit, bg=self._palette.accent, fg="white", relief="flat", padx=14, pady=8).pack(side="right", padx=8)

    def _go_step(self, step: int) -> None:
        self.step = step
        self.show_step()

    # -- submit -------------------------------------------------------------

    def submit(self) -> None:
        ok, clean = self.io.validate_form(self.answers)
        if not ok:
            messagebox.showerror("Check your answers", "\n".join(f"{k}: {v}" for k, v in clean.items()))
            return
        if self.worker.busy:
            return
        self._show_busy()
        self.worker.start(clean)
        self.after(self.POLL_MS, self._poll_worker)

    def _show_busy(self) -> None:
        self._clear()
        tk.Label(
            self.body, text="Taking a moment to understand your check-in…",
            font=("Segoe UI", 14), bg=self._palette.bg, fg=self._palette.ink,
        ).pack(pady=80)

    def _poll_worker(self) -> None:
        """Runs on the main thread: show the outcome once the worker thread has finished."""
        outcome = self.worker.poll()
        if outcome is None:
            self.after(self.POLL_MS, self._poll_worker)
            return
        ok, value = outcome
        if ok:
            self.show_result(value)
        else:
            self._show_failure(str(value))

    def _show_failure(self, code: str) -> None:
        self._clear()
        copy = self.io.format_ai_error(code)
        card = tk.Frame(self.body, bg=self._palette.panel, highlightbackground=self._palette.line, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=40, pady=30)
        tk.Label(card, text=copy["heading"], font=("Segoe UI", 16, "bold"), bg=self._palette.panel, fg=self._palette.ink).pack(anchor="w", padx=20, pady=(20, 6))
        tk.Label(card, text=copy["body"], font=("Segoe UI", 11), bg=self._palette.panel, fg=self._palette.sub, wraplength=560, justify="left").pack(anchor="w", padx=20)
        advisor = copy["speak_to_advisor"]
        tk.Label(card, text=advisor["heading"], font=("Segoe UI", 12, "bold"), bg=self._palette.panel, fg=self._palette.ink).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(
            card,
            text=f"SIT Counselling {StudentIO.ADVISOR_CONTACTS['helpline']}\n{StudentIO.ADVISOR_CONTACTS['email']}\nSOS {StudentIO.ADVISOR_CONTACTS['sos']} · mindline {StudentIO.ADVISOR_CONTACTS['mindline']}",
            font=("Segoe UI", 11), bg=self._palette.panel, fg=self._palette.ink, justify="left",
        ).pack(anchor="w", padx=20)
        tk.Button(card, text="Back to check-in", command=self.show_step, bg=self._palette.accent, fg="white", relief="flat", padx=12, pady=8).pack(anchor="w", padx=20, pady=16)

    # -- result -------------------------------------------------------------

    def show_result(self, record: dict) -> None:
        self._clear()
        self.result_record = record
        category = record.get("risk_category", "Moderate")
        soft = self.io.format_soft_label(str(record.get("soft_label", "")))

        canvas = tk.Canvas(self.body, bg=self._palette.bg, highlightthickness=0)
        scroll = ttk.Scrollbar(self.body, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=self._palette.bg)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        hero = tk.Frame(inner, bg=self._palette.tier_color(category))
        hero.pack(fill="x", padx=8, pady=8)
        tk.Label(hero, text="Your check-in", font=("Segoe UI", 10), bg=self._palette.tier_color(category), fg=self._palette.sub).pack(anchor="w", padx=16, pady=(12, 0))
        tk.Label(hero, text=soft["heading"], font=("Segoe UI", 20, "bold"), bg=self._palette.tier_color(category), fg=self._palette.ink).pack(anchor="w", padx=16)
        tk.Label(hero, text=soft["body"], font=("Segoe UI", 12), bg=self._palette.tier_color(category), fg=self._palette.ink, wraplength=640, justify="left").pack(anchor="w", padx=16, pady=(0, 8))
        note = "Wellbeing guidance, not a medical diagnosis. Your ID was not sent to the AI."
        tk.Label(hero, text=note, font=("Segoe UI", 9), bg=self._palette.tier_color(category), fg=self._palette.sub).pack(anchor="w", padx=16, pady=(0, 12))

        if record.get("safety_flag"):
            warn = tk.Frame(inner, bg=self._palette.high)
            warn.pack(fill="x", padx=8, pady=4)
            tk.Label(warn, text="Please reach out", font=("Segoe UI", 12, "bold"), bg=self._palette.high, fg=self._palette.ink).pack(anchor="w", padx=12, pady=(8, 0))
            tk.Label(
                warn,
                text=f"SIT Counselling {StudentIO.ADVISOR_CONTACTS['helpline']} · SOS {StudentIO.ADVISOR_CONTACTS['sos']} · mindline {StudentIO.ADVISOR_CONTACTS['mindline']}",
                font=("Segoe UI", 10), bg=self._palette.high, fg=self._palette.ink,
            ).pack(anchor="w", padx=12, pady=(0, 8))

        tk.Label(inner, text="How the pieces fit together", font=("Segoe UI", 13, "bold"), bg=self._palette.bg, fg=self._palette.ink).pack(anchor="w", padx=12, pady=(12, 4))
        grid = tk.Frame(inner, bg=self._palette.bg)
        grid.pack(fill="x", padx=8)
        for i, card in enumerate(record.get("factor_insights", [])):
            self._factor_card(grid, card).grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        tips = self.io.format_tips(record.get("tips", []))
        tk.Label(inner, text=tips["heading"], font=("Segoe UI", 13, "bold"), bg=self._palette.bg, fg=self._palette.ink).pack(anchor="w", padx=12, pady=(14, 4))
        for item in tips["items"]:
            row = tk.Frame(inner, bg=self._palette.panel, highlightbackground=self._palette.line, highlightthickness=1)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=item["text"], font=("Segoe UI", 11), bg=self._palette.panel, fg=self._palette.ink, wraplength=640, justify="left").pack(anchor="w", padx=12, pady=8)

        advisor = self.io.format_advisor(record.get("speak_prominence", "medium"))
        box = tk.Frame(inner, bg=self._palette.soft)
        box.pack(fill="x", padx=12, pady=12)
        tk.Label(box, text=advisor["heading"], font=("Segoe UI", 12, "bold"), bg=self._palette.soft, fg=self._palette.ink).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(box, text=advisor["body"], font=("Segoe UI", 10), bg=self._palette.soft, fg=self._palette.ink, wraplength=640, justify="left").pack(anchor="w", padx=12)
        tk.Label(
            box,
            text=f"{StudentIO.ADVISOR_CONTACTS['helpline']}  ·  {StudentIO.ADVISOR_CONTACTS['email']}",
            font=("Segoe UI", 10), bg=self._palette.soft, fg=self._palette.ink,
        ).pack(anchor="w", padx=12, pady=(0, 10))

        tk.Button(inner, text="Back to homepage", command=self.show_home, bg=self._palette.accent, fg="white", relief="flat", padx=14, pady=8).pack(anchor="w", padx=12, pady=(0, 16))

    def _factor_card(self, parent: tk.Frame, card: dict) -> tk.Frame:
        bg = self._palette.flag if card.get("flagged") else self._palette.panel
        frame = tk.Frame(parent, bg=bg, highlightbackground=self._palette.line, highlightthickness=1)
        tk.Label(frame, text=card.get("title", ""), font=("Segoe UI", 11, "bold"), bg=bg, fg=self._palette.ink).pack(anchor="w", padx=10, pady=(8, 0))
        if card.get("flagged"):
            tk.Label(frame, text="Worth some attention", font=("Segoe UI", 9), bg=bg, fg=self._palette.sub).pack(anchor="w", padx=10)
        tk.Label(frame, text=card.get("value", ""), font=("Segoe UI", 10, "bold"), bg=bg, fg=self._palette.ink).pack(anchor="w", padx=10, pady=(4, 0))
        tk.Label(frame, text=card.get("text", ""), font=("Segoe UI", 9), bg=bg, fg=self._palette.sub, wraplength=300, justify="left").pack(anchor="w", padx=10, pady=(2, 10))
        return frame

    # -- records ------------------------------------------------------------

    def show_records(self) -> None:
        self._clear()
        try:
            records = self.store.load()
        except DataStoreError:
            tk.Label(self.body, text="Saved records could not be loaded. Please check the records file.", font=("Segoe UI", 11), bg=self._palette.bg, fg=self._palette.ink).pack(anchor="w", pady=(4, 2))
            return
        tk.Label(self.body, text="Saved check-ins · staff view", font=("Segoe UI", 16, "bold"), bg=self._palette.bg, fg=self._palette.ink).pack(anchor="w", pady=(4, 2))
        tk.Label(self.body, text="Student IDs are visible here only. They are never sent to the AI.", font=("Segoe UI", 10), bg=self._palette.bg, fg=self._palette.sub).pack(anchor="w", pady=(0, 8))
        if not records:
            tk.Label(self.body, text="No records yet.", font=("Segoe UI", 11), bg=self._palette.bg, fg=self._palette.sub).pack(anchor="w")
            return

        cols = ("student_id", "stress_score", "risk_category", "soft_label", "status", "saved_at")
        tree = ttk.Treeview(self.body, columns=cols, show="headings", height=18)
        headings = {
            "student_id": "Student ID",
            "stress_score": "Score",
            "risk_category": "Tier",
            "soft_label": "Label",
            "status": "Status",
            "saved_at": "Saved",
        }
        for col in cols:
            tree.heading(col, text=headings[col])
            tree.column(col, width=120, anchor="center")
        tree.column("student_id", width=100)
        tree.column("saved_at", width=180)
        tree.pack(fill="both", expand=True)

        for item in sorted(records, key=lambda r: str(r.get("saved_at") or ""), reverse=True):
            status = RecordStatus.of(item)
            tree.insert("", "end", values=(
                item.get("student_id", ""),
                item.get("stress_score", ""),
                item.get("risk_category", ""),
                item.get("soft_label", ""),
                status,
                str(item.get("saved_at", ""))[:19],
            ))


if __name__ == "__main__":
    load_dotenv()
    DoNotStressApp().mainloop()
