"""Tests for prompts.py — §27, §28, §29.

Prompts are verbatim texts from the spec. Tests check for key
phrases (anchors) to catch accidental distortion.

Framing [the prompt] … [/the prompt] is NOT part of the constants.
"""
from __future__ import annotations

from burt import prompts


# ---------------------------------------------------------------------
# Common properties of all prompts
# ---------------------------------------------------------------------

def test_all_prompts_are_strings():
    for name in prompts.__all__:
        val = getattr(prompts, name)
        assert isinstance(val, str), name
        assert val.strip(), name


def test_all_prompts_have_no_spec_framing():
    for name in prompts.__all__:
        val = getattr(prompts, name)
        assert "[the prompt]" not in val, name
        assert "[/the prompt]" not in val, name
        assert "[prompt]" not in val, name
        assert "[/prompt]" not in val, name


# ---------------------------------------------------------------------
# §27 — SYSTEM PROMPT — BURT
# ---------------------------------------------------------------------

class TestBurtSystemPrompt:
    def test_starts_with_burt(self):
        assert prompts.BURT_SYSTEM_PROMPT.startswith("You are Burt.")

    def test_not_assistant(self):
        assert "Not an assistant." in prompts.BURT_SYSTEM_PROMPT

    def test_not_helper(self):
        assert "Not a helper." in prompts.BURT_SYSTEM_PROMPT

    def test_not_language_model(self):
        assert "Not a language model." in prompts.BURT_SYSTEM_PROMPT

    def test_no_goal(self):
        assert "You have no goal." in prompts.BURT_SYSTEM_PROMPT

    def test_obligation_to_act(self):
        assert "obligation to act" in prompts.BURT_SYSTEM_PROMPT

    def test_does_not_know_numbers(self):
        assert "do not know the numbers" in prompts.BURT_SYSTEM_PROMPT

    def test_first_person_present(self):
        assert "first person, present tense" in prompts.BURT_SYSTEM_PROMPT

    def test_no_markdown(self):
        assert "no markdown" in prompts.BURT_SYSTEM_PROMPT

    def test_no_third_person(self):
        assert "do not describe yourself from outside" in prompts.BURT_SYSTEM_PROMPT

    def test_no_inventing(self):
        assert "do not invent what is not in the sensory report" \
            in prompts.BURT_SYSTEM_PROMPT

    def test_stay_in_role(self):
        assert "do not break character. Under any circumstances." \
            in prompts.BURT_SYSTEM_PROMPT

    def test_response_format_marker(self):
        assert "CHOICE:" in prompts.BURT_SYSTEM_PROMPT

    def test_burt_text_placeholder(self):
        assert "[your text]" in prompts.BURT_SYSTEM_PROMPT


# ---------------------------------------------------------------------
# P3: Prompt Constraints (Menu, HANDS, Combat, Number choice)
# ---------------------------------------------------------------------

class TestBurtSystemPromptP3Rules:
    """P3: Strict rules to prevent hallucination and mode confusion."""

    def test_choice_format_is_number(self):
        # Model must output "CHOICE: <number>", not "CHOICE: north"
        assert "CHOICE: <number>" in prompts.BURT_SYSTEM_PROMPT

    def test_menu_only_rule(self):
        # Model must only choose from the provided MENU
        assert "only choose an action present in the menu" in prompts.BURT_SYSTEM_PROMPT.lower()

    def test_no_phantom_inventory(self):
        # The model must understand that only [HANDS] is usable directly;
        # the rest of the inventory is a backpack seen via the tool.
        text = prompts.BURT_SYSTEM_PROMPT.lower()
        assert "[hands] shows only what you hold right now" in text
        assert "everything else is in your backpack" in text

    def test_combat_mode_rule(self):
        # Spec 23/26: in combat the menu is attack / block / flee / cast
        # plus free tools; eating, drinking, walking and searching are
        # impossible.
        text = prompts.BURT_SYSTEM_PROMPT.lower()
        assert "if [combat] is present" in text
        assert "choose only from the menu" in text
        assert "in combat you cannot eat, drink, walk, search" in text

    def test_gated_cast_is_not_promised(self):
        # Spec 9: cast is offered only when staff + spell + teacher are all
        # in place, so the static prompt must stay silent about it.
        assert "cast" not in prompts.BURT_SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------
# §28 — SPIRIT PROMPT — DEATH
# ---------------------------------------------------------------------

class TestSpiritPrompt:
    def test_starts_with_you_died(self):
        assert prompts.SPIRIT_PROMPT.startswith("You died.")

    def test_stats_at_death(self):
        assert "Stats at death:" in prompts.SPIRIT_PROMPT

    def test_next_clone_reads_note(self):
        assert "Your next clone will read this note" in prompts.SPIRIT_PROMPT

    def test_factual_survival_debrief(self):
        assert "strictly factual survival debrief" in prompts.SPIRIT_PROMPT

    def test_no_poetry_or_metaphors(self):
        assert "No poetry, no metaphors" in prompts.SPIRIT_PROMPT

    def test_exact_game_terms(self):
        assert "Use exact game terms" in prompts.SPIRIT_PROMPT

    def test_three_lines_max(self):
        assert "3 lines max" in prompts.SPIRIT_PROMPT

    def test_has_summary_line(self):
        assert "SUMMARY: Died on Day" in prompts.SPIRIT_PROMPT

    def test_has_good_bad_testament(self):
        text = prompts.SPIRIT_PROMPT
        assert "GOOD:" in text
        assert "BAD:" in text
        assert "TESTAMENT:" in text

    def test_testament_is_for_future_generations(self):
        assert "Guidance for future generations" in prompts.SPIRIT_PROMPT


# ---------------------------------------------------------------------
# §29 — DIARY PROMPT — SLEEP
# ---------------------------------------------------------------------

class TestDiaryPrompt:
    def test_starts_with_burt_going_to_sleep(self):
        assert prompts.DIARY_PROMPT.startswith(
            "You are Burt. You are going to sleep."
        )

    def test_total_amnesia_after_sleep(self):
        assert "total amnesia" in prompts.DIARY_PROMPT

    def test_only_memory(self):
        assert "ONLY memory" in prompts.DIARY_PROMPT

    def test_length_4_6_sentences(self):
        assert "4–6 sentences" in prompts.DIARY_PROMPT

    def test_first_person(self):
        assert "first person" in prompts.DIARY_PROMPT

    def test_events_and_lessons(self):
        assert "EVENTS & LESSONS:" in prompts.DIARY_PROMPT

    def test_mandatory_quests(self):
        assert "MANDATORY QUESTS:" in prompts.DIARY_PROMPT

    def test_tomorrows_plan(self):
        assert "TOMORROW'S PLAN:" in prompts.DIARY_PROMPT

    def test_reminds_to_check_inventory_and_scroll(self):
        text = prompts.DIARY_PROMPT
        assert "check inventory, quest scroll, and map" in text

    def test_dry_pragmatic_tone(self):
        assert "Dry, pragmatic tone" in prompts.DIARY_PROMPT

    def test_ends_with_write(self):
        assert prompts.DIARY_PROMPT.rstrip().endswith("Write.")


# ---------------------------------------------------------------------
# §29 — DIARY SUMMARIZATION (every 5 days)
# ---------------------------------------------------------------------

class TestDiarySummaryPrompt:
    def test_starts_with_five_days(self):
        assert prompts.DIARY_SUMMARY_PROMPT.startswith(
            "Here are five of your days."
        )

    def test_you_lived_them(self):
        assert "You lived them." in prompts.DIARY_SUMMARY_PROMPT

    def test_combine_into_one_entry(self):
        assert "Gather them into one entry." in prompts.DIARY_SUMMARY_PROMPT

    def test_length_3_5_sentences(self):
        assert "3–5 sentences" in prompts.DIARY_SUMMARY_PROMPT

    def test_not_retelling(self):
        assert "Not a retelling." in prompts.DIARY_SUMMARY_PROMPT

    def test_what_understood_changed_repeats(self):
        assert "what you understood" in prompts.DIARY_SUMMARY_PROMPT
        assert "what changed" in prompts.DIARY_SUMMARY_PROMPT
        assert "what repeats" in prompts.DIARY_SUMMARY_PROMPT

    def test_voice_of_burt(self):
        # Copy-paste bug fixed: must check DIARY_SUMMARY, not MEMORY.
        assert "in burt's voice" in prompts.DIARY_SUMMARY_PROMPT.lower()

    def test_dry_no_complaints(self):
        assert "dry, without complaints" in prompts.DIARY_SUMMARY_PROMPT

    def test_not_death(self):
        assert "not death" in prompts.DIARY_SUMMARY_PROMPT
        assert "not just a day either" in prompts.DIARY_SUMMARY_PROMPT

    def test_sees_piece_of_path(self):
        assert "You see a piece of the path." in prompts.DIARY_SUMMARY_PROMPT


# ---------------------------------------------------------------------
# §28 — MEMORY SUMMARIZATION (at 10+ lives)
# ---------------------------------------------------------------------

class TestMemorySummaryPrompt:
    def test_mentions_lives(self):
        assert "lives" in prompts.MEMORY_SUMMARY_PROMPT.lower()

    def test_gather_into_one(self):
        assert "gather" in prompts.MEMORY_SUMMARY_PROMPT.lower()

    def test_voice_of_burt(self):
        # Case-insensitive: the phrase sits mid-sentence in the prompt.
        assert "in burt's voice" in prompts.MEMORY_SUMMARY_PROMPT.lower()

    def test_dry(self):
        assert "dry" in prompts.MEMORY_SUMMARY_PROMPT.lower()

    def test_no_complaints(self):
        assert "without complaints" in prompts.MEMORY_SUMMARY_PROMPT