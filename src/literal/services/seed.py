"""Seed service for initializing database with default data."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from literal.models import GrammaticalCase, User, UserCaseProgress

# Basque grammatical cases organized by learning level
# Based on EHU Basque Language Institute documentation
BASQUE_CASES = [
    # Level 1 - Core grammatical cases (essential for basic communication)
    {
        "name": "absolutive",
        "name_basque": "absolutiboa",
        "suffix": "∅/-a/-ak",
        "level": 1,
        "description": "Subject of intransitive verbs, object of transitive verbs. "
        "The default/unmarked case, used for naming and basic sentence objects.",
        "example_singular": "etxea",
        "example_plural": "etxeak",
    },
    {
        "name": "ergative",
        "name_basque": "ergatiboa",
        "suffix": "-k/-ek",
        "level": 1,
        "description": "Subject of transitive verbs (the agent performing the action). "
        "Marks who/what is doing the action to something else.",
        "example_singular": "etxeak",
        "example_plural": "etxeek",
    },
    {
        "name": "dative",
        "name_basque": "datiboa",
        "suffix": "-i/-ri/-ei",
        "level": 1,
        "description": "Indirect object, recipient of the action. "
        "Marks to whom/what something is given or directed.",
        "example_singular": "etxeari",
        "example_plural": "etxeei",
    },
    # Level 2 - Locative cases (location and direction)
    {
        "name": "inessive",
        "name_basque": "inesiboa",
        "suffix": "-n/-an/-etan",
        "level": 2,
        "description": "Location: in, on, at. Indicates where something is located.",
        "example_singular": "etxean",
        "example_plural": "etxeetan",
    },
    {
        "name": "adlative",
        "name_basque": "adlatiboa",
        "suffix": "-ra/-era/-etara",
        "level": 2,
        "description": "Direction: to, toward. Indicates movement toward a destination.",
        "example_singular": "etxera",
        "example_plural": "etxeetara",
    },
    {
        "name": "ablative",
        "name_basque": "ablatiboa",
        "suffix": "-tik/-etik/-etatik",
        "level": 2,
        "description": "Origin: from. Indicates the starting point or origin of movement.",
        "example_singular": "etxetik",
        "example_plural": "etxeetatik",
    },
    # Level 3 - Relational cases (possession, accompaniment, benefit)
    {
        "name": "genitive",
        "name_basque": "genitiboa",
        "suffix": "-ko/-eko/-etako",
        "level": 3,
        "description": "Possession and origin: of, from. "
        "Indicates ownership or where something originates.",
        "example_singular": "etxeko",
        "example_plural": "etxeetako",
    },
    {
        "name": "comitative",
        "name_basque": "soziatiboa",
        "suffix": "-ekin/-rekin",
        "level": 3,
        "description": "Accompaniment: with. Indicates being together with someone/something.",
        "example_singular": "etxearekin",
        "example_plural": "etxeekin",
    },
    {
        "name": "benefactive",
        "name_basque": "destinatiboa",
        "suffix": "-entzat/-rentzat",
        "level": 3,
        "description": "Beneficiary: for. Indicates for whose benefit an action is done.",
        "example_singular": "etxearentzat",
        "example_plural": "etxeentzat",
    },
    # Level 4 - Advanced cases (instrument, cause, role)
    {
        "name": "instrumental",
        "name_basque": "instrumentala",
        "suffix": "-z/-ez/-etaz",
        "level": 4,
        "description": "Means, manner, topic: by, with, about. "
        "Indicates the instrument used or topic discussed.",
        "example_singular": "etxeaz",
        "example_plural": "etxeetaz",
    },
    {
        "name": "motivative",
        "name_basque": "motibatiboa",
        "suffix": "-gatik/-engatik",
        "level": 4,
        "description": "Cause, reason: because of, for. "
        "Indicates the reason or cause of an action.",
        "example_singular": "etxeagatik",
        "example_plural": "etxeengatik",
    },
    {
        "name": "prolative",
        "name_basque": "prolatiboa",
        "suffix": "-tzat/-entzat",
        "level": 4,
        "description": "Role, function: as, for. "
        "Indicates the role or function something serves.",
        "example_singular": "etxetzat",
        "example_plural": "etxeetzat",
    },
    {
        "name": "partitive",
        "name_basque": "partitiboa",
        "suffix": "-ik/-rik",
        "level": 4,
        "description": "Partitive (negation, questions): any. "
        "Used in negative sentences and questions to indicate indefinite quantity.",
        "example_singular": "etxerik",
        "example_plural": "etxerik",
    },
]


async def seed_grammatical_cases(session: AsyncSession) -> int:
    """
    Seed the database with Basque grammatical cases.

    Returns the number of cases inserted (0 if already seeded).
    """
    # Check if already seeded
    result = await session.execute(select(GrammaticalCase).limit(1))
    if result.scalar_one_or_none() is not None:
        return 0

    # Insert all cases
    cases = [GrammaticalCase(**case_data) for case_data in BASQUE_CASES]
    session.add_all(cases)
    await session.commit()

    return len(cases)


async def seed_user_case_progress(session: AsyncSession, user_id: int) -> int:
    """
    Initialize case progress records for a user.

    Creates UserCaseProgress entries for all cases, with Level 1 cases
    automatically unlocked.

    Returns the number of progress records created.
    """
    # Get all cases
    result = await session.execute(select(GrammaticalCase).order_by(GrammaticalCase.level))
    cases = result.scalars().all()

    if not cases:
        raise ValueError("No grammatical cases found. Run seed_grammatical_cases first.")

    # Check if user already has progress records
    existing = await session.execute(
        select(UserCaseProgress).where(UserCaseProgress.user_id == user_id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return 0

    # Create progress records
    progress_records = []
    for case in cases:
        progress = UserCaseProgress(
            user_id=user_id,
            case_id=case.id,
            sentences_generated=0,
            sentences_reviewed=0,
            avg_interval=0.0,
            # Level 1 cases are unlocked by default
            unlocked=case.level == 1,
        )
        progress_records.append(progress)

    session.add_all(progress_records)
    await session.commit()

    return len(progress_records)


async def create_default_user(session: AsyncSession, username: str = "default") -> User:
    """
    Create a default user if none exists.

    Returns the existing or newly created user.
    """
    # Check if user exists
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is not None:
        return user

    # Create new user
    user = User(
        username=username,
        source_language="eu",  # Learning Basque
        target_language="fr",  # Native French
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return user


async def seed_all(session: AsyncSession) -> dict:
    """
    Run all seed operations.

    Returns a dict with counts of seeded items.
    """
    results = {}

    # Seed grammatical cases
    results["cases"] = await seed_grammatical_cases(session)

    # Create default user
    user = await create_default_user(session)
    results["user_id"] = user.id

    # Initialize case progress for default user
    results["progress"] = await seed_user_case_progress(session, user.id)

    return results
