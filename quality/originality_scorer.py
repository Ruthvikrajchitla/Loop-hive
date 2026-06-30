"""
LoopHive — Originality Scorer

Measures language diversity, repetition rate, and vocabulary range
to compute a structured originality score.
"""

from __future__ import annotations

import re


class OriginalityScorer:
    """Computes lexical diversity and structural variety to gauge originality."""

    @staticmethod
    def calculate_lexical_diversity(text: str) -> float:
        """Type-Token Ratio (TTR): unique words / total words."""
        # Clean text
        words = re.findall(r"\b\w+\b", text.lower())
        if not words:
            return 0.0
            
        unique_words = set(words)
        return len(unique_words) / len(words)

    @staticmethod
    def detect_repetitions(text: str, n: int = 3) -> float:
        """Finds repeating n-grams to detect AI-looping patterns."""
        words = re.findall(r"\b\w+\b", text.lower())
        if len(words) < n:
            return 0.0
            
        ngrams = [tuple(words[i:i+n]) for i in range(len(words)-n+1)]
        if not ngrams:
            return 0.0
            
        unique_ngrams = set(ngrams)
        repetition_rate = 1.0 - (len(unique_ngrams) / len(ngrams))
        return repetition_rate

    @classmethod
    def score(cls, text: str) -> dict:
        """
        Gives an originality score out of 100 based on TTR
        and inverse repetition rate.
        """
        diversity = cls.calculate_lexical_diversity(text)
        rep_3gram = cls.detect_repetitions(text, 3)
        rep_4gram = cls.detect_repetitions(text, 4)

        # Base calculations
        # High diversity = high score
        diversity_score = min(100.0, diversity * 150)  # Standard text TTR is around 0.4 - 0.6
        
        # High repetition = low score
        repetition_penalty = (rep_3gram * 50) + (rep_4gram * 50)
        
        final_score = diversity_score - repetition_penalty
        final_score = max(0.0, min(100.0, final_score))

        # Classify
        if final_score >= 85:
            classification = "Highly Creative"
        elif final_score >= 70:
            classification = "Standard Originality"
        elif final_score >= 50:
            classification = "Moderately Repetitive"
        else:
            classification = "Highly Repetitive / Bot-like"

        return {
            "lexical_diversity": diversity,
            "repetition_rate_3gram": rep_3gram,
            "repetition_rate_4gram": rep_4gram,
            "score": final_score,
            "classification": classification,
        }
