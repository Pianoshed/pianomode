"""Publish the built-in progression templates as chord movements. Safe to run repeatedly.

cd backend && python -m scripts.seed_movements
"""

from app.core.db import get_session
from app.services import movement_service


def main() -> None:
    session = next(get_session())
    try:
        result = movement_service.seed_default_movements(session)
    finally:
        session.close()
    for key, items in result.items():
        print(f"{key}: {len(items)}")
        if key == "failed":
            for item in items:
                print(f"  {item}")


if __name__ == "__main__":
    main()
