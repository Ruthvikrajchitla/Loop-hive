"""
LoopHive — Readability Analyzer

Implements readability scores (like Flesch-Kincaid) to measure text complexity.
"""

from __future__ import annotations

import re


class ReadabilityAnalyzer:
    """Analyzes text to compute standard readability indices."""

    @staticmethod
    def count_syllables(word: str) -> int:
        """Estimate the number of syllables in a word."""
        word = word.lower()
        if not word:
            return 0
            
        # Strip simple endings
        word = re.sub(r"[.,:;!?']", "", word)
        if len(word) <= 3:
            return 1
            
        # Simple vowel-based count
        vowels = "aeiouy"
        count = 0
        prev_is_vowel = False
        
        for char in word:
            is_vowel = char in vowels
            if is_vowel and not prev_is_vowel:
                count += 1
            prev_is_vowel = is_vowel
            
        # Adjust common silent suffixes
        if word.endswith("e"):
            count -= 1
        if word.endswith("es") or word.endswith("ed"):
            count -= 1
        if word.endswith("le") and len(word) > 2 and word[-3] not in vowels:
            count += 1
            
        return max(1, count)

    @classmethod
    def analyze(cls, text: str) -> dict:
        """
        Computes Flesch Reading Ease and Flesch-Kincaid Grade Level.

        Flesch Reading Ease:
        206.835 - 1.015 * (total_words / total_sentences) - 84.6 * (total_syllables / total_words)

        Flesch-Kincaid Grade Level:
        0.39 * (total_words / total_sentences) + 11.8 * (total_syllables / total_words) - 15.59
        """
        # Clean text
        text = re.sub(r"\s+", " ", text.strip())
        
        # Simple sentence split
        sentences = re.split(r"(?<=[.!?])\s+", text)
        sentences = [s for s in sentences if s.strip()]
        total_sentences = max(1, len(sentences))
        
        # Simple word split
        words = [w for w in text.split() if w.strip()]
        total_words = max(1, len(words))
        
        # Syllables
        total_syllables = sum(cls.count_syllables(w) for w in words)
        total_syllables = max(1, total_syllables)
        
        words_per_sentence = total_words / total_sentences
        syllables_per_word = total_syllables / total_words
        
        # Calculate Flesch Reading Ease
        reading_ease = 206.835 - (1.015 * words_per_sentence) - (84.6 * syllables_per_word)
        reading_ease = max(0.0, min(100.0, reading_ease))
        
        # Calculate Flesch-Kincaid Grade Level
        grade_level = (0.39 * words_per_sentence) + (11.8 * syllables_per_word) - 15.59
        grade_level = max(0.0, grade_level)
        
        # Interpret Reading Ease
        if reading_ease >= 90:
            interpretation = "Very Easy (5th grade)"
        elif reading_ease >= 80:
            interpretation = "Easy (6th grade)"
        elif reading_ease >= 70:
            interpretation = "Fairly Easy (7th grade)"
        elif reading_ease >= 60:
            interpretation = "Standard (8th-9th grade)"
        elif reading_ease >= 50:
            interpretation = "Fairly Difficult (High School)"
        elif reading_ease >= 30:
            interpretation = "Difficult (College)"
        else:
            interpretation = "Very Difficult (Graduate)"
            
        return {
            "sentences": total_sentences,
            "words": total_words,
            "syllables": total_syllables,
            "reading_ease": reading_ease,
            "grade_level": grade_level,
            "interpretation": interpretation,
        }
