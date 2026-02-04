"""French sentence builder using OpenAI for the Mintzaira translation flow."""

import json
import random
from dataclasses import dataclass

from openai import AsyncOpenAI

from literal.models.case import GrammaticalCase
from literal.models.word import Word


@dataclass
class FrenchSentenceResult:
    """Result of French sentence generation."""

    sentence: str
    words_used: list[str]
    target_word_used: str


# Subject pronouns for varied conjugation practice
# Weighted to give more practice with less common forms
SUBJECT_PRONOUNS = [
    ("je", "1st person singular"),
    ("tu", "2nd person singular informal"),
    ("il", "3rd person singular masculine"),
    ("elle", "3rd person singular feminine"),
    ("nous", "1st person plural"),
    ("vous", "2nd person plural/formal"),
    ("ils", "3rd person plural masculine"),
    ("elles", "3rd person plural feminine"),
    ("on", "impersonal/informal nous"),
]


# Mapping from Basque grammatical cases to French sentence context
CASE_CONTEXT_MAP = {
    # Level 1 - Core cases
    "absolutive": "simple subject or direct object (le/la/les)",
    "ergative": "subject performing a transitive action on something",
    "dative": "indirect object - giving, receiving, or benefiting (à quelqu'un)",
    # Level 2 - Location cases
    "inessive": "being located in/at a place (dans, à, en)",
    "adlative": "movement toward a place (vers, à)",
    "ablative": "coming from a place (de, depuis)",
    # Level 3 - Relation cases
    "genitive": "possession or belonging (de + possessor)",
    "comitative": "being with someone/something (avec)",
    "benefactive": "doing something for someone (pour)",
    # Level 4 - Advanced cases
    "instrumental": "using something as a tool or means (avec, par)",
    "motivative": "reason or cause for action (à cause de, pour)",
    "prolative": "passing through or by way of (par, à travers)",
    "partitive": "partial quantity (du, de la, des)",
}


class FrenchSentenceBuilder:
    """
    Build simple French sentences using known vocabulary.

    Uses OpenAI to generate grammatically correct French sentences
    that can then be translated to Basque via Mintzaira.

    Example:
        builder = FrenchSentenceBuilder(client)
        result = await builder.build_sentence(
            target_word=word,
            context_words=[word1, word2],
            target_case=case,
        )
        print(result.sentence)  # "Nous mangeons de la viande."
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str = "gpt-4o-mini",
    ):
        """
        Initialize the French sentence builder.

        Args:
            client: OpenAI async client
            model: Model to use for generation
        """
        self.client = client
        self.model = model

    def _get_case_context(self, case: GrammaticalCase) -> str:
        """Get the French grammatical context for a Basque case."""
        return CASE_CONTEXT_MAP.get(
            case.name.lower(),
            "general context",
        )

    def _build_prompt(
        self,
        target_word: Word,
        context_words: list[Word],
        target_case: GrammaticalCase,
        subject_pronoun: tuple[str, str] | None = None,
    ) -> str:
        """
        Build the prompt for French sentence generation.

        Args:
            target_word: The word that must appear in the sentence
            context_words: Additional known words to use
            target_case: The grammatical case context
            subject_pronoun: Optional (pronoun, description) tuple for conjugation variety

        Returns:
            Formatted prompt string
        """
        # Get French words, filtering out any without French translations
        target_french = target_word.french_word or target_word.word
        context_french = [
            w.french_word or w.word
            for w in context_words
            if w.french_word or w.word
        ]

        case_context = self._get_case_context(target_case)

        # Build subject requirement
        if subject_pronoun:
            pronoun, description = subject_pronoun
            subject_requirement = f'- MUST use subject pronoun: "{pronoun}" ({description})'
            examples = {
                "je": '"Je mange du pain."',
                "tu": '"Tu regardes la maison."',
                "il": '"Il aime le chocolat."',
                "elle": '"Elle va à l\'école."',
                "nous": '"Nous allons à la maison."',
                "vous": '"Vous avez une grande table."',
                "ils": '"Ils mangent de la viande."',
                "elles": '"Elles aiment le vin."',
                "on": '"On va au magasin."',
            }
            example = examples.get(pronoun, '"Je mange du pain."')
        else:
            subject_requirement = "- Use any appropriate subject (je, tu, il, elle, nous, vous, ils, elles, on)"
            example = '"Nous allons à la maison."'

        prompt = f"""Generate a simple French sentence (4-10 words).

REQUIREMENTS:
- MUST use the target word: "{target_french}"
{subject_requirement}
- CAN use these context words (optional): {', '.join(context_french[:6]) if context_french else 'none'}
- Grammatical context: {case_context}
- Keep the sentence simple and natural
- Use common French structures
- CRITICAL: Correct gender agreement (mon/ma/mes, le/la/les, un/une/des)
  - "mon chat" (masc), "ma maison" (fem), "mon eau" (fem starts with vowel)

EXAMPLE: {example}

Return ONLY valid JSON:
{{"sentence": "Your French sentence here", "words_used": ["list", "of", "words", "used"], "target_word_used": "{target_french}"}}"""

        return prompt

    async def build_sentence(
        self,
        target_word: Word,
        context_words: list[Word],
        target_case: GrammaticalCase,
        subject_pronoun: tuple[str, str] | None = None,
        vary_pronouns: bool = True,
    ) -> FrenchSentenceResult | None:
        """
        Generate a simple French sentence using the given words.

        Args:
            target_word: The word that must appear in the sentence
            context_words: Additional known vocabulary to potentially use
            target_case: The grammatical case to practice (provides context)
            subject_pronoun: Optional specific pronoun to use (pronoun, description)
            vary_pronouns: If True and no subject_pronoun given, randomly select one

        Returns:
            FrenchSentenceResult with the generated sentence, or None if failed

        Example:
            result = await builder.build_sentence(
                target_word=meat_word,  # french_word="viande"
                context_words=[eat_word, we_word],
                target_case=ergative_case,
            )
            # result.sentence = "Nous mangeons de la viande."
        """
        # Select a random pronoun for variety if enabled
        if subject_pronoun is None and vary_pronouns:
            subject_pronoun = random.choice(SUBJECT_PRONOUNS)

        prompt = self._build_prompt(target_word, context_words, target_case, subject_pronoun)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a native French language expert. Generate simple, "
                            "grammatically PERFECT French sentences. "
                            "CRITICAL: Respect gender agreement (le/la, un/une, mon/ma, etc.). "
                            "Examples: 'mon chat' (masc), 'ma maison' (fem), 'mon eau' (fem but vowel). "
                            "Output valid JSON only."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=150,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if not content:
                return None

            data = json.loads(content)

            return FrenchSentenceResult(
                sentence=data.get("sentence", ""),
                words_used=data.get("words_used", []),
                target_word_used=data.get("target_word_used", ""),
            )

        except Exception as e:
            print(f"French sentence generation error: {e}")
            return None

    async def build_sentence_simple(
        self,
        french_words: list[str],
        context_hint: str = "",
    ) -> str | None:
        """
        Simplified sentence builder using just French word strings.

        Args:
            french_words: List of French words to use
            context_hint: Optional context hint (e.g., "location", "action")

        Returns:
            Generated French sentence or None if failed
        """
        if not french_words:
            return None

        prompt = f"""Generate a simple French sentence (4-10 words) using some of these words: {', '.join(french_words)}

{f'Context: {context_hint}' if context_hint else ''}

Return ONLY the French sentence, nothing else."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Generate simple French sentences. Return only the sentence.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=100,
            )

            content = response.choices[0].message.content
            return content.strip() if content else None

        except Exception as e:
            print(f"French sentence generation error: {e}")
            return None
