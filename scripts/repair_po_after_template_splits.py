#!/usr/bin/env python3
"""Repair .po msgstr placeholder drift after template refactors (split strings + links).

Run from repo root after `pybabel update`:
    python3 scripts/repair_po_after_template_splits.py

Then: python3 -m babel.messages.frontend compile -d translations
"""
from __future__ import annotations

import re
from pathlib import Path

import polib

ROOT = Path(__file__).resolve().parent.parent
TRANS = ROOT / "translations"

WE_ANALYSE = (
    "we analyse voting patterns to identify natural opinion clusters, without "
    "labels, ideological assumptions, or demographic bias. This reveals how "
    "views actually form and overlap, something polls and comment sections "
    "consistently fail to capture."
)
USING_ML = "Using machine learning inspired by"
TRAD_POLL = (
    "Traditional polling gives you percentages. Comment sections amplify the loudest voices. Society Speaks shows you "
    "how views actually cluster — and where genuine common ground lies. Inspired by"
)
BUILT_DELIB = "built for deliberative democracy at any scale."
PIONEERED = (
    "pioneered this approach and used it for Taiwan's vTaiwan participatory democracy process — one of the most "
    "successful examples of digital deliberation in history. We are inspired by that work and the open-source "
    "research behind it."
)
YES_FREE = (
    "Yes — participating in discussions, creating discussions, and creating individual and organisation profiles are "
    "all free. Programmes are also free for most use cases. For large-scale institutional deployments with dedicated "
    "support, white-labelling, or advanced integrations,"
)
TRIAL_LEAD = (
    "You're one week into your Personal Brief trial. We hope the briefings are already saving you time. You have"
)
VOTED_ALL = "You voted on every statement in this theme (%(total)d)."
SUB_PAUSED = (
    "Your Society Speaks subscription has ended and your <strong>%(count)s briefings</strong> have been paused."
)


def truncate_at_named_placeholder(msgstr: str, name: str) -> str:
    tok = f"%({name})s"
    if tok not in msgstr:
        return msgstr
    return msgstr.split(tok)[0].rstrip(" ,")


def strip_leading_named_placeholder(msgstr: str, name: str) -> str:
    tok = f"%({name})s"
    if msgstr.startswith(tok):
        return msgstr[len(tok) :].lstrip()
    return msgstr


def split_prefix_through_polis_for_using_ml(rest: str) -> tuple[str, str]:
    """Split '… %(polis)s …' joined paragraph into (using_ml_frag, analyse_frag)."""
    s = rest.strip()
    m = re.match(r"^(.+?)%\(polis\)s\s*,?\s*(.+)$", s, re.DOTALL)
    if m:
        return m.group(1).rstrip().rstrip(","), m.group(2).lstrip()
    m2 = re.match(r"^%\(polis\)s\s*,?\s*(.+)$", s, re.DOTALL)
    if m2:
        return "", m2.group(1).lstrip()
    return "", rest


USING_FALLBACK_NO_PREFIX = {
    "ja": "Pol.is にインスピレーションを受けた機械学習により、",
    "ko": "Pol.is에서 영감을 받은 머신러닝을 활용하여,",
    "hi": "Pol.is से प्रेरित मशीन लर्निंग के साथ,",
}

WE_STRIP_LEAD = {
    "ja": r"^からインスピレーションを受けた機械学習を使用して、",
    "ko": r"^에서 영감을 받은 머신러닝을 사용하여,\s*",
    "hi": r"^से प्रेरित मशीन लर्निंग का उपयोग करते हुए,\s*",
}


SECTION_13 = {
    "ar": "القسم 1.3.",
    "de": "Abschnitt 1.3.",
    "es": "apartado 1.3.",
    "fr": "section 1.3.",
    "hi": "अनुभाग 1.3.",
    "ja": "第1.3項。",
    "ko": "1.3절.",
    "nl": "paragraaf 1.3.",
    "pt": "secção 1.3.",
    "zh": "第 1.3 节",
}

DAILY_SUBJECT = {
    "ar": "السؤال اليومي رقم %(num)s: %(topic)s",
    "de": "Tagesfrage Nr. %(num)s: %(topic)s",
    "es": "Pregunta diaria n.º %(num)s: %(topic)s",
    "fr": "Question quotidienne n°%(num)s : %(topic)s",
    "hi": "दैनिक प्रश्न %(num)s: %(topic)s",
    "ja": "デイリークエスチョン %(num)s：%(topic)s",
    "ko": "일일 질문 %(num)s: %(topic)s",
    "nl": "Dagelijkse vraag %(num)s: %(topic)s",
    "pt": "Pergunta diária n.º %(num)s: %(topic)s",
    "zh": "每日问题 %(num)s：%(topic)s",
}

WEEK_SUBJECT = {
    "ar": "5 أسئلة هذا الأسبوع: %(first)s...",
    "de": "5 Fragen diese Woche: %(first)s...",
    "es": "5 preguntas esta semana: %(first)s...",
    "fr": "5 questions cette semaine : %(first)s...",
    "hi": "इस सप्ताह के 5 प्रश्न: %(first)s...",
    "ja": "今週の5つの質問: %(first)s...",
    "ko": "이번 주 5가지 질문: %(first)s...",
    "nl": "5 vragen deze week: %(first)s...",
    "pt": "5 perguntas esta semana: %(first)s...",
    "zh": "本周 5 个问题：%(first)s...",
}

MONTH_SUBJECT = {
    "ar": "10 أسئلة هذا الشهر: %(first)s...",
    "de": "10 Fragen diesen Monat: %(first)s...",
    "es": "10 preguntas este mes: %(first)s...",
    "fr": "10 questions ce mois-ci : %(first)s...",
    "hi": "इस महीने के 10 प्रश्न: %(first)s...",
    "ja": "今月の10の質問: %(first)s...",
    "ko": "이번 달 10가지 질문: %(first)s...",
    "nl": "10 vragen deze maand: %(first)s...",
    "pt": "10 perguntas este mês: %(first)s...",
    "zh": "本月 10 个问题：%(first)s...",
}

VOTED_THEME = {
    "ar": "لقد صوّت على كل العبارات في هذا الموضوع (%(total)d).",
    "de": "Sie haben zu jeder Aussage in diesem Thema abgestimmt (%(total)d).",
    "es": "Has votado sobre todas las afirmaciones de este tema (%(total)d).",
    "fr": "Vous avez voté sur chaque affirmation de ce thème (%(total)d).",
    "hi": "आपने इस विषय की हर बात पर मतदान किया है (%(total)d)।",
    "ja": "このテーマのすべての表明に投票済みです（%(total)d）。",
    "ko": "이 주제의 모든 진술에 투표했습니다 (%(total)d).",
    "nl": "Je hebt op elke stelling in dit thema gestemd (%(total)d).",
    "pt": "Votou em todas as afirmações deste tema (%(total)d).",
}

SUB_COUNT_PAUSED = {
    "ar": (
        "انتهى اشتراكك في Society Speaks، وتم إيقاف "
        "<strong>%(count)s</strong> من رسائل الملخص مؤقتًا."
    ),
    "de": "Ihr Society Speaks-Abonnement ist beendet, und Ihre <strong>%(count)s Briefings</strong> wurden pausiert.",
    "es": "Tu suscripción a Society Speaks ha finalizado y se han pausado tus <strong>%(count)s boletines</strong>.",
    "fr": "Votre abonnement Society Speaks est terminé et vos <strong>%(count)s briefings</strong> ont été suspendus.",
    "hi": "आपका Society Speaks सदस्यता समाप्त हो गया है और आपके <strong>%(count)s ब्रीफिंग</strong> रोक दिए गए हैं।",
    "ja": "Society Speaks のご契約が終了し、<strong>%(count)s 件のブリーフィング</strong>が一時停止されました。",
    "ko": "Society Speaks 구독이 종료되어 <strong>브리핑 %(count)s개</strong>가 일시 중지되었습니다.",
    "nl": "Je Society Speaks-abonnement is beëindigd en je <strong>%(count)s briefings</strong> zijn gepauzeerd.",
    "pt": "A sua subscrição Society Speaks terminou e os seus <strong>%(count)s briefings</strong> foram suspensos.",
}

TRIAL_LEAD_FIX = {
    "zh": "您使用个人简报试用期已满一周。我们希望这些简报已在为您节省时间。接下来您还有",
}

COPY_OVERVIEW_LINK = {
    "ar": "انسخ رابط نظرة عامة على الرحلة",
    "de": "Überblicks-Link der Journey kopieren",
    "es": "Copiar enlace del resumen del recorrido",
    "fr": "Copier le lien de synthèse du parcours",
    "hi": "यात्रा अवलोकन लिंक कॉपी करें",
    "ja": "ジャーニー概要へのリンクをコピーする",
    "ko": "여정 개요 링크 복사",
    "nl": "Kopieer de overzichtslink van de journey",
    "pt": "Copiar link da visão geral da jornada",
    "zh": "复制历程概览链接",
}


def split_traditional_polispair(msgstr: str) -> tuple[str, str] | None:
    """Trad block ends before Pol.is; remainder continues after %(polis)s (e.g. JA/KR particles)."""
    if "%(polis)s" not in msgstr:
        return None
    a, b = msgstr.split("%(polis)s", 1)
    first, second = a.rstrip(), b.lstrip()
    if not second:
        return None
    return first, second


def strip_subject_after_polis(msgstr: str) -> str | None:
    """Remove %(polis)s plus subject marker (Pol.is link appears before the rest of the sentence)."""
    s = msgstr.strip()
    if not s.startswith("%(polis)s"):
        return None
    tail = s[len("%(polis)s") :].lstrip()
    for p in (
        "は",
        "が",
        "은",
        "는",
        "을",
        "를",
        "와",
        "과",
        "에게",
        "에게서",
        "에서",
    ):
        if tail.startswith(p):
            return tail[len(p) :].lstrip()
    for prefix in (
        "fue ",
        "Fue ",
        "foi ",
        "Foi ",
        "tem ",
        "Tem ",
        "hat ",
        "Hat ",
        "ha ",
        "Ha ",
        "har ",
        "Har ",
        "heeft ",
        "Heeft ",
    ):
        if tail.startswith(prefix):
            return tail[len(prefix) :].lstrip()
    return tail


def by_msgid(po: polib.POFile, msgid: str) -> polib.POEntry | None:
    for e in po:
        if e.msgid == msgid:
            return e
    return None


def repair_file(po_path: Path) -> int:
    locale = po_path.parent.parent.name
    po = polib.pofile(str(po_path))
    edits = 0

    # --- Daily / digest email subjects ---
    e = by_msgid(po, "Daily Question #%(num)s: %(topic)s")
    if e and locale in DAILY_SUBJECT and e.msgstr != DAILY_SUBJECT[locale]:
        e.msgstr = DAILY_SUBJECT[locale]
        _drop_fuzzy(e)
        edits += 1

    e = by_msgid(po, "5 Questions This Week: %(first)s...")
    if e and locale in WEEK_SUBJECT and e.msgstr != WEEK_SUBJECT[locale]:
        e.msgstr = WEEK_SUBJECT[locale]
        _drop_fuzzy(e)
        edits += 1

    e = by_msgid(po, "10 Questions This Month: %(first)s...")
    if e and locale in MONTH_SUBJECT and e.msgstr != MONTH_SUBJECT[locale]:
        e.msgstr = MONTH_SUBJECT[locale]
        _drop_fuzzy(e)
        edits += 1

    # --- section 1.3 (privacy cross-link) ---
    e = by_msgid(po, "section 1.3.")
    if e and locale in SECTION_13 and not (e.msgstr or "").strip():
        e.msgstr = SECTION_13[locale]
        _drop_fuzzy(e)
        edits += 1

    # --- about.html ML + Pol.is split ---
    e_use = by_msgid(po, USING_ML)
    e_we = by_msgid(po, WE_ANALYSE)
    if e_we and e_we.msgstr and "%(polis)s" in e_we.msgstr:
        prefix, suffix = split_prefix_through_polis_for_using_ml(e_we.msgstr.strip())
        inner = suffix
        if not prefix and locale in WE_STRIP_LEAD:
            inner = re.sub(WE_STRIP_LEAD[locale], "", inner, count=1)
        if not prefix and locale in USING_FALLBACK_NO_PREFIX and e_use:
            if not (e_use.msgstr or "").strip():
                e_use.msgstr = USING_FALLBACK_NO_PREFIX[locale]
                _drop_fuzzy(e_use)
                edits += 1
        elif prefix and e_use and not (e_use.msgstr or "").strip():
            e_use.msgstr = prefix.strip()
            _drop_fuzzy(e_use)
            edits += 1
        if inner != e_we.msgstr.strip():
            e_we.msgstr = inner.strip()
            _drop_fuzzy(e_we)
            edits += 1

    # --- platform Traditional polling ↔ built ---
    e_trad = by_msgid(po, TRAD_POLL)
    e_built = by_msgid(po, BUILT_DELIB)
    if e_trad and e_trad.msgstr:
        sp = split_traditional_polispair(e_trad.msgstr.strip())
        if sp:
            first, trailer = sp
            if first != e_trad.msgstr.strip():
                e_trad.msgstr = first
                _drop_fuzzy(e_trad)
                edits += 1
            if e_built and trailer and (not e_built.msgstr or not e_built.msgstr.strip()):
                e_built.msgstr = trailer
                _drop_fuzzy(e_built)
                edits += 1

    # --- platform pioneered (link before sentence) ---
    e = by_msgid(po, PIONEERED)
    if e and e.msgstr and e.msgstr.strip().startswith("%(polis)s"):
        nu = strip_subject_after_polis(e.msgstr.strip())
        if nu is None:
            nu = strip_leading_named_placeholder(e.msgstr.strip(), "polis").lstrip()
        if nu and nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    # --- entry point (link is separate in template) ---
    e = by_msgid(po, "is the entry point.")
    if e and e.msgstr:
        nu = e.msgstr.strip()
        if "%(daily_link)s" in nu:
            parts = re.split(r"\%\(daily_link\)s\s*", nu, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                nu = parts[1].lstrip()
            else:
                nu = strip_leading_named_placeholder(nu, "daily_link")
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    # --- content-policy embed ---
    e = by_msgid(
        po,
        "For data we collect in the embed context (e.g. session fingerprint, partner ref), see our",
    )
    if e and e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "privacy_link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    # --- pricing FAQ ---
    e = by_msgid(po, YES_FREE)
    if e and e.msgstr and "%(get_in_touch)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "get_in_touch")
        nu = nu.rstrip(".")
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    # --- Brief landing bias line ---
    e = by_msgid(po, "Bias ratings from")
    if e and e.msgstr and "%(allsides)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "allsides").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    RIGHTS = (
        "<strong>Your rights:</strong> You can request erasure or a copy of data we "
        "hold about you by contacting"
    )
    e = by_msgid(po, RIGHTS)
    if e and e.msgstr and "%(contact)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "contact").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    CONT_MONITOR = (
        "We continuously monitor <strong>140+ carefully selected news sources</strong>, "
        "including quality journalism outlets, policy publications, think tanks, "
        "investigative journalism, and intellectual podcasts. Each source is rated "
        "for political leaning using"
    )
    e = by_msgid(po, CONT_MONITOR)
    if e and e.msgstr and "%(allsides_link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "allsides_link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    SHOW_BALANCE = (
        'We show the balance not to say who\'s "right," but to help you see blind '
        "spots in coverage."
    )
    e = by_msgid(po, SHOW_BALANCE)
    if e and e.msgstr and "%(allsides_link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "allsides_link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    SRC_CLASS = "Source classifications based on"
    e = by_msgid(po, SRC_CLASS)
    if e and e.msgstr:
        nu = truncate_at_named_placeholder(
            truncate_at_named_placeholder(e.msgstr.strip(), "allsides"), "methodology"
        ).rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    WHERE_AVAIL = (
        "where available, with manual assessment for podcasts and newer publications. "
        "We update ratings monthly."
    )
    e = by_msgid(po, WHERE_AVAIL)
    if e and e.msgstr and "%(allsides_link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "allsides_link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    DONT_MAIL = "Don't want to receive any emails?"
    e = by_msgid(po, DONT_MAIL)
    if e and e.msgstr and "%(unsub_link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "unsub_link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    LOGGED_IN = "If you are logged in, you can also"
    e = by_msgid(po, LOGGED_IN)
    if e and e.msgstr and "%(open_prefs_link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "open_prefs_link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    ORG_POSTS = (
        "These posts are written by <strong>discussion organisers</strong> (for example "
        "policy outcomes, hearings, or next steps). They are <strong>not</strong> where "
        "you suggest new voting statements — use"
    )
    e = by_msgid(po, ORG_POSTS)
    if e and e.msgstr:
        nu = truncate_at_named_placeholder(
            truncate_at_named_placeholder(e.msgstr.strip(), "suggest_link"), "mod_link"
        ).rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    # --- brief tagline ---
    BRIEF_TAG = (
        "— our email newsletter that delivers the day's top stories with coverage "
        "analysis from multiple perspectives."
    )
    e = by_msgid(po, BRIEF_TAG)
    if e and e.msgstr and "%(brief_link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "brief_link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    ANYONE = (
        "Anyone can browse and participate — no account required to read, an account "
        "is needed to vote or submit statements."
    )
    e = by_msgid(po, ANYONE)
    if e and e.msgstr and "%(catalogue_link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "catalogue_link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    GO_PROG = (
        "<strong>Go to Programmes → New programme</strong> from the navigation menu, "
        "or visit"
    )
    e = by_msgid(po, GO_PROG)
    if e and e.msgstr and "%(link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    # --- partner docs fragments ---
    e = by_msgid(po, "to get your test API key and DNS verification token.")
    if e and e.msgstr and "%(link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    e = by_msgid(
        po,
        "to try browser-safe endpoints (lookup, snapshot, oEmbed) from Swagger UI.",
    )
    if e and e.msgstr and "%(link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    e = by_msgid(po, "or visit the")
    if e and e.msgstr and "%(link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    e = by_msgid(po, "Get test keys in the")
    if e and e.msgstr and "%(portal_link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "portal_link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    e = by_msgid(po, "for clarification on any of these rules.")
    if e and e.msgstr and "%(email_link)s" in e.msgstr:
        nu = truncate_at_named_placeholder(e.msgstr.strip(), "email_link").rstrip()
        if nu != e.msgstr.strip():
            e.msgstr = nu
            _drop_fuzzy(e)
            edits += 1

    # --- journeys ---
    if locale in COPY_OVERVIEW_LINK:
        e = by_msgid(po, "Copy journey overview link")
        if e:
            targ = COPY_OVERVIEW_LINK[locale]
            if e.msgstr != targ or "%(name)s" in (e.msgstr or ""):
                e.msgstr = targ
                _drop_fuzzy(e)
                edits += 1

    # --- recap / billing ---
    if locale in VOTED_THEME:
        e = by_msgid(po, VOTED_ALL)
        if e and ("%(total)d)" not in (e.msgstr or "")):
            e.msgstr = VOTED_THEME[locale]
            _drop_fuzzy(e)
            edits += 1

    if locale in SUB_COUNT_PAUSED:
        e = by_msgid(po, SUB_PAUSED)
        if e and "%(count)s" not in (e.msgstr or ""):
            e.msgstr = SUB_COUNT_PAUSED[locale]
            _drop_fuzzy(e)
            edits += 1

    # --- trial_mid split (zh-only bad merge spotted) ---
    if locale == "zh":
        e = by_msgid(po, TRIAL_LEAD)
        if e and TRIAL_LEAD_FIX["zh"] and e.msgstr != TRIAL_LEAD_FIX["zh"]:
            if "%(days_remaining)s" in (e.msgstr or ""):
                e.msgstr = TRIAL_LEAD_FIX["zh"]
                _drop_fuzzy(e)
                edits += 1

    po.save(str(po_path))
    return edits


def _drop_fuzzy(e: polib.POEntry) -> None:
    if "fuzzy" in e.flags:
        e.flags.remove("fuzzy")


def main() -> None:
    total = 0
    for po_path in sorted(TRANS.glob("*/LC_MESSAGES/messages.po")):
        total += repair_file(po_path)
    print(f"repair_po_after_template_splits: applied ~{total} entry updates")


if __name__ == "__main__":
    main()
